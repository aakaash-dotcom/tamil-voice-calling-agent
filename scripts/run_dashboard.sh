#!/usr/bin/env bash
# Run FastAPI dashboard + Twilio webhook server
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source .venv/bin/activate 2>/dev/null || true

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

echo "Starting dashboard at http://localhost:$PORT"
uvicorn voice_agent.dashboard.app:app --host "$HOST" --port "$PORT" --reload
