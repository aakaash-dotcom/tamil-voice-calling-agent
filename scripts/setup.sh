#!/usr/bin/env bash
# ============================================================================
# Setup script — Tamil Voice Agent
# Usage: bash scripts/setup.sh
# ============================================================================
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "============================================================"
echo "  Tamil Voice Agent — Setup"
echo "============================================================"
echo ""

# --- Python version check ---
if ! command -v python3 &> /dev/null; then
    echo "✗ Python 3 is required but not installed."
    exit 1
fi
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✓ Found Python $PY_VERSION"

PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    echo "✗ Python 3.10+ required (found $PY_VERSION)"
    exit 1
fi

# --- System packages (Linux) ---
echo ""
echo "Installing system dependencies..."
if command -v apt-get &> /dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq \
        python3-dev python3-venv \
        portaudio19-dev \
        ffmpeg \
        libsndfile1 \
        espeak-ng \
        2>/dev/null || echo "  (some packages may already be installed)"
else
    echo "  (apt-get not found — please install portaudio19-dev, ffmpeg, libsndfile1 manually)"
fi

# --- Virtual environment ---
echo ""
echo "Creating Python virtual environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

# --- Upgrade pip ---
pip install --upgrade pip wheel setuptools --quiet

# --- Install Python deps ---
echo ""
echo "Installing Python dependencies (this may take 3-5 minutes)..."
pip install -r requirements.txt --quiet

# --- .env file ---
echo ""
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✓ Created .env from .env.example"
    echo "  ⚠ EDIT .env and fill in your GROQ_API_KEY and Twilio credentials"
else
    echo "✓ .env already exists"
fi

# --- Assets dir ---
mkdir -p assets
mkdir -p download/recordings

# --- Sample fee PDFs (placeholders) ---
echo ""
echo "Generating sample fee PDFs..."
python3 -c "
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
import os

def make_pdf(path, title, lines):
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    c.setFont('Helvetica-Bold', 20)
    c.drawString(20*mm, h - 30*mm, title)
    c.setFont('Helvetica', 12)
    y = h - 50*mm
    for line in lines:
        c.drawString(20*mm, y, line)
        y -= 7*mm
    c.save()
    print(f'  ✓ Created {path}')

# Tuition fees
make_pdf('assets/tuition_fees.pdf', 'Vidhya Tuition Centre — Fee Structure', [
    'Classes 6-10 (all subjects): Rs.1500/month',
    'Classes 11-12 (PCM/PCB): Rs.2500/month',
    'NEET / JEE Foundation: Rs.3500/month',
    'Weekend Crash Course: Rs.5000 (3 months)',
    '',
    'Batch Timings:',
    '  Weekday: 5 PM - 7 PM',
    '  Weekend: 10 AM - 12 PM',
    '',
    'Trial Class: FREE (1 session)',
    'Address: No.42, Gandhipuram, Coimbatore 641012',
    'Phone: +91 422 5555 555',
])

# PG fees
make_pdf('assets/pg_fees.pdf', 'Shanthi Gents PG — Rent Structure', [
    'Sharing Room (2 sharing): Rs.6500/month',
    'Single Room: Rs.9500/month',
    'Deposit: 2 months (refundable)',
    '',
    'Amenities (all inclusive):',
    '  - 24/7 WiFi (100 Mbps)',
    '  - Air Conditioning',
    '  - 3 meals daily (veg + non-veg)',
    '  - Hot water 24/7',
    '  - Laundry service (weekly)',
    '  - 24/7 security',
    '',
    'Address: 3rd Floor, Crosscut Road, Gandhipuram, Coimbatore 641012',
    'Phone: +91 422 5555 556',
])
" 2>&1 | head -20

# --- Final check ---
echo ""
echo "============================================================"
echo "  ✓ Setup complete!"
echo "============================================================"
echo ""
echo "Next steps:"
echo "  1. Edit .env and set GROQ_API_KEY (get free at https://console.groq.com)"
echo "  2. (Optional) Add Twilio credentials for real phone calls"
echo "  3. Test locally with push-to-talk:"
echo "       source .venv/bin/activate"
echo "       python -m voice_agent.cli.push_to_talk --business tuition"
echo "  4. Run the dashboard:"
echo "       uvicorn voice_agent.dashboard.app:app --reload"
echo "  5. Visit http://localhost:8000"
echo ""
