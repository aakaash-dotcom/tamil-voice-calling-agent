"""
voice_agent.stt.whisper_stt — Streaming Tamil STT via faster-whisper.

faster-whisper is a CTranslate2-backed implementation of Whisper that is 4-10x
faster than openai-whisper with no accuracy loss. The `small` model handles
Tamil well at ~2-3x realtime on CPU.

We expose two interfaces:
1. transcribe_buffer()  — one-shot transcription of a full audio chunk
2. StreamingIterator   — for chunked streaming (used by live calls)

Tamil language code: 'ta' forces Whisper to decode as Tamil rather than
auto-detecting, which dramatically reduces false starts on Tanglish.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import AsyncIterator

import numpy as np

from ..config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    text: str
    language: str
    segments: list[dict]
    processing_time_ms: float
    is_final: bool = True


class WhisperSTT:
    """Faster-Whisper STT wrapper. Singleton — model loads once."""

    def __init__(
        self,
        model_size: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
        language: str | None = "ta",
        vad_filter: bool | None = None,
    ):
        settings = get_settings()
        self.model_size = model_size or settings.whisper_model_size
        self.device = device or settings.whisper_device
        self.compute_type = compute_type or settings.whisper_compute_type
        self.language = language if language is not None else settings.whisper_language
        self.vad_filter = (
            vad_filter if vad_filter is not None else settings.whisper_vad_filter
        )
        self._model = None

    def load(self):
        """Lazy-load the model. First call takes ~5-15s; subsequent calls instant."""
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel

        logger.info(
            "Loading faster-whisper model: size=%s device=%s compute=%s lang=%s vad=%s",
            self.model_size,
            self.device,
            self.compute_type,
            self.language,
            self.vad_filter,
        )
        t0 = time.monotonic()
        self._model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )
        logger.info(
            "Whisper model loaded in %.2fs", time.monotonic() - t0
        )
        return self._model

    def transcribe_buffer(
        self, audio: np.ndarray, sample_rate: int = 16000
    ) -> TranscriptionResult:
        """
        Transcribe a complete audio buffer.

        Args:
            audio: float32 numpy array, mono, values in [-1, 1].
            sample_rate: must be 16000 (Whisper requirement).

        Returns:
            TranscriptionResult with text, language, segments, timing.
        """
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)  # downmix to mono
        if sample_rate != 16000:
            # Resample using librosa if available, else fail loudly
            try:
                import librosa
                audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000)
            except ImportError as e:
                raise RuntimeError(
                    "Audio must be 16kHz mono. Install librosa or resample upstream."
                ) from e
            sample_rate = 16000

        model = self.load()
        t0 = time.monotonic()
        segments_iter, info = model.transcribe(
            audio,
            language=self.language,
            vad_filter=self.vad_filter,
            beam_size=1,                    # greedy — fastest for streaming
            best_of=1,
            temperature=0.0,                # deterministic
            without_timestamps=True,
            condition_on_previous_text=False,  # avoid hallucination loops
        )
        segments = []
        text_parts = []
        for seg in segments_iter:
            segments.append(
                {
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip(),
                }
            )
            text_parts.append(seg.text.strip())
        elapsed_ms = (time.monotonic() - t0) * 1000
        return TranscriptionResult(
            text=" ".join(text_parts).strip(),
            language=info.language if info else (self.language or "ta"),
            segments=segments,
            processing_time_ms=elapsed_ms,
            is_final=True,
        )

    async def transcribe_buffer_async(
        self, audio: np.ndarray, sample_rate: int = 16000
    ) -> TranscriptionResult:
        """Async wrapper — runs blocking transcribe in executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.transcribe_buffer, audio, sample_rate
        )

    async def stream_transcribe(
        self, audio_chunks: AsyncIterator[np.ndarray], sample_rate: int = 16000
    ) -> AsyncIterator[TranscriptionResult]:
        """
        Consume a stream of audio chunks and yield incremental transcriptions.

        Strategy: accumulate chunks until we have ~1s of audio (16k samples),
        then run transcription on the accumulated buffer and yield the result.
        On the next call, slide the window forward.

        This is NOT a true streaming ASR — it's a pragmatic chunked approach
        that works well for conversational turn-taking.
        """
        chunk_window_samples = sample_rate  # 1s window
        buffer = np.array([], dtype=np.float32)
        async for chunk in audio_chunks:
            if chunk.dtype != np.float32:
                chunk = chunk.astype(np.float32)
            buffer = np.concatenate([buffer, chunk])
            if len(buffer) >= chunk_window_samples:
                # Take last 2s of audio max to avoid runaway buffer
                if len(buffer) > sample_rate * 2:
                    buffer = buffer[-sample_rate * 2 :]
                result = await self.transcribe_buffer_async(buffer, sample_rate)
                if result.text:
                    yield result
                # Keep last 0.2s as context for next window
                buffer = buffer[-int(sample_rate * 0.2) :]


@lru_cache(maxsize=1)
def get_stt() -> WhisperSTT:
    """Get the singleton WhisperSTT instance."""
    return WhisperSTT()
