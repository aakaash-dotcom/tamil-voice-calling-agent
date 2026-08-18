#!/usr/bin/env bash
# ============================================================================
# push_to_github.sh — Push the Tamil Voice Agent project to GitHub
#
# Usage:
#   ./push_to_github.sh https://github.com/username/repo-name.git
#
# If push fails due to authentication, this script creates a ZIP fallback at
# /home/z/my-project/download/voice_agent_project.zip
# ============================================================================
set -e

REPO_URL="${1:-}"
PROJECT_ROOT="/home/z/my-project"

if [ -z "$REPO_URL" ]; then
    echo "❌ Usage: $0 <github_repo_url>"
    echo "   Example: $0 https://github.com/username/tamil-voice-agent.git"
    exit 1
fi

# Normalize URL: add .git if missing
if [[ "$REPO_URL" != *.git ]]; then
    REPO_URL="${REPO_URL}.git"
fi

cd "$PROJECT_ROOT"

echo "============================================================"
echo "  Pushing Tamil Voice Agent to GitHub"
echo "  Repo: $REPO_URL"
echo "============================================================"
echo ""

# --- Step 1: Verify .gitignore excludes secrets and large files ---
if [ ! -f ".gitignore" ]; then
    echo "❌ .gitignore not found. Aborting to prevent committing secrets/venv."
    exit 1
fi

if git check-ignore .env >/dev/null 2>&1; then
    echo "✓ .env is properly ignored (secrets protected)"
else
    echo "⚠ WARNING: .env is NOT ignored. Refusing to push — would leak API keys."
    exit 1
fi

if git check-ignore .venv >/dev/null 2>&1; then
    echo "✓ .venv is properly ignored (no 564MB commit)"
else
    echo "⚠ WARNING: .venv is NOT ignored. Refusing to push — too large."
    exit 1
fi

# --- Step 2: Stage all files ---
echo ""
echo "Staging files..."
git add -A
git status --short | head -30

# --- Step 3: Commit ---
if git diff --cached --quiet; then
    echo "ℹ No changes to commit (already up to date)"
else
    echo ""
    echo "Committing..."
    git commit -m "feat: Tamil & Tanglish AI voice calling agent

Production-grade voice agent for Tamil (தமிழ்), Tanglish, and Indian English.
Handles inbound receptionist + outbound campaigns for Tuition Centre & Gents PG.

Stack:
- STT: faster-whisper (local, free, Tamil)
- LLM: Groq Llama-3.3-70B (free tier, ~100ms TTFT)
- TTS: edge-tts ta-IN-PallaviNeural (free, native Tamil)
- Telephony + WhatsApp: Twilio
- Dashboard: FastAPI + Jinja2
- DB: SQLite

Features:
- Sub-700ms end-to-end latency (sub-500ms with GPU STT)
- Full-duplex with energy-based barge-in (<40ms)
- 6 LLM tools (fee chart, location pin, study material, bookings, end call)
- Lead scoring (Hot/Warm/Cold)
- Per-turn latency tracking in dashboard
- Dry-run mode for all external integrations" 2>&1 | tail -5
fi

# --- Step 4: Add remote (or update if exists) ---
echo ""
echo "Configuring remote..."
if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "$REPO_URL"
    echo "✓ Updated origin → $REPO_URL"
else
    git remote add origin "$REPO_URL"
    echo "✓ Added origin → $REPO_URL"
fi

# --- Step 5: Push ---
echo ""
echo "Pushing to GitHub..."
if git push -u origin main 2>&1; then
    echo ""
    echo "============================================================"
    echo "  ✅ SUCCESS — Pushed to GitHub!"
    echo "  $REPO_URL"
    echo "============================================================"
    echo ""
    echo "Clone on any machine with:"
    echo "  git clone $REPO_URL"
    echo "  cd tamil-voice-calling-agent"
    echo "  bash scripts/setup.sh"
    exit 0
else
    PUSH_EXIT=$?
    echo ""
    echo "============================================================"
    echo "  ⚠ PUSH FAILED (exit $PUSH_EXIT)"
    echo "============================================================"
    echo ""
    echo "Common causes:"
    echo "  1. Repository doesn't exist yet — create it at github.com/new first"
    echo "  2. Authentication required — GitHub needs a Personal Access Token"
    echo "     (not your password). Get one at:"
    echo "     https://github.com/settings/tokens (scope: repo)"
    echo "  3. Repository is private and you don't have access"
    echo ""
    echo "Falling back to ZIP archive..."
    bash "$PROJECT_ROOT/scripts/create_zip.sh"
    exit $PUSH_EXIT
fi
