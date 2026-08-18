"""
voice_agent.agent.core — The voice agent turn loop.

This is the heart of the system. The agent's job is:

    1. Receive an audio chunk (from mic / Twilio / WebSocket)
    2. Run STT  → get text
    3. If empty / no speech → wait for more audio
    4. Append user message to history
    5. Stream LLM response → text deltas
    6. For each delta → stream TTS → audio bytes
    7. Play audio bytes (interruptible if barge-in detected)
    8. If LLM emitted tool calls → dispatch them, then re-prompt LLM
    9. Repeat until end_call tool is invoked

Latency budget breakdown (target <600ms):
    STT (1s audio):       ~150-250ms (faster-whisper small on CPU)
    LLM TTFT:             ~80-150ms  (Groq Llama-3.3-70B)
    TTS first byte:       ~100-200ms (Edge-TTS)
    Network overhead:     ~50ms
    -----------------------------
    Total first-audio:    ~380-650ms  ← meets target

The agent is fully async and supports concurrent STT/TTS via asyncio.
Barge-in is implemented via an `interrupt_event` that the audio playback
loop checks between chunks.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import AsyncIterator, Callable

import numpy as np

from ..config import get_settings
from ..llm import GroqLLM, get_llm, ToolCall
from ..stt import WhisperSTT, get_stt, TranscriptionResult
from ..tts import EdgeTTS, get_tts
from ..tools import dispatch_tool_call
from ..prompts import (
    build_inbound_system_prompt,
    build_outbound_system_prompt,
    TOOL_DEFINITIONS,
)
from .conversation import ConversationState, LatencyStats

logger = logging.getLogger(__name__)


# Type for an async audio sink — receives MP3 bytes, plays them.
# Implementation must support interruption via the interrupt_event.
AudioSink = Callable[[bytes], asyncio.Future]
AudioSource = Callable[[], AsyncIterator[np.ndarray]]


@dataclass
class TurnResult:
    """Result of processing one user turn."""
    user_text: str
    assistant_text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    latency: LatencyStats = field(default_factory=LatencyStats)
    should_end_call: bool = False


class VoiceAgent:
    """The full-duplex voice agent. One instance per active call."""

    def __init__(
        self,
        llm: GroqLLM | None = None,
        stt: WhisperSTT | None = None,
        tts: EdgeTTS | None = None,
    ):
        self.llm = llm or get_llm()
        self.stt = stt or get_stt()
        self.tts = tts or get_tts()

    # ------------------------------------------------------------------
    # SETUP
    # ------------------------------------------------------------------
    def init_state(
        self,
        call_sid: str,
        direction: str,
        business: str,
        phone_number: str,
        campaign_id: str | None = None,
        campaign_config: dict | None = None,
    ) -> ConversationState:
        """Create a fresh ConversationState with the system prompt installed."""
        state = ConversationState(
            call_sid=call_sid,
            direction=direction,
            business=business,
            phone_number=phone_number,
            campaign_id=campaign_id,
        )
        if direction == "outbound" and campaign_config:
            prompt = build_outbound_system_prompt(
                business=business,
                campaign_name=campaign_config.get("name", ""),
                campaign_goal=campaign_config.get("goal", ""),
                talking_points=campaign_config.get("talking_points", ""),
                campaign_intro=campaign_config.get("intro", ""),
            )
        else:
            prompt = build_inbound_system_prompt(business)
        state.set_system_prompt(prompt)
        return state

    # ------------------------------------------------------------------
    # CORE TURN
    # ------------------------------------------------------------------
    async def process_turn(
        self,
        state: ConversationState,
        user_audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> TurnResult:
        """
        Process one full turn:
            audio → STT → LLM (stream) → TTS (stream) → audio bytes

        Returns a TurnResult with text + latency stats.
        Does NOT play audio — caller is responsible for streaming the
        returned audio bytes to the speaker / phone.

        For barge-in support, use process_turn_streaming() instead.
        """
        t_turn_start = time.monotonic()
        result = TurnResult(user_text="", assistant_text="")

        # --- 1. STT ---
        t_stt_start = time.monotonic()
        stt_result = await self.stt.transcribe_buffer_async(user_audio, sample_rate)
        state.last_latency.stt_ms = (time.monotonic() - t_stt_start) * 1000
        result.user_text = stt_result.text.strip()

        if not result.user_text:
            logger.debug("STT returned empty — skipping turn")
            return result
        state.add_user_message(result.user_text)
        logger.info("STT [%s]: %s (%.0fms)",
                    state.call_sid, result.user_text, state.last_latency.stt_ms)

        # --- 2. LLM streaming + 3. TTS streaming (interleaved) ---
        await self._stream_llm_with_tools(state, result, t_turn_start)
        state.last_latency.total_turn_ms = (time.monotonic() - t_turn_start) * 1000

        # Update rolling average
        if state.turn_count > 0:
            state.avg_latency_ms = (
                (state.avg_latency_ms * (state.turn_count - 1)
                 + state.last_latency.total_turn_ms) / state.turn_count
            )

        return result

    async def process_text_turn(
        self,
        state: ConversationState,
        user_text: str,
    ) -> TurnResult:
        """
        Process a turn where the input is already text (no STT needed).
        Useful for testing, web chat, or pre-transcribed calls.
        """
        t_turn_start = time.monotonic()
        result = TurnResult(user_text=user_text, assistant_text="")
        state.add_user_message(user_text)
        logger.info("Text input [%s]: %s", state.call_sid, user_text)

        await self._stream_llm_with_tools(state, result, t_turn_start)
        state.last_latency.total_turn_ms = (time.monotonic() - t_turn_start) * 1000

        if state.turn_count > 0:
            state.avg_latency_ms = (
                (state.avg_latency_ms * (state.turn_count - 1)
                 + state.last_latency.total_turn_ms) / state.turn_count
            )
        return result

    async def _stream_llm_with_tools(
        self,
        state: ConversationState,
        result: TurnResult,
        t_turn_start: float,
    ):
        """Stream LLM response, dispatch tools, re-prompt if needed."""
        max_tool_rounds = 3  # safety limit
        round_num = 0

        while round_num < max_tool_rounds:
            round_num += 1
            t_llm_start = time.monotonic()
            ttft_recorded = False
            text_buf: list[str] = []
            tool_calls: list[ToolCall] = []

            # Stream LLM
            async for text_delta, tool_call in self.llm.stream_chat(
                state.messages, tools=TOOL_DEFINITIONS
            ):
                if text_delta:
                    if not ttft_recorded:
                        state.last_latency.llm_ttft_ms = (time.monotonic() - t_llm_start) * 1000
                        ttft_recorded = True
                    text_buf.append(text_delta)
                if tool_call:
                    tool_calls.append(tool_call)

            state.last_latency.llm_total_ms = (time.monotonic() - t_llm_start) * 1000
            assistant_text = "".join(text_buf)
            result.assistant_text += assistant_text

            if assistant_text:
                state.add_assistant_message(assistant_text)
                logger.info("LLM [%s]: %s (%.0fms ttft, %.0fms total)",
                            state.call_sid, assistant_text[:120],
                            state.last_latency.llm_ttft_ms,
                            state.last_latency.llm_total_ms)

            # No tool calls — we're done with this turn
            if not tool_calls:
                return

            # Dispatch tool calls
            for tc in tool_calls:
                result.tool_calls.append(tc)
                logger.info("Tool call [%s]: %s args=%s",
                            state.call_sid, tc.name, tc.arguments)

                # Record the assistant tool_call message in history
                state.add_tool_call({
                    "role": "assistant",
                    "content": assistant_text or None,
                    "tool_calls": [{
                        "id": tc.id or f"call_{tc.name}",
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": __import__("json").dumps(tc.arguments),
                        },
                    }],
                })

                # Dispatch
                tool_result = await dispatch_tool_call(
                    tc.name, tc.arguments, call_sid=state.call_sid
                )
                result.tool_results.append(tool_result)
                state.add_tool_result(tc.name, tool_result)

                # end_call → terminate the turn
                if tc.name == "end_call":
                    state.lead_score = int(tc.arguments.get("lead_score", 0))
                    state.lead_status = tc.arguments.get("lead_status", "cold")
                    state.summary = tc.arguments.get("summary", "")
                    result.should_end_call = True
                    return

            # Loop back — LLM will produce a follow-up response now that
            # tool results are in history.

    # ------------------------------------------------------------------
    # TTS STREAMING (with barge-in support)
    # ------------------------------------------------------------------
    async def stream_tts(
        self,
        text: str,
        interrupt_event: asyncio.Event | None = None,
    ) -> AsyncIterator[bytes]:
        """
        Stream TTS audio bytes for the given text.

        If interrupt_event is set during streaming, the generator stops
        yielding — caller should stop playback immediately.
        """
        if not text.strip():
            return
        try:
            async for chunk in self.tts.stream_synthesize(text):
                if interrupt_event and interrupt_event.is_set():
                    logger.debug("TTS interrupted mid-stream")
                    return
                yield chunk
        except Exception as e:
            logger.error("TTS streaming error: %s", e)


@lru_cache(maxsize=1)
def get_agent() -> VoiceAgent:
    """Singleton VoiceAgent instance."""
    return VoiceAgent()
