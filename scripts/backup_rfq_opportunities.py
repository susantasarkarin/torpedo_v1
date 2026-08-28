"""
Backup RFQ-tagged opportunities (and their sender RFQ-scan state) to a JSON
file, before scripts/clear_rfq_data.py deletes anything.

Read-only. Run this first, keep the output file, and check its path is
printed before running the clear script.

Usage:
    python scripts/backup_rfq_opportunities.py [--out-dir /root/backups]
"""
import argparse
import json
import os
from datetime import datetime

import pymongo
from bson import ObjectId, json_util

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

client = pymongo.MongoClient(MONGO_URI)
db = client["email_automation"]
crm_db = client["crm_db"]

opportunities_col = crm_db["opportunities"]
sender_analysis_col = db["mail_sender_analysis"]

# Same predicate spine_rfq._rfq_query() uses to identify an RFQ-sourced
# opportunity, minus is_deleted (a backup should include soft-deleted rows
# too, so nothing is lost if they get hard-deleted later).
RFQ_PREDICATE = {
    "$or": [
        {"stage": "rfq"},
        {"metadata.source": "rfq"},
        {"metadata.rfq": {"$exists": True}},
    ]
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="/root/backups")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(args.out_dir, f"rfq-backup-{timestamp}.json")

    opportunities = list(opportunities_col.find(RFQ_PREDICATE))
    print(f"Found {len(opportunities)} RFQ-tagged opportunities in crm_db.opportunities")

    # Also snapshot every sender's rfq_scan ledger — the clear script resets
    # this, so the backup is the only place the pre-reset scan state survives.
    senders_with_scan = list(sender_analysis_col.find(
        {"rfq_scan": {"$exists": True}},
        {"_id": 1, "rfq_scan": 1},
    ))
    print(f"Found {len(senders_with_scan)} senders with an rfq_scan ledger")

    payload = {
        "backed_up_at": datetime.utcnow().isoformat(),
        "mongo_uri_db": opportunities_col.database.name,
        "opportunities": opportunities,
        "sender_rfq_scans": senders_with_scan,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        # json_util handles ObjectId/datetime the same way the rest of the
        # backend's Mongo tooling does, so the file round-trips cleanly with
        # json_util.loads() if a restore is ever needed.
        f.write(json_util.dumps(payload, indent=2))

    print(f"\nBackup written to {out_path}")
    print(f"  {len(opportunities)} opportunities, {len(senders_with_scan)} sender scan ledgers")
    print("\nKeep this file before running scripts/clear_rfq_data.py.")


if __name__ == "__main__":
    main()
