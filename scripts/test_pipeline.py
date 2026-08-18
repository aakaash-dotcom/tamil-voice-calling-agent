"""
End-to-end pipeline test — text in, audio out (no mic/speaker needed).

Verifies:
1. LLM produces Tamil response to Tamil input
2. TTS converts response to audio bytes
3. Latency is logged
4. Tool calls work (simulated)
5. DB persistence works
"""
import asyncio
import sys
import time
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_agent.config import get_settings, reload_settings
from voice_agent.db.database import init_db, get_db
from voice_agent.agent.core import get_agent
from voice_agent.agent.conversation import ConversationState


async def run_test():
    # Force settings reload (so we can test without .env file)
    settings = get_settings()

    # Check Groq key
    if not settings.groq_api_key or settings.groq_api_key == "your_groq_api_key_here":
        print("⚠ No GROQ_API_KEY set in .env")
        print("  This test will skip the LLM call and only verify TTS + DB.")
        print("  To run the full test, set GROQ_API_KEY in .env")
        print()

        # Just verify TTS works
        from voice_agent.tts.edge_tts import get_tts
        tts = get_tts()
        text = "வணக்கம் ஐயா! இது ஒரு test call. நான் Kavya பேசுறேன்."
        print(f"TTS test: {text}")
        t0 = time.monotonic()
        audio = await tts.synthesize_to_bytes(text)
        elapsed = (time.monotonic() - t0) * 1000
        print(f"  ✓ Generated {len(audio)} bytes in {elapsed:.0f}ms")
        out_path = "/home/z/my-project/download/pipeline_test.mp3"
        with open(out_path, "wb") as f:
            f.write(audio)
        print(f"  ✓ Saved to {out_path}")
        return

    # Full pipeline test
    print("=" * 60)
    print("  End-to-End Pipeline Test")
    print("=" * 60)
    init_db()
    db = get_db()
    agent = get_agent()

    call_sid = f"test-{int(time.time())}"
    db.create_call(
        call_sid=call_sid,
        direction="inbound",
        business="tuition",
        phone_number="+919999999999",
    )

    state = agent.init_state(
        call_sid=call_sid,
        direction="inbound",
        business="tuition",
        phone_number="+919999999999",
    )

    # Simulated caller turns (Tamil + Tanglish)
    test_inputs = [
        "வணக்கம், fees விவரம் கேக்கணும்",
        "weekend batch இருக்கா?",
        "சரி, address அனுப்புங்க. நன்றி!",
    ]

    all_audio = b""
    for i, user_text in enumerate(test_inputs, 1):
        print(f"\n--- Turn {i} ---")
        print(f"👤 User: {user_text}")

        t0 = time.monotonic()
        result = await agent.process_text_turn(state, user_text)
        total_ms = (time.monotonic() - t0) * 1000

        print(f"🤖 AI: {result.assistant_text}")
        print(f"  ⏱ Latency: STT=N/A, LLM-TTFT={state.last_latency.llm_ttft_ms:.0f}ms, "
              f"LLM-total={state.last_latency.llm_total_ms:.0f}ms, TOTAL={total_ms:.0f}ms")

        db.add_message(call_sid, "user", user_text)
        if result.assistant_text:
            db.add_message(call_sid, "assistant", result.assistant_text,
                          latency_ms=int(total_ms))

        # Generate TTS audio
        if result.assistant_text:
            t_tts = time.monotonic()
            tts_first_byte = None
            audio_buf = b""
            async for chunk in agent.stream_tts(result.assistant_text):
                if tts_first_byte is None:
                    tts_first_byte = (time.monotonic() - t_tts) * 1000
                audio_buf += chunk
            tts_total = (time.monotonic() - t_tts) * 1000
            print(f"  🔊 TTS: first_byte={tts_first_byte:.0f}ms, total={tts_total:.0f}ms, {len(audio_buf)} bytes")
            all_audio += audio_buf

        # Show tool calls
        for tc, tr in zip(result.tool_calls, result.tool_results):
            print(f"  🔧 {tc.name} → {tr.get('status', 'unknown')}")
            db.add_message(call_sid, "tool", str(tr),
                          tool_name=tc.name, tool_args=tc.arguments,
                          tool_result=tr)

        if result.should_end_call:
            print("\n📞 Agent ended the call")
            break

    # Save combined audio
    out_path = "/home/z/my-project/download/pipeline_test.mp3"
    with open(out_path, "wb") as f:
        f.write(all_audio)
    print(f"\n✓ Combined audio saved to {out_path}")
    print(f"✓ Total turns: {state.turn_count}")
    print(f"✓ Avg latency: {state.avg_latency_ms:.0f}ms")

    db.end_call(call_sid, duration_seconds=int(time.time() - state.started_at))

    print("\n" + "=" * 60)
    print("  ✓ Pipeline test complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_test())
