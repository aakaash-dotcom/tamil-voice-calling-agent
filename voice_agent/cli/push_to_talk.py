"""
voice_agent.cli.push_to_talk — Local mic/speaker test runner.

USAGE:
    python -m voice_agent.cli.push_to_talk [--business tuition|pg]

HOW IT WORKS:
    1. Hold SPACEBAR to record from mic
    2. Release SPACEBAR to stop recording & send to STT
    3. STT transcribes → LLM streams → TTS plays through speakers
    4. Press SPACEBAR again during AI reply to interrupt (barge-in)
    5. Press Ctrl+C to exit

This is the fastest way to verify the full Tamil voice loop without
needing a real phone line.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
import wave
from pathlib import Path

import numpy as np

from ..config import get_settings
from ..db.database import init_db, get_db
from ..agent.core import get_agent
from ..agent.conversation import ConversationState

logger = logging.getLogger("push_to_talk")

# Audio config — Whisper wants 16kHz mono
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_DURATION_MS = 100  # 100ms chunks
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)


def record_until_release(record_seconds_max: float = 30.0) -> np.ndarray:
    """Block-record from mic until user releases SPACEBAR (or max time)."""
    import sounddevice as sd

    chunks = []
    print("🔴 Recording... (release SPACE to stop)", end="", flush=True)

    try:
        # Check keyboard in a non-blocking way
        import keyboard
        is_held = keyboard.is_pressed("space")
    except ImportError:
        # Fallback: just record for fixed duration
        print(" (keyboard module not found — recording for fixed duration)")
        is_held = False
        record_seconds_max = min(record_seconds_max, 5.0)

    t_start = time.monotonic()
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=CHUNK_SAMPLES,
    ) as stream:
        while True:
            chunk, _ = stream.read(CHUNK_SAMPLES)
            chunks.append(chunk.flatten())
            elapsed = time.monotonic() - t_start
            if elapsed >= record_seconds_max:
                break
            try:
                import keyboard
                if not keyboard.is_pressed("space") and is_held:
                    break
            except ImportError:
                break

    audio = np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)
    print(f" done ({len(audio)/SAMPLE_RATE:.1f}s)")
    return audio


def play_audio_bytes(mp3_bytes: bytes):
    """Play MP3 bytes through the speakers."""
    if not mp3_bytes:
        return
    try:
        from io import BytesIO
        from pydub import AudioSegment
        import sounddevice as sd
    except ImportError:
        # Fallback: write to file and let user play it
        out_path = Path("/tmp/voice_agent_reply.mp3")
        out_path.write_bytes(mp3_bytes)
        print(f"  (Wrote audio to {out_path} — install pydub for auto-playback)")
        return

    audio = AudioSegment.from_mp3(BytesIO(mp3_bytes))
    samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
    if audio.channels > 1:
        samples = samples.reshape(-1, audio.channels).mean(axis=1)
    samples = samples / (2**15)
    sd.play(samples, audio.frame_rate)
    sd.wait()


async def run_push_to_talk(business: str = "tuition"):
    """Main push-to-talk loop."""
    settings = get_settings()
    init_db()
    agent = get_agent()
    db = get_db()

    # Create a fake "call" in DB for tracking
    fake_call_sid = f"local-{int(time.time())}"
    db.create_call(
        call_sid=fake_call_sid,
        direction="inbound",
        business=business,
        phone_number="+919999999999",
    )

    state = agent.init_state(
        call_sid=fake_call_sid,
        direction="inbound",
        business=business,
        phone_number="+919999999999",
    )

    # Trigger the opening greeting
    print("\n" + "="*60)
    print(f"  📞 Voice Agent Test Runner — {business.upper()}")
    print(f"     Voice: {settings.tts_voice}")
    print(f"     LLM:   {settings.groq_model}")
    print(f"     STT:   faster-whisper {settings.whisper_model_size}")
    print("="*60)
    print("  • Hold SPACE to talk, release to send")
    print("  • Press SPACE during reply to BARGE-IN")
    print("  • Ctrl+C to quit\n")

    # First, get the AI greeting
    print("🤖 AI: ", end="", flush=True)
    greeting_result = await agent.process_text_turn(state, "[call connected — greet the caller]")
    if greeting_result.assistant_text:
        print(greeting_result.assistant_text)
        # Speak the greeting
        async for audio_chunk in agent.stream_tts(greeting_result.assistant_text):
            play_audio_bytes(audio_chunk)
    db.add_message(fake_call_sid, "assistant", greeting_result.assistant_text or "")

    # Main loop
    while True:
        try:
            # Wait for user to press & release SPACE
            input("\n📡 Press ENTER when ready to speak (or hold SPACE + ENTER)...")
            audio = record_until_release()

            if len(audio) < SAMPLE_RATE * 0.1:
                print("  (too short, try again)")
                continue

            # Create barge-in interrupt event
            interrupt_event = asyncio.Event()

            # Spawn a keyboard watcher for barge-in
            barge_watcher = None
            try:
                import keyboard
                def _watch():
                    while True:
                        if keyboard.is_pressed("space"):
                            interrupt_event.set()
                            return
                        time.sleep(0.02)
                # We can't easily run this in async, so skip for now
            except ImportError:
                pass

            # Process turn — STT + LLM
            t0 = time.monotonic()
            result = await agent.process_turn(state, audio, SAMPLE_RATE)
            print(f"\n👤 You: {result.user_text}")
            print(f"🤖 AI: {result.assistant_text}")
            print(f"  ⏱ Latency: STT={state.last_latency.stt_ms:.0f}ms "
                  f"LLM-TTFT={state.last_latency.llm_ttft_ms:.0f}ms "
                  f"LLM-total={state.last_latency.llm_total_ms:.0f}ms "
                  f"TOTAL={state.last_latency.total_turn_ms:.0f}ms")

            db.add_message(fake_call_sid, "user", result.user_text,
                           latency_ms=int(state.last_latency.stt_ms))
            if result.assistant_text:
                db.add_message(fake_call_sid, "assistant", result.assistant_text,
                               latency_ms=int(state.last_latency.total_turn_ms))

            # Tool calls
            for tc, tr in zip(result.tool_calls, result.tool_results):
                db.add_message(fake_call_sid, "tool", str(tr),
                               tool_name=tc.name, tool_args=tc.arguments,
                               tool_result=tr)
                print(f"  🔧 {tc.name} → {tr.get('status', 'unknown')}")

            # Speak the reply (streaming)
            if result.assistant_text:
                async for audio_chunk in agent.stream_tts(
                    result.assistant_text, interrupt_event=interrupt_event
                ):
                    if interrupt_event.is_set():
                        print("\n  ⚡ BARGE-IN detected — stopping TTS")
                        break
                    play_audio_bytes(audio_chunk)

            if result.should_end_call:
                print("\n📞 Call ended by agent")
                db.end_call(fake_call_sid, duration_seconds=int(time.time() - state.started_at))
                break

        except KeyboardInterrupt:
            print("\n\n👋 Exiting...")
            db.end_call(fake_call_sid, duration_seconds=int(time.time() - state.started_at))
            break
        except Exception as e:
            logger.exception("Turn failed")
            print(f"\n❌ Error: {e}")
            print("  (continuing...)")


def main():
    parser = argparse.ArgumentParser(
        description="Tamil Voice Agent — Push-to-Talk Test Runner"
    )
    parser.add_argument(
        "--business", choices=["tuition", "pg"], default="tuition",
        help="Which business context to test (default: tuition)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    try:
        asyncio.run(run_push_to_talk(args.business))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
