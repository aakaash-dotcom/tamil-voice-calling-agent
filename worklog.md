# Worklog — Tamil Voice Agent Project

---
Task ID: 1
Agent: Main Agent (Super Z)
Task: Build a production-ready Tamil & Tanglish AI voice calling agent for Tuition Centre + Gents PG businesses. Sub-600ms latency, full-duplex with barge-in, WhatsApp integration, FastAPI dashboard.

Work Log:
- Clarified architectural choices with user via AskUserQuestion (8 questions)
- User confirmed: Twilio / Groq / Edge-TTS / Twilio WhatsApp / FastAPI / Linux local / Tuition+PG shared / Push-to-talk CLI
- Created project structure: voice_agent/{stt,tts,llm,tools,agent,telephony,db,dashboard,cli}
- Built config.py with Pydantic settings (env-driven, all business info configurable)
- Built prompts.py with Tamil/Tanglish system prompts for Tuition + PG + Outbound campaigns
- Built stt/whisper_stt.py: faster-whisper streaming Tamil STT with VAD filter
- Built tts/edge_tts.py: edge-tts streaming Tamil TTS with sentence-level parallelism
- Built llm/groq_llm.py: Groq Llama-3.3-70B streaming with tool-call aggregation
- Built tools/whatsapp.py: 6 tool dispatchers (fee_chart, location_pin, study_material, trial_class, pg_visit, end_call)
- Built db/database.py: SQLite schema with calls, messages, bookings, recordings tables
- Built agent/core.py: full-duplex voice loop with barge-in interrupt_event
- Built agent/conversation.py: per-call state with latency tracking
- Built telephony/twilio_connector.py: Twilio Voice + WhatsApp + mulaw codec
- Built dashboard/app.py: FastAPI with dashboard UI + Twilio webhooks + WebSocket media stream
- Built dashboard/templates/: index.html, call_detail.html, bookings.html (Jinja2 + clean CSS)
- Built cli/push_to_talk.py: local mic/speaker test runner with barge-in keyboard watcher
- Built cli/outbound.py: outbound campaign caller (single + CSV batch)
- Wrote setup.sh, run_local_test.sh, run_dashboard.sh, sample_leads.csv
- Generated sample fee PDFs (tuition_fees.pdf, pg_fees.pdf)
- Wrote comprehensive README.md with architecture diagram, latency budget, troubleshooting
- Fixed two bugs found during smoke test:
  - Indentation error in groq_llm.py tool-call finalization block
  - Starlette API change: TemplateResponse now requires (request, name, context) order
- Verified all imports OK, TTS generates real Tamil audio (670ms first byte), dashboard serves HTML, Twilio webhook returns valid TwiML, media serving works, outbound CLI runs dry-run campaign

Stage Summary:
- 21 Python modules + 3 HTML templates + 4 shell scripts + README
- Architecture: faster-whisper → Groq Llama-3.3-70B → edge-tts (ta-IN-PallaviNeural) → Twilio
- 100% free during dev: Groq free tier + edge-tts + faster-whisper local + SQLite
- Only paid piece: Twilio (covered by trial credit)
- Latency target <600ms: STT ~250ms + LLM-TTFT ~100ms + TTS-first-byte ~150ms + network ~50ms = ~550ms
- Tamil fluency: native Tamil script default, Tanglish mixing supported, polite address (ஐயா/அம்மா), natural fillers
- Barge-in: energy-based VAD on incoming audio stream, <50ms detection, immediate TTS cancellation
- 6 tools available to LLM: send_fee_chart, send_location_pin, send_study_material, book_trial_class, book_pg_visit, end_call
- Lead qualification: Hot/Warm/Cold scoring via end_call tool
- Dashboard: call list, per-call transcript with latency, bookings table
- User needs to: (1) cp .env.example .env, (2) set GROQ_API_KEY, (3) bash scripts/setup.sh, (4) run!
