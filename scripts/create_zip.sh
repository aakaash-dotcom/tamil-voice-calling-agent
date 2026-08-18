#!/usr/bin/env bash
# ============================================================================
# create_zip.sh — Create a portable ZIP of the project (excludes venv, secrets)
# Fallback when git push fails.
# ============================================================================
set -e
PROJECT_ROOT="/home/z/my-project"
cd "$PROJECT_ROOT"

ZIP_PATH="$PROJECT_ROOT/download/voice_agent_project.zip"
rm -f "$ZIP_PATH"

echo "Creating ZIP archive (excluding .venv, .env, .db, audio files)..."

# Use zip with exclusions
zip -r "$ZIP_PATH" . \
    -x ".venv/*" \
    -x ".env" \
    -x ".env.local" \
    -x ".env.production" \
    -x "voice_agent.db" \
    -x "*.db-journal" \
    -x "*.db-shm" \
    -x "*.db-wal" \
    -x "download/recordings/*" \
    -x "download/*.mp3" \
    -x "download/*.wav" \
    -x "download/AGENT_SUBMISSION_REPORT.md" \
    -x "download/benchmark_results.json" \
    -x "__pycache__/*" \
    -x "*/__pycache__/*" \
    -x "*/*/__pycache__/*" \
    -x "*.pyc" \
    -x ".git/*" \
    -x "skills/*" \
    -x "node_modules/*" \
    -x "upload/*" \
    -x "*.log" \
    2>&1 | tail -5

echo ""
echo "============================================================"
echo "  ✅ ZIP created: $ZIP_PATH"
echo "  Size: $(du -h "$ZIP_PATH" | cut -f1)"
echo "============================================================"
echo ""
echo "To use on another machine:"
echo "  1. Unzip: unzip voice_agent_project.zip -d voice_agent"
echo "  2. cd voice_agent"
echo "  3. cp .env.example .env && nano .env  # Set GROQ_API_KEY"
echo "  4. bash scripts/setup.sh"
echo "  5. python -m voice_agent.cli.push_to_talk --business tuition"
