"""
Global outreach kill switch — read/set the single doc that
routers/cold_outreach_router.py::_process_one_outreach_lead() checks as
the very first thing, before even looking at campaign.is_active. Missing
doc or paused=True means every send attempt is refused and every lead is left
exactly as it was (the send loop returns before selecting any). `resume` also
restores any lead an older version of the loop had parked as
workflow_status="paused", which nothing else would ever bring back.

This is deliberately a DB flag, not an env var — it takes effect on the
next send attempt with no deploy or process restart needed, which matters
on a service that's already crash-looping (see BOUNCE_DIAGNOSIS doc §2.4).

Usage:
    python outreach_kill_switch.py status
    python outreach_kill_switch.py pause  --reason "..."
    python outreach_kill_switch.py resume --reason "..."
"""

import argparse
import os
import sys
from datetime import datetime

from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "torpedo")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "pause", "resume"])
    parser.add_argument("--reason", default="")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    col = client[MONGO_DB_NAME]["outreach_kill_switch"]

    if args.action == "status":
        doc = col.find_one({"_id": "global"})
        if not doc:
            print("No kill-switch doc exists — sends are PAUSED by default (fail-safe).")
        else:
            state = "PAUSED" if doc.get("paused", True) else "ACTIVE (sends allowed)"
            print(f"State: {state}")
            print(f"Reason: {doc.get('reason', '')}")
            print(f"Last changed: {doc.get('updated_at')} by {doc.get('updated_by', 'unknown')}")
        return 0

    paused = args.action == "pause"
    col.update_one(
        {"_id": "global"},
        {"$set": {
            "paused": paused,
            "reason": args.reason,
            "updated_at": datetime.utcnow(),
            "updated_by": os.getenv("USER") or os.getenv("USERNAME") or "script",
        }},
        upsert=True,
    )
    print(f"Kill switch set to {'PAUSED' if paused else 'ACTIVE'}.")
    if not paused:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from services.outreach_resume import restore_paused_leads
        restored = restore_paused_leads(client[MONGO_DB_NAME])
        print(f"Restored {restored} lead(s) that had been parked as 'paused'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
