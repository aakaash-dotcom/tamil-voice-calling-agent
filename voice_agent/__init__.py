"""
voice_agent — Tamil & Tanglish AI Voice Calling Agent.

A production-ready, ultra-low-latency conversational voice agent for
Tamil (தமிழ்), Tanglish, and Indian English. Handles inbound receptionist
and outbound campaign calls for a Tuition Centre and Gents PG business.

Architecture:
    STT: faster-whisper (local, free, Tamil)
    LLM: Groq Llama-3.3-70B (free tier, ~100ms TTFT)
    TTS: edge-tts ta-IN-PallaviNeural (free, native Tamil)
    Telephony + WhatsApp: Twilio
    Dashboard: FastAPI + Jinja2
    DB: SQLite

Quick start:
    # 1. Install deps
    pip install -r requirements.txt

    # 2. Configure
    cp .env.example .env
    # Edit .env with your Groq API key + Twilio creds

    # 3. Test locally (push-to-talk)
    python -m voice_agent.cli.push_to_talk --business tuition

    # 4. Run dashboard + telephony server
    uvicorn voice_agent.dashboard.app:app --host 0.0.0.0 --port 8000

    # 5. Make outbound call
    python -m voice_agent.cli.outbound --to +919876543210 --business tuition
"""

__version__ = "1.0.0"
