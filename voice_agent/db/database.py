"""
voice_agent.db.database — SQLite persistence for calls, transcripts, leads, bookings.

Schema:
- calls          : one row per call (inbound or outbound)
- messages       : one row per turn (user or assistant)
- bookings       : trial classes / PG visits
- recordings     : call recording metadata
- lead_events    : tool calls + lead score updates

We use raw sqlite3 with row_factory — no ORM bloat, fastest possible queries.
All writes are synchronous (SQLite is fast enough for our call volume).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import get_settings

logger = logging.getLogger(__name__)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_sid TEXT UNIQUE NOT NULL,
    direction TEXT NOT NULL,             -- inbound | outbound
    business TEXT NOT NULL,              -- tuition | pg
    phone_number TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds INTEGER,
    lead_score INTEGER DEFAULT 0,
    lead_status TEXT DEFAULT 'cold',     -- hot | warm | cold
    summary TEXT,
    recording_url TEXT,
    campaign_id TEXT,
    status TEXT DEFAULT 'active'         -- active | completed | failed
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_sid TEXT NOT NULL,
    role TEXT NOT NULL,                  -- user | assistant | tool
    content TEXT NOT NULL,
    tool_name TEXT,
    tool_args TEXT,                      -- JSON
    tool_result TEXT,                    -- JSON
    latency_ms INTEGER,                  -- STT or LLM latency for this turn
    created_at TEXT NOT NULL,
    FOREIGN KEY (call_sid) REFERENCES calls(call_sid)
);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_sid TEXT,
    business TEXT NOT NULL,
    booking_type TEXT NOT NULL,          -- trial_class | pg_visit
    caller_name TEXT,
    phone_number TEXT NOT NULL,
    preferred_date TEXT,
    preferred_time TEXT,
    subject TEXT,
    status TEXT DEFAULT 'pending',       -- pending | confirmed | cancelled
    created_at TEXT NOT NULL,
    FOREIGN KEY (call_sid) REFERENCES calls(call_sid)
);

CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_sid TEXT NOT NULL,
    file_path TEXT NOT NULL,
    duration_seconds INTEGER,
    format TEXT DEFAULT 'wav',
    created_at TEXT NOT NULL,
    FOREIGN KEY (call_sid) REFERENCES calls(call_sid)
);

CREATE INDEX IF NOT EXISTS idx_calls_phone ON calls(phone_number);
CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status);
CREATE INDEX IF NOT EXISTS idx_calls_started ON calls(started_at);
CREATE INDEX IF NOT EXISTS idx_messages_call ON messages(call_sid);
CREATE INDEX IF NOT EXISTS idx_bookings_phone ON bookings(phone_number);
"""


class Database:
    """Thread-safe SQLite wrapper. Connection per-thread."""

    def __init__(self, db_path: str | None = None):
        settings = get_settings()
        self.db_path = db_path or settings.database_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Each thread gets its own connection."""
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self):
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        logger.info("Database initialized at %s", self.db_path)

    # ------------------------------------------------------------------
    # CALLS
    # ------------------------------------------------------------------
    def create_call(
        self,
        call_sid: str,
        direction: str,
        business: str,
        phone_number: str,
        campaign_id: str | None = None,
    ) -> int:
        """Insert a new call row. Returns the call id."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """INSERT INTO calls
               (call_sid, direction, business, phone_number, started_at, campaign_id, status)
               VALUES (?, ?, ?, ?, ?, ?, 'active')""",
            (call_sid, direction, business, phone_number, now, campaign_id),
        )
        conn.commit()
        return cur.lastrowid

    def end_call(
        self,
        call_sid: str,
        duration_seconds: int | None = None,
        recording_url: str | None = None,
    ):
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """UPDATE calls
               SET ended_at = ?, duration_seconds = ?, recording_url = ?, status = 'completed'
               WHERE call_sid = ?""",
            (now, duration_seconds, recording_url, call_sid),
        )
        conn.commit()

    def update_call_lead(
        self,
        call_sid: str,
        lead_score: int,
        lead_status: str,
        summary: str,
    ):
        conn = self._get_conn()
        conn.execute(
            """UPDATE calls
               SET lead_score = ?, lead_status = ?, summary = ?
               WHERE call_sid = ?""",
            (lead_score, lead_status, summary, call_sid),
        )
        conn.commit()

    def get_call(self, call_sid: str) -> dict | None:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM calls WHERE call_sid = ?", (call_sid,)).fetchone()
        return dict(row) if row else None

    def list_calls(self, limit: int = 50, offset: int = 0, business: str | None = None) -> list[dict]:
        conn = self._get_conn()
        if business:
            rows = conn.execute(
                "SELECT * FROM calls WHERE business = ? ORDER BY started_at DESC LIMIT ? OFFSET ?",
                (business, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM calls ORDER BY started_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_calls(self, business: str | None = None) -> int:
        conn = self._get_conn()
        if business:
            row = conn.execute(
                "SELECT COUNT(*) as n FROM calls WHERE business = ?", (business,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as n FROM calls").fetchone()
        return row["n"] if row else 0

    def lead_stats(self) -> dict:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT lead_status, COUNT(*) as n
               FROM calls GROUP BY lead_status"""
        ).fetchall()
        return {r["lead_status"]: r["n"] for r in rows}

    # ------------------------------------------------------------------
    # MESSAGES
    # ------------------------------------------------------------------
    def add_message(
        self,
        call_sid: str,
        role: str,
        content: str,
        tool_name: str | None = None,
        tool_args: dict | None = None,
        tool_result: dict | None = None,
        latency_ms: int | None = None,
    ):
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO messages
               (call_sid, role, content, tool_name, tool_args, tool_result, latency_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                call_sid, role, content,
                tool_name,
                json.dumps(tool_args) if tool_args else None,
                json.dumps(tool_result) if tool_result else None,
                latency_ms,
                now,
            ),
        )
        conn.commit()

    def list_messages(self, call_sid: str) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM messages WHERE call_sid = ? ORDER BY id ASC",
            (call_sid,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # BOOKINGS
    # ------------------------------------------------------------------
    def create_booking(
        self,
        business: str,
        booking_type: str,
        caller_name: str,
        phone_number: str,
        preferred_date: str,
        preferred_time: str,
        subject: str | None = None,
        call_sid: str | None = None,
    ) -> int:
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """INSERT INTO bookings
               (call_sid, business, booking_type, caller_name, phone_number,
                preferred_date, preferred_time, subject, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                call_sid, business, booking_type, caller_name, phone_number,
                preferred_date, preferred_time, subject, now,
            ),
        )
        conn.commit()
        return cur.lastrowid

    def list_bookings(self, limit: int = 50) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM bookings ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # RECORDINGS
    # ------------------------------------------------------------------
    def add_recording(
        self,
        call_sid: str,
        file_path: str,
        duration_seconds: int | None = None,
        fmt: str = "wav",
    ) -> int:
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """INSERT INTO recordings
               (call_sid, file_path, duration_seconds, format, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (call_sid, file_path, duration_seconds, fmt, now),
        )
        conn.commit()
        return cur.lastrowid


@lru_cache(maxsize=1)
def get_db() -> Database:
    return Database()


def init_db():
    """Explicitly initialize the DB (called on app startup)."""
    return get_db()
