"""
voice_agent.llm.groq_llm — Groq LLM client with streaming + tool calling.

Groq Cloud runs Llama-3.3-70B on LPU hardware with Time-To-First-Token ~100ms,
which is the fastest free-tier option for sub-600ms conversational latency.

We expose:
- stream_chat()   : async generator yielding text deltas + tool calls
- chat()          : single-shot completion (returns final response)
- Streaming aggregation: handles Groq's tool-call delta format correctly
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import AsyncIterator

from ..config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """Parsed tool call from the LLM."""
    name: str
    arguments: dict
    id: str | None = None


@dataclass
class LLMResponse:
    """Aggregated response from a streaming chat."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict | None = None
    ttft_ms: float | None = None  # time to first token


class GroqLLM:
    """Groq LLM client with streaming + tool calling."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        settings = get_settings()
        self.api_key = api_key or settings.groq_api_key
        self.model = model or settings.groq_model
        self.temperature = temperature if temperature is not None else settings.groq_temperature
        self.max_tokens = max_tokens or settings.groq_max_tokens
        if not self.api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Get a free key at https://console.groq.com"
            )
        self._client = None

    @property
    def client(self):
        """Lazy-init AsyncGroq client."""
        if self._client is None:
            from groq import AsyncGroq
            self._client = AsyncGroq(api_key=self.api_key)
        return self._client

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict = "auto",
    ) -> AsyncIterator[tuple[str, ToolCall | None]]:
        """
        Stream chat completion. Yields tuples of (text_delta, tool_call_or_None).

        - text_delta is non-empty when the model is producing text
        - tool_call is non-None only on the FINAL yield for a tool call
          (we aggregate streaming tool arguments and yield once at the end)

        Caller should treat each text_delta as a chunk to be TTS'd immediately
        to maximize streaming benefit.
        """
        import time as _time
        t0 = _time.monotonic()
        ttft_recorded = False
        ttft_ms = None

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        try:
            stream = await self.client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.error("Groq API call failed: %s", e)
            raise

        # Track streaming tool call assembly
        # Groq streams arguments as deltas: we accumulate by index
        tool_calls_acc: dict[int, dict] = {}
        final_tool_calls: list[ToolCall] = []

        try:
            async for chunk in stream:
                if not ttft_recorded:
                    ttft_ms = (_time.monotonic() - t0) * 1000
                    ttft_recorded = True

                if not chunk.choices:
                    # Could be the final usage-only chunk
                    if hasattr(chunk, "usage") and chunk.usage:
                        logger.debug("Groq usage: %s", chunk.usage)
                    continue
                delta = chunk.choices[0].delta
                finish = chunk.choices[0].finish_reason

                # Text content
                if delta and delta.content:
                    yield (delta.content, None)

                # Tool call deltas — accumulate
                if delta and delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc.id,
                                "name": tc.function.name if tc.function else None,
                                "args_buf": "",
                            }
                        if tc.function and tc.function.arguments:
                            tool_calls_acc[idx]["args_buf"] += tc.function.arguments
                        if tc.id and not tool_calls_acc[idx]["id"]:
                            tool_calls_acc[idx]["id"] = tc.id

                if finish:
                    # Finalize tool calls
                    for idx in sorted(tool_calls_acc.keys()):
                        acc = tool_calls_acc[idx]
                        try:
                            args = json.loads(acc["args_buf"]) if acc["args_buf"] else {}
                        except json.JSONDecodeError:
                            logger.warning(
                                "Malformed tool args from LLM: %r", acc["args_buf"]
                            )
                            args = {}
                        tc = ToolCall(
                            name=acc["name"] or "",
                            arguments=args,
                            id=acc["id"],
                        )
                        final_tool_calls.append(tc)
                        yield ("", tc)
                    if finish != "tool_calls":
                        # We've truly finished
                        return
        except Exception as e:
            logger.error("Groq streaming error: %s", e)
            raise

        logger.debug("Groq TTFT: %.0fms", ttft_ms or 0)

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict = "auto",
    ) -> LLMResponse:
        """Non-streaming chat. Returns the final aggregated response."""
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        async for text_delta, tool_call in self.stream_chat(
            messages, tools=tools, tool_choice=tool_choice
        ):
            if text_delta:
                text_parts.append(text_delta)
            if tool_call:
                tool_calls.append(tool_call)
        return LLMResponse(text="".join(text_parts), tool_calls=tool_calls)


@lru_cache(maxsize=1)
def get_llm() -> GroqLLM:
    """Get the singleton GroqLLM instance."""
    return GroqLLM()
