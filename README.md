# 📞 Tamil & Tanglish AI Voice Calling Agent

A production-grade, ultra-low-latency (<600ms target) conversational voice agent that speaks, understands, and interacts fluently in **native Tamil (தமிழ்)**, **Tanglish**, and **Indian English**.

Built for a **Tuition Centre** and **Gents PG** business to handle:
- **Inbound 24/7 Receptionist** — answers inquiries about schedules, fees, location, PG availability
- **Outbound Mass Campaigns** — dials leads for exam announcements, fee reminders, new batches
- **Automated WhatsApp Dispatch** — sends fee PDFs, location pins, study material post-call

---

## 🎯 Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    CALLER (PSTN / Mic)                       │
└──────────┬───────────────────────────────────────┬───────────┘
           │ (inbound)                             │ (barge-in)
           ▼                                       │
┌─────────────────────┐    ┌──────────────────┐    │
│  Twilio Media Stream│◄──►│  FastAPI WebSocket│◄───┘
│  (8kHz mulaw)       │    │  /twilio/stream  │
└─────────────────────┘    └────────┬─────────┘
                                    │
                                    ▼
                       ┌────────────────────────┐
                       │   Voice Agent Core     │
                       │   (asyncio pipeline)   │
                       └─┬───────┬───────┬──────┘
                         │       │       │
              ┌──────────▼┐  ┌───▼────┐  ┌──▼─────────┐
              │  STT      │  │  LLM   │  │   TTS      │
              │  faster-  │  │  Groq  │  │  edge-tts  │
              │  whisper  │  │  Llama │  │  ta-IN     │
              │  (Tamil)  │  │  3.3-70│  │  Pallavi   │
              └───────────┘  └───┬────┘  └────────────┘
                                 │
                          ┌──────▼──────┐
                          │ Tool Calls  │
                          │ WhatsApp    │
                          │ Bookings    │
                          │ Lead Score  │
                          └─────────────┘
                                 │
                          ┌──────▼──────┐
                          │   SQLite    │
                          │  (calls,    │
                          │  leads,     │
                          │  bookings)  │
                          └─────────────┘
```

### Component Choice Rationale

| Component   | Choice                  | Why                                            | Cost |
|-------------|-------------------------|------------------------------------------------|------|
| STT         | faster-whisper `small`  | Local, CTranslate2, Tamil support, ~250ms       | Free |
| LLM         | Groq Llama-3.3-70B      | Fastest TTFT (~100ms), free tier, strong Tamil | Free |
| TTS         | edge-tts ta-IN-Pallavi  | Free, native Tamil, low latency (~150ms)        | Free |
| Telephony   | Twilio Voice + WhatsApp | Mature SDK, SIP + WhatsApp, India DIDs          | ~₹0.50/min |
| Dashboard   | FastAPI + Jinja2        | Lightweight, no JS framework, fast              | Free |
| Database    | SQLite                  | Zero-config, fast enough, file-based            | Free |

**Total cost during development: ₹0** (Twilio trial credit covers dev calls)

---

## 🚀 Quick Start

### 1. Install

```bash
cd /home/z/my-project
bash scripts/setup.sh
```

This will:
- Install system deps (PortAudio, ffmpeg)
- Create Python venv
- Install all Python packages
- Create `.env` from `.env.example`
- Generate sample fee PDFs

### 2. Configure

Edit `.env` and set at minimum:

```bash
GROQ_API_KEY=your_key_here          # Get free at https://console.groq.com
TTS_VOICE=ta-IN-PallaviNeural       # or ta-IN-ValluvarNeural (male)
```

Optional (for real phone calls):
```bash
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+12345678901
TWILIO_WHATSAPP_NUMBER=whatsapp:+12345678901
PUBLIC_BASE_URL=https://your-ngrok-url.ngrok.io
```

### 3. Test Locally (Push-to-Talk)

```bash
source .venv/bin/activate
python -m voice_agent.cli.push_to_talk --business tuition
```

**How it works:**
- Hold **SPACE** to speak Tamil/Tanglish into mic
- Release **SPACE** → STT transcribes → LLM responds → TTS plays
- Press **SPACE** during AI reply to test **barge-in**
- Press **Ctrl+C** to exit

### 4. Run Dashboard

```bash
source .venv/bin/activate
bash scripts/run_dashboard.sh
# Visit http://localhost:8000
```

The dashboard shows:
- Recent calls with lead scores (Hot/Warm/Cold)
- Per-call transcript with latency breakdown
- Bookings (trial classes, PG visits)

### 5. Make Outbound Calls

```bash
# Single call
python -m voice_agent.cli.outbound single --to +919876543210 --business tuition

# Campaign from CSV
python -m voice_agent.cli.outbound campaign --file scripts/sample_leads.csv
```

### 6. Receive Inbound Calls (Twilio)

1. Buy a Twilio phone number
2. Expose your local server via ngrok: `ngrok http 8000`
3. Set the webhook URL in Twilio console:
   - Voice URL: `https://your-ngrok.ngrok.io/twilio/voice/inbound`
   - Status callback: `https://your-ngrok.ngrok.io/twilio/status`
4. Call your Twilio number — the agent will greet the caller in Tamil!

---

## 🗂 Project Structure

```
voice_agent/
├── __init__.py                  # Package marker
├── config.py                    # Settings (env-driven)
├── prompts.py                   # Tamil/Tanglish system prompts + tool defs
│
├── stt/
│   └── whisper_stt.py          # faster-whisper streaming Tamil STT
│
├── tts/
│   └── edge_tts.py             # Edge-TTS streaming Tamil TTS
│
├── llm/
│   └── groq_llm.py             # Groq Llama-3.3-70B with tool calling
│
├── tools/
│   └── whatsapp.py             # WhatsApp dispatch + booking tools
│
├── telephony/
│   └── twilio_connector.py     # Twilio Voice + WhatsApp + mulaw codec
│
├── agent/
│   ├── core.py                 # ⭐ Full-duplex voice loop with barge-in
│   └── conversation.py         # Per-call state + latency tracking
│
├── db/
│   └── database.py             # SQLite (calls, messages, bookings, recordings)
│
├── dashboard/
│   ├── app.py                  # FastAPI: dashboard + Twilio webhooks + WS
│   └── templates/              # Jinja2 HTML templates
│       ├── index.html
│       ├── call_detail.html
│       └── bookings.html
│
└── cli/
    ├── push_to_talk.py         # Local mic/speaker test runner
    └── outbound.py             # Outbound campaign caller

scripts/
├── setup.sh                    # One-shot setup
├── run_local_test.sh           # Launch push-to-talk
├── run_dashboard.sh            # Launch FastAPI server
└── sample_leads.csv            # Example outbound CSV
```

---

## ⚡ Latency Budget

Target: **Caller stops speaking → first audio packet < 600ms**

| Stage                       | Expected | Notes |
|-----------------------------|----------|-------|
| VAD detects end-of-speech   | ~50ms    | webrtcvad on 8kHz stream |
| STT (1s audio, small model) | ~250ms   | faster-whisper on CPU; GPU cuts this to ~50ms |
| LLM Time-to-First-Token     | ~100ms   | Groq LPU, free tier |
| TTS first byte              | ~150ms   | edge-tts Pallavi |
| Network + Twilio mux        | ~50ms    | WebSocket to Twilio |
| **Total**                   | **~600ms** | Meets target |

### Barge-in (Interruption)
- Detection: Energy-based VAD on incoming Twilio audio stream
- Detection time: **<50ms** after caller starts speaking
- Reaction: Stop sending TTS audio chunks immediately, switch to listening mode

---

## 🛠 Tamil & Tanglish Fluency

The system prompt in `voice_agent/prompts.py` is tuned for:

- **Native Tamil script** by default (தமிழ் எழுத்துக்கள்)
- **Tanglish mixing** when caller uses English words ("fees evalo?", "batch irukka?")
- **Polite address**: ஐயா/அம்மா/அண்ணா based on inferred gender
- **Natural fillers**: சரி, கண்டிப்பா, எனக்கு புரியுது, நல்லா இருக்கு
- **Short replies** (1-3 sentences) — this is a phone call, not an email
- **One question at a time** — never dump all info

### Sample Conversation

```
Caller:  வணக்கம், fees evalo கேக்கணும்?
Agent:   வணக்கம் ஐயா! மாதம் ₹1500. NEET foundation ₹3500.
         WhatsApp-ல் fee chart அனுப்பலாமா?

Caller:  ஆமாங்க, அனுப்புங்க.
Agent:   கண்டிப்பா! +91...98765 இந்த number-ஆ? [CONFIRMS]
         அனுப்பிட்டேன். வேறு ஏதாவது கேக்கணுமா?

Caller:  weekend batch இருக்கா?
Agent:   ஆமாங்க! சனி ஞாயிறு 10 மணி முதல் 12 மணி வரை. Trial class-க்கு
         வரலாம். Book பண்ணியிருவா?
```

---

## 🔧 Tools Available to the Agent

The LLM can call these tools during a conversation:

| Tool                  | Trigger                                            | Action |
|-----------------------|----------------------------------------------------|--------|
| `send_fee_chart`      | Caller asks "fees அனுப்புங்க"                    | Sends fee PDF via WhatsApp |
| `send_location_pin`   | Caller asks "address அனுப்புங்க"                 | Sends Google Maps link via WhatsApp |
| `send_study_material` | Caller asks "notes அனுப்புங்க"                    | Sends sample material PDF |
| `book_trial_class`    | Caller wants trial class                           | Records booking in DB |
| `book_pg_visit`       | Caller wants PG visit                              | Records booking in DB |
| `end_call`            | Caller says bye / no more questions                | Finalizes lead score + ends call |

---

## 📊 Database Schema

SQLite database at `voice_agent.db`. Tables:

- **calls** — One row per call (call_sid, direction, business, phone, lead_score, lead_status, summary, recording_url)
- **messages** — Per-turn messages (role: user/assistant/tool, content, latency_ms)
- **bookings** — Trial class / PG visit bookings
- **recordings** — Call recording metadata

Inspect directly:
```bash
sqlite3 voice_agent.db "SELECT call_sid, lead_status, summary FROM calls ORDER BY started_at DESC LIMIT 10;"
```

---

## 🎛 Configuration Reference

All settings live in `.env`. Key ones:

| Setting                  | Default                | Description |
|--------------------------|------------------------|-------------|
| `BUSINESS_MODE`          | shared                 | tuition / pg / shared |
| `GROQ_API_KEY`           | (required)             | Get free at console.groq.com |
| `GROQ_MODEL`             | llama-3.3-70b-versatile | Fastest Tamil-capable LLM |
| `TTS_VOICE`              | ta-IN-PallaviNeural    | Female Tamil voice (Valluvar = male) |
| `WHISPER_MODEL_SIZE`     | small                  | tiny/base/small/medium/large-v3 |
| `WHISPER_DEVICE`         | cpu                    | Switch to cuda for GPU |
| `WHISPER_LANGUAGE`       | ta                     | Force Tamil decoding |
| `TUITION_FEES_PDF_PATH`  | assets/tuition_fees.pdf | Path to your fee PDF |
| `PG_FEES_PDF_PATH`       | assets/pg_fees.pdf     | Path to your PG rent PDF |

---

## 🧪 Testing & Verification

### Smoke Test (no API keys needed)

Test the TTS engine:
```bash
python -c "
import asyncio
from voice_agent.tts import get_tts
async def test():
    tts = get_tts()
    audio = await tts.synthesize_to_bytes('வணக்கம் ஐயா! எப்படி இருக்கீங்க?')
    print(f'Got {len(audio)} bytes of MP3 audio')
asyncio.run(test())
"
```

### Full Local Loop Test (needs Groq key only)

```bash
python -m voice_agent.cli.push_to_talk --business tuition
```

### Dashboard Test

```bash
uvicorn voice_agent.dashboard.app:app --reload
# Visit http://localhost:8000
```

---

## 🚨 Production Notes

### Latency Optimization (sub-400ms achievable)

1. **GPU STT**: Switch `WHISPER_DEVICE=cuda` and `WHISPER_COMPUTE_TYPE=float16` — cuts STT from 250ms → 50ms
2. **Larger Whisper model**: `medium` or `large-v3` for better Tanglish accuracy at cost of latency
3. **Dedicated TTS**: Switch to AI4Bharat Indic-TTS for best accent, or Coqui XTTS-v2 for voice cloning
4. **Edge caching**: Pre-generate common TTS phrases ("வணக்கம் ஐயா!", "கண்டிப்பா!") to skip TTS entirely
5. **Groq Pro tier**: Removes rate limits for high call volume

### Twilio WhatsApp Production

- Twilio WhatsApp sandbox only sends to verified numbers
- For production: submit WhatsApp Business profile approval (1-3 days)
- Template messages (proactive outreach) require pre-approval
- Free-form messages allowed only within 24h of customer-initiated message

### Indian Regulatory (DLT Compliance)

- For SMS/voice campaigns to Indian numbers: register on DLT platforms (Jio/Airtel/Vodafone)
- Pre-approved templates required for promotional content
- Calling hours: 9 AM - 9 PM only (TRAI regulation)
- NDNC filter: Don't call numbers on National Do Not Call registry

---

## 🔄 Upgrade Path (When You're Ready to Scale)

| Component | Free Tier → | Paid Upgrade |
|-----------|-------------|--------------|
| STT | faster-whisper local | Deepgram Nova-2 Tamil (paid, streaming WebSocket) |
| LLM | Groq free | Groq Pro / Anthropic Claude / OpenAI GPT-4o-mini |
| TTS | edge-tts | ElevenLabs multilingual / AI4Bharat Indic-TTS self-hosted |
| Telephony | Twilio trial | Exotel (India-native, DLT-compliant) |
| DB | SQLite | PostgreSQL / Baserow (already supported) |
| Dashboard | FastAPI local | Deploy on Railway / Render / VPS |

---

## 🐛 Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError: faster_whisper` | `pip install faster-whisper==1.0.3` |
| Mic not working on Linux | `sudo apt install portaudio19-dev` then reinstall sounddevice |
| Groq rate limit (429) | Free tier is 30 RPM; upgrade or add Gemini fallback |
| TTS sounds robotic | Increase `TTS_RATE=+0%` (default +5% may be too fast for some) |
| Tamil not recognized | Set `WHISPER_LANGUAGE=ta` (not None) |
| Twilio webhook 502 | Use ngrok with `--region ap` for India |
| WhatsApp not delivered | Sandbox requires recipient verification first |
| `audioop` not found | Linux: `sudo apt install libaudiofile-dev` |

---

## 📜 License

MIT License — built with love for the Tamil-speaking community.

## 🙏 Credits

- [AI4Bharat](https://github.com/AI4Bharat) — Indic language models research
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — CTranslate2 Whisper
- [edge-tts](https://github.com/rany2/edge-tts) — Microsoft Edge TTS Python wrapper
- [Groq](https://groq.com) — LPU inference for Llama
- [Twilio](https://twilio.com) — Voice + WhatsApp APIs
- [pipecat-ai](https://github.com/pipecat-ai/pipecat) — Architecture inspiration
- [bolna-ai](https://github.com/bolna-ai/bolna) — Indian voice agent reference
