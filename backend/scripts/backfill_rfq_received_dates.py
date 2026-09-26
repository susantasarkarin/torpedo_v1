"""
Backfill metadata.rfq.received_at onto every RFQ opportunity from its source
email's real date (2026-09-26 P1 fix). created_at is left untouched -- it is
the true record of when this row was written to the CRM (mostly a
2026-08-03 bulk migration), which stays useful for audit; the RFQ page
switches to received_at for display (app/services/spine_rfq.py).

Purely additive: only ever sets a new field, never modifies amount, stage,
currency or anything else. Idempotent -- skips a record that already has
received_at, so a second run is a no-op. Writes a JSON backup of every
record it is about to touch (its _id and current metadata.rfq) before
writing anything, so a revert is possible.

Usage:
    python scripts/backfill_rfq_received_dates.py --dry-run
    python scripts/backfill_rfq_received_dates.py
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--backup-path", default=None,
                        help="Where to write the pre-change backup JSON "
                             "(default: scripts/backfill_rfq_received_dates.backup.<ts>.json)")
    args = parser.parse_args()

    from bson import ObjectId
    from database import get_db_manager
    from db_pools import get_db

    opps = get_db_manager().client["crm_db"]["opportunities"]
    mail = get_db("torpedo_gmail")["email_metadata"]

    query = {"metadata.rfq.source_email_id": {"$nin": [None, ""]},
             "metadata.rfq.received_at": {"$exists": False}}
    cursor = opps.find(query, {"metadata.rfq": 1})
    if args.limit:
        cursor = cursor.limit(args.limit)
    docs = list(cursor)
    log.info("candidates (source_email_id set, received_at not yet set): %d", len(docs))

    backup_path = args.backup_path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"backfill_rfq_received_dates.backup.{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json")
    backup = []

    stats = {"updated": 0, "no_email_found": 0, "no_date_on_email": 0}
    for d in docs:
        eid = d["metadata"]["rfq"].get("source_email_id")
        try:
            email_doc = mail.find_one({"_id": ObjectId(eid)}, {"date": 1, "timestamp": 1})
        except Exception:
            email_doc = None
        if not email_doc:
            stats["no_email_found"] += 1
            continue
        real_date = email_doc.get("date") or email_doc.get("timestamp")
        if not real_date:
            stats["no_date_on_email"] += 1
            continue

        backup.append({"_id": str(d["_id"]), "metadata_rfq_before": d.get("metadata", {}).get("rfq", {})})
        if args.dry_run:
            stats["updated"] += 1
            continue
        opps.update_one({"_id": d["_id"]}, {"$set": {"metadata.rfq.received_at": real_date}})
        stats["updated"] += 1

    if backup and not args.dry_run:
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(backup, f, indent=2, default=str)
        log.info("wrote pre-change backup for %d records to %s", len(backup), backup_path)

    log.info("%s: %s", "DRY RUN" if args.dry_run else "DONE", stats)


if __name__ == "__main__":
    main()
