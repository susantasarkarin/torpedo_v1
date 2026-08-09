"""
Backfill `panelists.invite_clicked_at` from the invitation log.

Clicks have always been recorded on panel_invitation_log only. The funnel's
stalled segments (and the drip sender that reuses them) query `panelists`, so
the "Registered, no double opt-in" segment could not see clickers and sat at ~1
against a 190K pool. services/panel_bounce_handler.mark_invite_clicked now
mirrors the click onto the panelist going forward; this backfills the ~569
people who already clicked.

Idempotent — only writes where the field is missing.

    python backend/scripts/backfill_panelist_invite_clicks.py [--dry-run]
"""

import argparse
import os
import sys

from pymongo import MongoClient, UpdateOne

BATCH = 2000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"))
    db = client["campaign_platform"]

    # Earliest click per address — a lead is re-invited repeatedly, so one
    # person owns many clicked rows.
    pipeline = [
        {"$match": {"clicked_at": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$email", "first_click": {"$min": "$clicked_at"}}},
    ]
    cursor = db["panel_invitation_log"].aggregate(pipeline, allowDiskUse=True)

    ops = []
    seen = 0
    modified = 0

    def flush():
        nonlocal ops, modified
        if not ops:
            return
        if not args.dry_run:
            modified += db["panelists"].bulk_write(ops, ordered=False).modified_count
        ops = []

    for row in cursor:
        email = (row.get("_id") or "").lower().strip()
        if not email or not row.get("first_click"):
            continue
        seen += 1
        ops.append(UpdateOne(
            {"email": email, "invite_clicked_at": {"$exists": False}},
            {"$set": {"invite_clicked_at": row["first_click"]}},
        ))
        if len(ops) >= BATCH:
            flush()
    flush()

    print(f"clickers={seen} panelists_updated={modified}{' (dry run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
