"""
voice_agent.telephony.twilio_connector — Twilio Voice + WhatsApp integration.

Two call flows:

INBOUND (caller dials Twilio number):
    1. Twilio webhook → our /voice/inbound endpoint
    2. We respond with a TwiML <Connect><Stream> pointing to our WebSocket
    3. Twilio opens a bidirectional WebSocket to /twilio/stream
    4. We receive caller audio (mulaw 8kHz) → STT → LLM → TTS → send back
    5. Barge-in: when we detect caller audio while we're speaking, we stop
       sending audio chunks and switch back to listening mode.

OUTBOUND (we dial a lead):
    1. We POST to Twilio Calls API with TwiML that connects to our WebSocket
    2. Same WebSocket streaming flow as inbound

Audio format conversion:
    - Twilio stream: 8kHz mulaw (G.711 µ-law), 20ms chunks (160 samples)
    - Whisper wants: 16kHz float32 mono
    - We use a simple resampler + mulaw decode/encode (audioop)

For <600ms latency in production we'd want to use the Twilio Media Streams
extension with the newer <Connect><Stream> TwiML and bidirectional audio.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import audioop
from functools import lru_cache
from typing import AsyncIterator

import numpy as np

from ..config import get_settings

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# MULAW <-> LINEAR conversion (G.711 µ-law, the standard for PSTN)
# ----------------------------------------------------------------------------
def mulaw_to_linear(mulaw_bytes: bytes, sample_rate: int = 8000) -> np.ndarray:
    """Convert 8kHz mulaw bytes → 16kHz float32 numpy array."""
    # audioop.ulaw2lin expects ulaw input and returns 16-bit signed linear PCM
    linear_16bit = audioop.ulaw2lin(mulaw_bytes, 2)
    arr = np.frombuffer(linear_16bit, dtype=np.int16).astype(np.float32) / 32768.0
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
    # PCM 16-bit → mulaw
    return audioop.lin2ulaw(audio_16bit.tobytes(), 2)


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
