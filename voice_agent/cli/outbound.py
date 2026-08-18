"""
voice_agent.cli.outbound — Outbound campaign caller.

USAGE:
    python -m voice_agent.cli.outbound --to +919876543210 --business tuition
    python -m voice_agent.cli.outbound --campaign-file leads.csv

The campaign file is a CSV with columns: phone,business,name
Example:
    phone,business,name
    +919876543210,tuition,Ramesh
    +919812345678,pg,Suresh
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from pathlib import Path

from ..config import get_settings
from ..db.database import init_db, get_db
from ..telephony.twilio_connector import get_twilio

logger = logging.getLogger("outbound")


DEFAULT_CAMPAIGNS = {
    "tuition": {
        "name": "Exam Model Test Announcement",
        "goal": "Inform parents about upcoming model exam on Saturday",
        "talking_points": "- Model exam this Saturday 10 AM\n- Free for current students\n- ₹100 for outsiders\n- Covers Maths, Science, English\n- Top 3 get scholarship",
        "intro": "Model exam இந்த சனிக்கிழமை 10 மணி. Free trial-ஆ வரலாம்.",
    },
    "pg": {
        "name": "New Sharing Room Available",
        "goal": "Announce new vacancy for next month",
        "talking_points": "- 2 sharing rooms available from next month\n- ₹6500/month all inclusive\n- AC, WiFi, food, laundry\n- Visit any day 10 AM - 7 PM",
        "intro": "அடுத்த மாசம் 2 sharing rooms vacant-ஆ இருக்கு. Visit வரலாம்.",
    },
}


async def place_single_call(
    to_number: str,
    business: str = "tuition",
    campaign_id: str | None = None,
):
    """Place a single outbound call via Twilio."""
    settings = get_settings()
    if not settings.twilio_account_sid:
        logger.error("Twilio not configured. Set TWILIO_ACCOUNT_SID in .env")
        return None
    twilio = get_twilio()
    call_sid = twilio.place_call(
        to_number=to_number,
        business=business,
        campaign_id=campaign_id,
    )
    db = get_db()
    db.create_call(
        call_sid=call_sid,
        direction="outbound",
        business=business,
        phone_number=to_number,
        campaign_id=campaign_id,
    )
    return call_sid


async def run_campaign(campaign_file: Path, dry_run: bool = False):
    """Run an outbound campaign from a CSV file."""
    init_db()
    if not campaign_file.exists():
        logger.error("Campaign file not found: %s", campaign_file)
        return

    with campaign_file.open() as f:
        reader = csv.DictReader(f)
        leads = list(reader)

    logger.info("Loaded %d leads from %s", len(leads), campaign_file)

    for i, lead in enumerate(leads):
        phone = lead.get("phone", "").strip()
        business = lead.get("business", "tuition").strip()
        name = lead.get("name", "").strip()
        if not phone:
            continue
        logger.info("[%d/%d] Calling %s (%s, %s)...",
                    i + 1, len(leads), phone, business, name)
        if dry_run:
            logger.info("  (dry-run — skipping actual call)")
            continue
        try:
            call_sid = await place_single_call(phone, business)
            logger.info("  → call_sid=%s", call_sid)
        except Exception as e:
            logger.error("  ✗ Failed: %s", e)
        # Stagger calls to avoid rate limits
        await asyncio.sleep(2.0)


def main():
    parser = argparse.ArgumentParser(
        description="Tamil Voice Agent — Outbound Campaign Caller"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_single = sub.add_parser("single", help="Place a single outbound call")
    p_single.add_argument("--to", required=True, help="Phone number to call (E.164)")
    p_single.add_argument("--business", choices=["tuition", "pg"], default="tuition")
    p_single.add_argument("--campaign-id", default=None)

    p_campaign = sub.add_parser("campaign", help="Run a campaign from CSV")
    p_campaign.add_argument("--file", required=True, help="CSV file path")
    p_campaign.add_argument("--dry-run", action="store_true")

    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.cmd == "single":
        asyncio.run(place_single_call(args.to, args.business, args.campaign_id))
    elif args.cmd == "campaign":
        asyncio.run(run_campaign(Path(args.file), args.dry_run))


if __name__ == "__main__":
    main()
