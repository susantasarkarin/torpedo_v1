"""
Remove literal placeholder/test-fixture account names from the Accounts
page — "N/A", "Unknown", and _SmokeCoInc_/_SmokeSyncCoInc_-style smoke-test
fixtures that leaked into production data. A small, fixed, exact-match set
(checked by hand), not a broad pattern — this is deliberately conservative
after two earlier rounds this session where looser matching first missed
real junk and then flagged real companies.

Same non-destructive treatment as the other cleanup scripts: crm_db.accounts
flagged (metadata.hidden_from_accounts_list), never deleted; only the
email_automation.sales_accounts mirror row removed.

Usage:
    python cleanup_placeholder_accounts.py            # dry run
    python cleanup_placeholder_accounts.py --apply
    python cleanup_placeholder_accounts.py --rollback <run_id>
"""

import argparse
import os
import re
import sys
import uuid
from datetime import datetime

from pymongo import MongoClient
from bson import ObjectId

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

_PLACEHOLDER_RE = re.compile(
    r"^(n/a|na|test|smoke|unknown|none|null|undefined|-{1,3}|"
    r"_smoke.*|.*smoketest.*|company not explicitly mentioned)$",
    re.IGNORECASE,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", metavar="RUN_ID")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    ea = client["email_automation"]
    crm = client["crm_db"]
    log = ea["placeholder_accounts_cleanup_log"]

    if args.rollback:
        entries = list(log.find({"run_id": args.rollback}))
        for e in entries:
            if e.get("account_id"):
                crm["accounts"].update_one(
                    {"_id": ObjectId(e["account_id"])},
                    {"$unset": {"metadata.hidden_from_accounts_list": ""}})
            if e.get("sales_account_doc"):
                ea["sales_accounts"].insert_one(e["sales_account_doc"])
        log.delete_many({"run_id": args.rollback})
        print(f"Rolled back {len(entries)} accounts from run {args.rollback}")
        return 0

    dry_run = not args.apply
    run_id = str(uuid.uuid4())

    rows = [d for d in ea["sales_accounts"].find(
        {}, {"account_name": 1, "crm_account_id": 1, "source": 1})
        if _PLACEHOLDER_RE.match((d.get("account_name") or "").strip())]

    print(f"=== {'DRY RUN' if dry_run else f'APPLY (run_id={run_id})'} — "
          f"{len(rows)} placeholder accounts ===")
    for r in rows:
        print(f"  {r.get('account_name')!r} | {r.get('source')}")

    if dry_run:
        print("\nNo writes made. Re-run with --apply.")
        return 0

    removed = flagged = 0
    for row in rows:
        now = datetime.utcnow()
        account_id = row.get("crm_account_id")
        if account_id:
            try:
                crm["accounts"].update_one(
                    {"_id": ObjectId(account_id)},
                    {"$set": {"metadata.hidden_from_accounts_list": True,
                              "updated_at": now}})
                flagged += 1
            except Exception:
                account_id = None
        log.insert_one({
            "run_id": run_id,
            "account_id": account_id,
            "sales_account_doc": row,
            "applied_at": now,
        })
        ea["sales_accounts"].delete_one({"_id": row["_id"]})
        removed += 1

    print(f"Flagged {flagged} crm_db.accounts as hidden_from_accounts_list.")
    print(f"Removed {removed} rows from email_automation.sales_accounts.")
    print(f"\nRollback with: python cleanup_placeholder_accounts.py --rollback {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
