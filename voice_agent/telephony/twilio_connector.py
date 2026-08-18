"""
voice_agent.telephony.twilio_connector — Twilio Voice + WhatsApp integration.

INBOUND flow:
    1. Twilio webhook → /twilio/voice/inbound
    2. Respond with TwiML <Connect><Stream> pointing to our WebSocket
    3. Twilio opens bidirectional WebSocket to /twilio/stream
    4. Caller audio (mulaw 8kHz) → STT → LLM → TTS → send back

OUTBOUND flow:
    1. POST to Twilio Calls API with TwiML connecting to our WebSocket
    2. Same WebSocket streaming flow as inbound

Audio format conversion:
    - Twilio stream: 8kHz mulaw (G.711 µ-law), 20ms chunks (160 samples)
    - Whisper wants: 16kHz float32 mono
    - Pure NumPy & audioop-lts fallback (Python 3.10 to 3.14+ compatible)
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
from functools import lru_cache
from typing import AsyncIterator

import numpy as np

from ..config import get_settings

logger = logging.getLogger(__name__)

# Safe audioop fallback for Python 3.10 to 3.14+
try:
    import audioop
except ImportError:
    try:
        import audioop_lts as audioop
    except ImportError:
        audioop = None


# ----------------------------------------------------------------------------
# MULAW <-> LINEAR conversion (G.711 µ-law, the standard for PSTN)
# ----------------------------------------------------------------------------
def mulaw_to_linear(mulaw_bytes: bytes, sample_rate: int = 8000) -> np.ndarray:
    """Convert 8kHz mulaw bytes → 16kHz float32 numpy array."""
    if audioop is not None:
        linear_16bit = audioop.ulaw2lin(mulaw_bytes, 2)
        arr = np.frombuffer(linear_16bit, dtype=np.int16).astype(np.float32) / 32768.0
    else:
        # Pure NumPy G.711 mu-law decoding (zero external dependencies)
        u = np.frombuffer(mulaw_bytes, dtype=np.uint8)
        u = ~u
        sign = (u & 0x80)
        exponent = (u & 0x70) >> 4
        mantissa = (u & 0x0F)
        sample = ((mantissa << 3) + 132) << exponent
        sample -= 132
        sample = np.where(sign != 0, -sample, sample)
        arr = (sample / 32768.0).astype(np.float32)

    # Upsample 8kHz → 16kHz (linear interpolation)
    if sample_rate == 8000:
        arr_up = np.interp(
            np.arange(0, len(arr), 0.5),
            np.arange(len(arr)),
            arr,
        ).astype(np.float32)
        return arr_up
    return arr


def linear_to_mulaw(audio: np.ndarray, in_sample_rate: int = 16000) -> bytes:
    """Convert float32 numpy audio → 8kHz mulaw bytes for Twilio."""
    # Downsample 16kHz → 8kHz
    if in_sample_rate == 16000:
        audio = audio[::2]
    # Clip and convert to 16-bit PCM
    audio_clipped = np.clip(audio, -1.0, 1.0)
    audio_16bit = (audio_clipped * 32767).astype(np.int16)

    if audioop is not None:
        return audioop.lin2ulaw(audio_16bit.tobytes(), 2)
    else:
        # Pure NumPy G.711 mu-law encoding (zero external dependencies)
        samples = audio_16bit.astype(np.int32)
        sign = (samples >> 8) & 0x80
        samples = np.where(samples < 0, -samples, samples)
        samples = np.clip(samples + 132, 0, 32767)

        exp = np.zeros_like(samples, dtype=np.uint8)
        for i in range(7, 0, -1):
            exp = np.where((samples >= (1 << (i + 7))) & (exp == 0), i, exp)

        mantissa = (samples >> (exp + 3)) & 0x0F
        mulaw = ~(sign | (exp << 4) | mantissa).astype(np.uint8)
        return mulaw.tobytes()


# ----------------------------------------------------------------------------
# TwiML generators
# ----------------------------------------------------------------------------
def inbound_twiml(stream_url: str) -> str:
    """Generate TwiML to connect an inbound call to our media stream."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{stream_url}" />
  </Connect>
</Response>"""


def outbound_twiml(stream_url: str, machine_detection: bool = True) -> str:
    """TwiML for outbound calls — connects to our media stream."""
    md = '<Parameter name="Enable" value="true" />' if machine_detection else ''
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{stream_url}">
      {md}
      <Parameter name="direction" value="outbound" />
    </Stream>
  </Connect>
</Response>"""


# ----------------------------------------------------------------------------
# Twilio REST API client
# ----------------------------------------------------------------------------
class TwilioConnector:
    """Twilio Voice + WhatsApp REST wrapper."""

    def __init__(self):
        settings = get_settings()
        self.settings = settings
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from twilio.rest import Client
            if not self.settings.twilio_account_sid:
                raise RuntimeError("Twilio credentials not configured")
            self._client = Client(
                self.settings.twilio_account_sid,
                self.settings.twilio_auth_token,
            )
        return self._client

    @property
    def stream_websocket_url(self) -> str:
        """wss:// URL Twilio should connect to for media streaming."""
        base = self.settings.public_base_url
        if base.startswith("http://"):
            base = "ws://" + base[len("http://"):]
        elif base.startswith("https://"):
            base = "wss://" + base[len("https://"):]
        return f"{base}/twilio/stream"

    # ------------------------------------------------------------------
    # INBOUND — TwiML response for incoming call webhook
    # ------------------------------------------------------------------
    def handle_inbound_webhook(self, form_data: dict) -> str:
        """Return TwiML for an inbound call."""
        return inbound_twiml(self.stream_websocket_url)

    # ------------------------------------------------------------------
    # OUTBOUND — Place a call
    # ------------------------------------------------------------------
    def place_call(
        self,
        to_number: str,
        business: str = "tuition",
        campaign_id: str | None = None,
        machine_detection: bool = True,
    ) -> str:
        """Place an outbound call. Returns the Twilio Call SID."""
        twiml = outbound_twiml(self.stream_websocket_url, machine_detection)
        call = self.client.calls.create(
            to=to_number,
            from_=self.settings.twilio_phone_number,
            twiml=twiml,
            status_callback=f"{self.settings.public_base_url}/twilio/status",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
        )
        logger.info("Outbound call placed: %s → %s (sid=%s)",
                    self.settings.twilio_phone_number, to_number, call.sid)
        return call.sid

    def hangup_call(self, call_sid: str):
        """Terminate an active call."""
        self.client.calls(call_sid).update(status="completed")
        logger.info("Call hung up: %s", call_sid)

    def send_whatsapp_text(self, to: str, body: str) -> str:
        """Send a WhatsApp text message. Returns message SID."""
        msg = self.client.messages.create(
            from_=self.settings.twilio_whatsapp_number,
            to=f"whatsapp:{to}" if not to.startswith("whatsapp:") else to,
            body=body,
        )
        return msg.sid

    def send_whatsapp_media(self, to: str, body: str, media_url: str) -> str:
        """Send a WhatsApp message with media. Returns message SID."""
        msg = self.client.messages.create(
            from_=self.settings.twilio_whatsapp_number,
            to=f"whatsapp:{to}" if not to.startswith("whatsapp:") else to,
            body=body,
            media_url=[media_url],
        )
        return msg.sid


@lru_cache(maxsize=1)
def get_twilio() -> TwilioConnector:
    return TwilioConnector()
