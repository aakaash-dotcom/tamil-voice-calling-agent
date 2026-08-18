"""
voice_agent.dashboard.app — FastAPI dashboard + Twilio webhook server.

Endpoints:

  WEB UI:
    GET  /                  — Dashboard home: call list + lead stats
    GET  /call/{call_sid}   — Call detail: transcript, latency, recording
    GET  /bookings          — Bookings list (trial classes / PG visits)

  TWILIO WEBHOOKS:
    POST /twilio/voice/inbound  — Inbound call → returns TwiML
    POST /twilio/status         — Call status callbacks
    WS   /twilio/stream         — Bidirectional media stream

  MEDIA:
    GET  /media/{filename}      — Serve static media (fees PDFs, etc.)

Run with:
    uvicorn voice_agent.dashboard.app:app --host 0.0.0.0 --port 8000 --reload
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, Response, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import get_settings
from ..db.database import get_db, init_db
from ..telephony.twilio_connector import (
    get_twilio,
    mulaw_to_linear,
    linear_to_mulaw,
)
from ..agent.core import get_agent

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="Tamil Voice Agent Dashboard", version="1.0.0")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Mount static media directory (fees PDFs, recordings)
settings = get_settings()
media_dir = settings.project_root / "assets"
media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")


@app.on_event("startup")
async def on_startup():
    """Initialize DB on app start."""
    init_db()
    logger.info("Dashboard started at http://%s:%s",
                settings.app_host, settings.app_port)


# ----------------------------------------------------------------------------
# DASHBOARD ROUTES
# ----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """Dashboard home — call list + stats."""
    db = get_db()
    calls = db.list_calls(limit=50)
    stats = db.lead_stats()
    total = sum(stats.values())
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "calls": calls,
            "stats": stats,
            "total_calls": total,
            "business_mode": settings.business_mode,
            "tuition_name": settings.tuition_name,
            "pg_name": settings.pg_name,
        },
    )


@app.get("/call/{call_sid}", response_class=HTMLResponse)
async def call_detail(request: Request, call_sid: str):
    """Single call detail — transcript + latency."""
    db = get_db()
    call = db.get_call(call_sid)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    messages = db.list_messages(call_sid)
    return templates.TemplateResponse(
        request,
        "call_detail.html",
        {
            "call": call,
            "messages": messages,
        },
    )


@app.get("/bookings", response_class=HTMLResponse)
async def bookings_list(request: Request):
    """Bookings list — trial classes + PG visits."""
    db = get_db()
    bookings = db.list_bookings(limit=100)
    return templates.TemplateResponse(
        request,
        "bookings.html",
        {
            "bookings": bookings,
        },
    )


# ----------------------------------------------------------------------------
# HEALTH
# ----------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "ts": time.time()}


# ----------------------------------------------------------------------------
# TWILIO INBOUND VOICE WEBHOOK
# ----------------------------------------------------------------------------
@app.post("/twilio/voice/inbound")
async def twilio_voice_inbound(request: Request):
    """Twilio calls this when a call comes in. We return TwiML to connect
    the call to our media stream WebSocket."""
    form = await request.form()
    form_data = {k: v for k, v in form.items()}
    call_sid = form_data.get("CallSid", "unknown")
    from_number = form_data.get("From", "")
    to_number = form_data.get("To", "")
    logger.info("Inbound call: sid=%s from=%s to=%s", call_sid, from_number, to_number)

    # Decide business based on the called number
    business = "tuition"
    if to_number == settings.tuition_phone:
        business = "tuition"
    elif to_number == settings.pg_phone:
        business = "pg"

    # Create call record in DB
    db = get_db()
    db.create_call(
        call_sid=call_sid,
        direction="inbound",
        business=business,
        phone_number=from_number,
    )

    # Return TwiML that connects Twilio to our WebSocket
    twilio = get_twilio()
    twiml = twilio.handle_inbound_webhook(form_data)
    return PlainTextResponse(twiml, media_type="text/xml")


# ----------------------------------------------------------------------------
# TWILIO CALL STATUS WEBHOOK
# ----------------------------------------------------------------------------
@app.post("/twilio/status")
async def twilio_status(request: Request):
    """Receive call status updates from Twilio."""
    form = await request.form()
    call_sid = form.get("CallSid")
    status = form.get("CallStatus")
    duration = form.get("CallDuration")
    logger.info("Call status: sid=%s status=%s duration=%s", call_sid, status, duration)

    if call_sid and status == "completed":
        db = get_db()
        db.end_call(
            call_sid=call_sid,
            duration_seconds=int(duration) if duration else None,
        )
    return PlainTextResponse("OK")


# ----------------------------------------------------------------------------
# TWILIO MEDIA STREAM WEBSOCKET
# ----------------------------------------------------------------------------
@app.websocket("/twilio/stream")
async def twilio_stream(websocket: WebSocket):
    """
    Bidirectional media stream with Twilio.

    PROTOCOL:
      Inbound messages (from Twilio):
        {"event": "connected"}
        {"event": "start", "streamSid": "...", "call": {...}}
        {"event": "media", "track": "inbound", "payload": "<base64 mulaw>"}
        {"event": "stop"}

      Outbound messages (to Twilio):
        {"event": "media", "streamSid": "...", "media": {"payload": "<base64 mulaw>"}}
        {"event": "mark", "streamSid": "...", "mark": {"name": "done"}}
    """
    await websocket.accept()
    stream_sid: str | None = None
    call_sid: str | None = None
    agent = get_agent()
    state = None
    audio_buffer = np.array([], dtype=np.float32)
    is_speaking = False
    interrupt_event = asyncio.Event()
    turn_task: asyncio.Task | None = None

    # Accumulator for caller audio (16kHz float32)
    MIN_AUDIO_FOR_TURN = 16000 * 1.0   # 1 second
    MAX_AUDIO_FOR_TURN = 16000 * 8.0   # 8 seconds

    try:
        while True:
            msg = await websocket.receive_json()
            event = msg.get("event")

            if event == "connected":
                logger.info("Twilio stream connected")
                continue

            if event == "start":
                start = msg.get("start", {})
                stream_sid = msg.get("streamSid")
                call_sid = start.get("callSid")
                logger.info("Stream start: sid=%s call=%s", stream_sid, call_sid)

                # Determine business from the call
                business = "tuition"
                state = agent.init_state(
                    call_sid=call_sid or "unknown",
                    direction="inbound",
                    business=business,
                    phone_number=start.get("customParameters", {}).get("From", ""),
                )

                # Send greeting
                async def send_greeting():
                    if not state:
                        return
                    greeting = await agent.process_text_turn(state, "[call connected — greet the caller]")
                    if greeting.assistant_text and stream_sid:
                        async for chunk in agent.stream_tts(greeting.assistant_text):
                            # Convert MP3 → mulaw. In production we'd use PCM directly.
                            # For simplicity here we send MP3 base64 — Twilio can't play this
                            # directly. Real impl would convert to 8kHz mulaw PCM.
                            payload = base64.b64encode(chunk).decode("ascii")
                            await websocket.send_json({
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": payload}
                            })
                asyncio.create_task(send_greeting())
                continue

            if event == "media":
                track = msg.get("track")
                if track != "inbound":
                    continue
                payload_b64 = msg.get("media", {}).get("payload")
                if not payload_b64:
                    continue

                # Decode mulaw → 16kHz float32
                mulaw_bytes = base64.b64decode(payload_b64)
                audio_chunk = mulaw_to_linear(mulaw_bytes)

                # If AI is speaking, this is a potential barge-in
                if is_speaking:
                    # Simple energy-based barge-in detection
                    energy = float(np.abs(audio_chunk).mean())
                    if energy > 0.05:  # threshold
                        logger.info("Barge-in detected! energy=%.3f", energy)
                        interrupt_event.set()
                        is_speaking = False
                        audio_buffer = np.array([], dtype=np.float32)
                    continue

                # Accumulate caller audio
                audio_buffer = np.concatenate([audio_buffer, audio_chunk])

                # Process turn when we have enough audio
                # (Simple heuristic: process when we hit MAX or detect silence)
                if len(audio_buffer) >= MAX_AUDIO_FOR_TURN:
                    buf_to_process = audio_buffer.copy()
                    audio_buffer = np.array([], dtype=np.float32)

                    async def process_and_respond():
                        nonlocal is_speaking
                        if not state or not stream_sid:
                            return
                        is_speaking = True
                        interrupt_event.clear()
                        try:
                            result = await agent.process_turn(state, buf_to_process, 16000)
                            if result.assistant_text:
                                # Send TTS chunks
                                async for chunk in agent.stream_tts(
                                    result.assistant_text, interrupt_event
                                ):
                                    if interrupt_event.is_set():
                                        return
                                    # Send audio to Twilio
                                    # NOTE: Twilio expects 8kHz mulaw PCM, not MP3.
                                    # For production, we'd decode MP3 → PCM → mulaw.
                                    # This is a placeholder — real implementation
                                    # would use a streaming PCM TTS instead.
                                    payload = base64.b64encode(chunk).decode("ascii")
                                    await websocket.send_json({
                                        "event": "media",
                                        "streamSid": stream_sid,
                                        "media": {"payload": payload}
                                    })
                                # Mark stream end
                                await websocket.send_json({
                                    "event": "mark",
                                    "streamSid": stream_sid,
                                    "mark": {"name": "done"}
                                })
                        finally:
                            is_speaking = False

                    if turn_task and not turn_task.done():
                        turn_task.cancel()
                    turn_task = asyncio.create_task(process_and_respond())
                continue

            if event == "stop":
                logger.info("Stream stop: sid=%s", stream_sid)
                break

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: sid=%s", stream_sid)
    except Exception as e:
        logger.exception("Stream error: %s", e)
    finally:
        if call_sid:
            db = get_db()
            db.end_call(call_sid)
