#!/usr/bin/env python3
"""
Pause already-enrolled outreach_leads_v2 rows whose underlying lead the AI
classifier has since rejected or flagged uncertain (outreach_bucket REJECT or
REVIEW). See leads/ai_rejected_hold.py for why this is needed even after the
2026-09-26 enrollment fix.

Usage:
    python scripts/pause_ai_rejected_leads.py            # dry run, reports only
    python scripts/pause_ai_rejected_leads.py --apply    # writes for real
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient

from leads.ai_rejected_hold import apply_pause, find_ai_rejected_enrolled

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "torpedo")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[MONGO_DB_NAME]

    rows = find_ai_rejected_enrolled(db)
    print(f"Found {len(rows)} enrolled leads whose AI verdict is REJECT/REVIEW.")
    if rows:
        by_bucket = {}
        by_status = {}
        sendable_due = 0
        for r in rows:
            by_bucket[r["_ai_bucket"]] = by_bucket.get(r["_ai_bucket"], 0) + 1
            by_status[r["workflow_status"]] = by_status.get(r["workflow_status"], 0) + 1
            if r.get("sendable") is True:
                sendable_due += 1
        print(f"  by verdict: {by_bucket}")
        print(f"  by workflow_status: {by_status}")
        print(f"  currently sendable=True (would be eligible to send next cycle): {sendable_due}")

    result = apply_pause(db, rows, dry_run=not args.apply)
    if args.apply:
        print(f"\nApplied: paused {result['applied']} of {result['would_pause']} leads.")
    else:
        print(f"\nDry run only — nothing written. Would pause {result['would_pause']} leads. "
              f"Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
