"""
voice_agent.agent.conversation — Per-call conversation state.

Tracks:
- The running message list (for LLM context)
- Call metadata (call_sid, business, direction, phone)
- Tool-call results pending injection
- Latency telemetry per turn
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LatencyStats:
    """Tracks latency for the most recent turn."""
    stt_ms: float = 0.0
    llm_ttft_ms: float = 0.0       # time to first LLM token
    llm_total_ms: float = 0.0
    tts_first_byte_ms: float = 0.0
    tts_total_ms: float = 0.0
    total_turn_ms: float = 0.0     # caller-stop → first-audio

    def as_dict(self) -> dict:
        return {
            "stt_ms": round(self.stt_ms, 1),
            "llm_ttft_ms": round(self.llm_ttft_ms, 1),
            "llm_total_ms": round(self.llm_total_ms, 1),
            "tts_first_byte_ms": round(self.tts_first_byte_ms, 1),
            "tts_total_ms": round(self.tts_total_ms, 1),
            "total_turn_ms": round(self.total_turn_ms, 1),
        }


@dataclass
class ConversationState:
    """State for a single ongoing call."""

    call_sid: str
    direction: str = "inbound"                # inbound | outbound
    business: str = "tuition"                  # tuition | pg
    phone_number: str = ""
    campaign_id: str | None = None

    # LLM message history
    messages: list[dict] = field(default_factory=list)

    # Latency tracking
    last_latency: LatencyStats = field(default_factory=LatencyStats)
    avg_latency_ms: float = 0.0
    turn_count: int = 0

    # Barge-in state
    is_speaking: bool = False                  # AI is currently speaking
    interrupted: bool = False                  # caller barged in

    # Call lifecycle
    started_at: float = field(default_factory=time.time)
    ended_at: bool = False
    lead_score: int = 0
    lead_status: str = "cold"
    summary: str = ""

    def add_user_message(self, text: str):
        self.messages.append({"role": "user", "content": text})
        self.turn_count += 1

    def add_assistant_message(self, text: str):
        self.messages.append({"role": "assistant", "content": text})

    def add_tool_call(self, assistant_tool_call: dict):
        """Append the assistant's tool_call message (Groq format)."""
        self.messages.append(assistant_tool_call)

    def add_tool_result(self, tool_name: str, result: dict):
        """Append a tool result message (Groq format)."""
        self.messages.append({
            "role": "tool",
            "name": tool_name,
            "content": str(result),
        })

    def set_system_prompt(self, prompt: str):
        """Insert/replace the system message at index 0."""
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0] = {"role": "system", "content": prompt}
        else:
            self.messages.insert(0, {"role": "system", "content": prompt})

    def as_dict(self) -> dict:
        return {
            "call_sid": self.call_sid,
            "direction": self.direction,
            "business": self.business,
            "phone_number": self.phone_number,
            "campaign_id": self.campaign_id,
            "turn_count": self.turn_count,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "last_latency": self.last_latency.as_dict(),
            "lead_score": self.lead_score,
            "lead_status": self.lead_status,
            "summary": self.summary,
        }
