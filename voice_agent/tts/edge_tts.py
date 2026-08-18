"""
voice_agent.tts.edge_tts — Microsoft Edge TTS for native Tamil voices.

Why Edge-TTS:
- 100% free, no API key, no rate limits in practice
- Native Tamil voices: ta-IN-PallaviNeural (female), ta-IN-ValluvarNeural (male)
- Low latency (~150-300ms to first byte for short utterances)
- Supports SSML-like prosody adjustments (rate, volume, pitch)

Streaming strategy:
- We split text into sentences (Tamil danda '.' and English '.' both work)
- Each sentence is synthesized in parallel
- Audio chunks are yielded in order, so playback can start as soon as the
  first sentence is ready
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
from functools import lru_cache
from typing import AsyncIterator

import edge_tts

from ..config import get_settings

logger = logging.getLogger(__name__)


class TTSError(RuntimeError):
    pass


# Split on Tamil danda (।), full stop (.), question/exclamation, and newlines.
# Keep the delimiter so we can rebuild context if needed.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?।\n])\s+")
_MAX_SENTENCE_LEN = 200  # Edge-TTS struggles with very long utterances


def split_text_into_sentences(text: str) -> list[str]:
    """Split Tamil/English text into speakable chunks."""
    text = text.strip()
    if not text:
        return []
    parts = _SENTENCE_SPLIT_RE.split(text)
    # Merge very short fragments with the next one to avoid choppy TTS
    merged: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if merged and len(merged[-1]) < 30:
            merged[-1] = merged[-1] + " " + p
        else:
            merged.append(p)
    # Also split any sentence that's still too long
    final: list[str] = []
    for s in merged:
        if len(s) > _MAX_SENTENCE_LEN:
            # Greedy word-boundary split
            words = s.split()
            cur = ""
            for w in words:
                if len(cur) + len(w) + 1 > _MAX_SENTENCE_LEN:
                    final.append(cur.strip())
                    cur = w
                else:
                    cur = (cur + " " + w).strip()
            if cur:
                final.append(cur)
        else:
            final.append(s)
    return final


class EdgeTTS:
    """Edge-TTS streaming Tamil TTS."""

    def __init__(
        self,
        voice: str | None = None,
        rate: str | None = None,
        volume: str | None = None,
        pitch: str | None = None,
    ):
        settings = get_settings()
        self.voice = voice or settings.tts_voice
        self.rate = rate or settings.tts_rate
        self.volume = volume or settings.tts_volume
        self.pitch = pitch or settings.tts_pitch

    async def synthesize_to_bytes(self, text: str) -> bytes:
        """
        Synthesize a complete text string to a single MP3 bytes blob.

        Use this for short utterances or when you want the full audio before
        playing. For longer text, prefer stream_synthesize().
        """
        text = text.strip()
        if not text:
            return b""
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume,
            pitch=self.pitch,
        )
        buf = io.BytesIO()
        try:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
        except Exception as e:
            raise TTSError(f"Edge-TTS synthesis failed: {e}") from e
        return buf.getvalue()

    async def stream_synthesize(
        self, text: str, sentence_split: bool = True
    ) -> AsyncIterator[bytes]:
        """
        Stream audio chunks as soon as they're ready.

        Args:
            text: Text to synthesize.
            sentence_split: If True, split into sentences and synthesize
                each in parallel, yielding chunks in sentence order.

        Yields:
            MP3 audio bytes in playback order.
        """
        text = text.strip()
        if not text:
            return
        if not sentence_split:
            async for chunk in self._synthesize_streaming(text):
                yield chunk
            return

        sentences = split_text_into_sentences(text)
        if not sentences:
            return

        # Synthesize all sentences concurrently, queue results in order
        # This maximizes the parallelism Edge-TTS can give us.
        tasks = [asyncio.create_task(self.synthesize_to_bytes(s)) for s in sentences]
        for task in tasks:
            try:
                audio = await task
                if audio:
                    yield audio
            except TTSError as e:
                logger.error("TTS sentence failed: %s", e)
                tasks = [t for t in tasks if not t.done()]
                for t in tasks:
                    t.cancel()
                raise

    async def _synthesize_streaming(self, text: str) -> AsyncIterator[bytes]:
        """Single-utterance streaming — yields audio chunks as Edge sends them."""
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume,
            pitch=self.pitch,
        )
        try:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
        except Exception as e:
            raise TTSError(f"Edge-TTS streaming failed: {e}") from e

    async def list_available_voices(self, language: str = "ta") -> list[dict]:
        """List available voices for a language (mostly for debugging)."""
        voices = await edge_tts.list_voices()
        return [v for v in voices if v.get("Locale", "").startswith(language)]


@lru_cache(maxsize=1)
def get_tts() -> EdgeTTS:
    """Get the singleton EdgeTTS instance."""
    return EdgeTTS()
