#!/usr/bin/env bash
# Run push-to-talk test runner
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source .venv/bin/activate 2>/dev/null || true

BUSINESS="${1:-tuition}"
python -m voice_agent.cli.push_to_talk --business "$BUSINESS"
