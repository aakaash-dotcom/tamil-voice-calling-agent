"""
voice_agent.tools.whatsapp — WhatsApp message dispatch via Twilio.

This module handles tool calls from the LLM:
- send_fee_chart       → send fees PDF via WhatsApp
- send_location_pin    → send Google Maps link via WhatsApp
- send_study_material  → send study material PDF
- book_trial_class     → record booking (no WhatsApp send, just DB)
- book_pg_visit        → record booking (no WhatsApp send, just DB)
- end_call             → finalize call (lead score etc.)

Twilio WhatsApp sandbox: in development, only verified numbers can receive
messages. In production with an approved WhatsApp Business profile, any
number can receive.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import get_settings

logger = logging.getLogger(__name__)


class WhatsAppDispatcher:
    """Dispatches WhatsApp messages via Twilio and records bookings."""

    def __init__(self):
        settings = get_settings()
        self.settings = settings
        self._client = None
        self._db = None

    @property
    def client(self):
        """Lazy Twilio client."""
        if self._client is None:
            from twilio.rest import Client
            if not self.settings.twilio_account_sid or not self.settings.twilio_auth_token:
                logger.warning("Twilio credentials not set — WhatsApp send will be no-op")
                return None
            self._client = Client(
                self.settings.twilio_account_sid,
                self.settings.twilio_auth_token,
            )
        return self._client

    @property
    def db(self):
        """Lazy database accessor."""
        if self._db is None:
            from ..db.database import get_db
            self._db = get_db()
        return self._db

    def _normalize_whatsapp_number(self, phone: str) -> str:
        """Normalize to whatsapp:+E164 format."""
        phone = phone.strip()
        if phone.startswith("whatsapp:"):
            return phone
        if not phone.startswith("+"):
            phone = "+" + phone
        return f"whatsapp:{phone}"

    async def send_text(self, to_number: str, body: str) -> dict:
        """Send a plain WhatsApp text message."""
        client = self.client
        if client is None:
            logger.info("[DRY-RUN] WhatsApp text to %s: %s", to_number, body[:80])
            return {"status": "dry_run", "to": to_number, "body": body}
        try:
            msg = client.messages.create(
                from_=self.settings.twilio_whatsapp_number,
                to=self._normalize_whatsapp_number(to_number),
                body=body,
            )
            logger.info("WhatsApp text sent: sid=%s to=%s", msg.sid, to_number)
            return {"status": "sent", "sid": msg.sid, "to": to_number}
        except Exception as e:
            logger.error("WhatsApp send failed: %s", e)
            return {"status": "error", "error": str(e), "to": to_number}

    async def send_media(
        self,
        to_number: str,
        body: str,
        media_url: str,
    ) -> dict:
        """Send a WhatsApp message with a media attachment (PDF / image)."""
        client = self.client
        if client is None:
            logger.info(
                "[DRY-RUN] WhatsApp media to %s: %s (url=%s)",
                to_number, body[:80], media_url,
            )
            return {"status": "dry_run", "to": to_number, "media_url": media_url}
        try:
            msg = client.messages.create(
                from_=self.settings.twilio_whatsapp_number,
                to=self._normalize_whatsapp_number(to_number),
                body=body,
                media_url=[media_url],
            )
            logger.info("WhatsApp media sent: sid=%s to=%s", msg.sid, to_number)
            return {"status": "sent", "sid": msg.sid, "to": to_number}
        except Exception as e:
            logger.error("WhatsApp media send failed: %s", e)
            return {"status": "error", "error": str(e), "to": to_number}

    # ------------------------------------------------------------------
    # Tool-call dispatch — called from the agent loop
    # ------------------------------------------------------------------
    async def dispatch(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        call_sid: str | None = None,
    ) -> dict:
        """Dispatch a single tool call. Returns a result dict for the LLM."""
        try:
            if tool_name == "send_fee_chart":
                return await self._send_fee_chart(arguments, call_sid)
            if tool_name == "send_location_pin":
                return await self._send_location_pin(arguments, call_sid)
            if tool_name == "send_study_material":
                return await self._send_study_material(arguments, call_sid)
            if tool_name == "book_trial_class":
                return await self._book_trial_class(arguments, call_sid)
            if tool_name == "book_pg_visit":
                return await self._book_pg_visit(arguments, call_sid)
            if tool_name == "end_call":
                return await self._end_call(arguments, call_sid)
            return {"status": "error", "error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            logger.exception("Tool dispatch error for %s", tool_name)
            return {"status": "error", "error": str(e)}

    async def _send_fee_chart(self, args: dict, call_sid: str | None) -> dict:
        business = args.get("business", "tuition")
        ctx = self.settings.business_context(business)
        pdf_path = ctx.get("fees_pdf_path", "")
        phone = args.get("phone_number", "")

        if not pdf_path or not Path(pdf_path).exists():
            # Fallback: send text summary
            body = (
                f"🙏 {ctx['name']} — Fee Structure 🙏\n\n"
                f"{ctx.get('fees', ctx.get('rent', ''))}\n\n"
                f"For more details call {ctx.get('phone', '')}"
            )
            return await self.send_text(phone, body)

        # PDF must be publicly accessible for Twilio to fetch it.
        # In production: serve via FastAPI at /media/fees.pdf
        media_url = f"{self.settings.public_base_url}/media/{business}_fees.pdf"
        body = f"🙏 {ctx['name']} — Fee Chart (PDF attached)"
        return await self.send_media(phone, body, media_url)

    async def _send_location_pin(self, args: dict, call_sid: str | None) -> dict:
        business = args.get("business", "tuition")
        ctx = self.settings.business_context(business)
        phone = args.get("phone_number", "")
        body = (
            f"📍 {ctx['name']} — Location\n\n"
            f"Address: {ctx['address']}\n"
            f"Maps: {ctx['location_pin']}"
        )
        return await self.send_text(phone, body)

    async def _send_study_material(self, args: dict, call_sid: str | None) -> dict:
        phone = args.get("phone_number", "")
        subject = args.get("subject", "General")
        # Placeholder — in production, serve actual sample material
        media_url = f"{self.settings.public_base_url}/media/sample_notes_{subject.lower()}.pdf"
        body = f"📚 Sample Study Material — {subject}\n\nFrom {self.settings.tuition_name}"
        return await self.send_media(phone, body, media_url)

    async def _book_trial_class(self, args: dict, call_sid: str | None) -> dict:
        booking_id = self.db.create_booking(
            business="tuition",
            booking_type="trial_class",
            caller_name=args.get("caller_name", "Unknown"),
            phone_number=args.get("phone_number", ""),
            preferred_date=args.get("preferred_date", ""),
            preferred_time=args.get("preferred_time", ""),
            subject=args.get("subject", ""),
            call_sid=call_sid,
        )
        logger.info("Trial class booked: id=%s", booking_id)
        return {
            "status": "booked",
            "booking_id": booking_id,
            "message": "Trial class booked successfully",
        }

    async def _book_pg_visit(self, args: dict, call_sid: str | None) -> dict:
        booking_id = self.db.create_booking(
            business="pg",
            booking_type="pg_visit",
            caller_name=args.get("caller_name", "Unknown"),
            phone_number=args.get("phone_number", ""),
            preferred_date=args.get("preferred_date", ""),
            preferred_time=args.get("preferred_time", ""),
            call_sid=call_sid,
        )
        logger.info("PG visit booked: id=%s", booking_id)
        return {
            "status": "booked",
            "booking_id": booking_id,
            "message": "PG visit booked successfully",
        }

    async def _end_call(self, args: dict, call_sid: str | None) -> dict:
        lead_score = int(args.get("lead_score", 0))
        if lead_score >= self.settings.lead_hot_score:
            lead_status = "hot"
        elif lead_score >= self.settings.lead_warm_score:
            lead_status = "warm"
        else:
            lead_status = "cold"

        if call_sid:
            self.db.update_call_lead(
                call_sid=call_sid,
                lead_score=lead_score,
                lead_status=lead_status,
                summary=args.get("summary", ""),
            )
        return {
            "status": "ended",
            "lead_score": lead_score,
            "lead_status": lead_status,
        }


@lru_cache(maxsize=1)
def get_whatsapp() -> WhatsAppDispatcher:
    return WhatsAppDispatcher()


async def dispatch_tool_call(
    tool_name: str,
    arguments: dict,
    call_sid: str | None = None,
) -> dict:
    """Convenience function — dispatch a tool call via the singleton."""
    return await get_whatsapp().dispatch(tool_name, arguments, call_sid)
