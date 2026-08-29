"""
Hide source=websearch accounts from the Accounts page, per explicit user
decision (2026-08-29): the Accounts page should only ever show real
clients/customers, never cold-outreach lead-gen prospects — even though
these are real companies (BlackRock, Airbnb, Salesforce) correctly
marked "prospect", not fabricated data like the two earlier cleanups
(person-name fallback, RFQ sender-domain guesses).

Same non-destructive treatment as the other cleanup scripts in this
directory: crm_db.accounts is flagged (metadata.hidden_from_accounts_list),
never deleted — the underlying lead-gen/outreach data and any linked
opportunities/activities stay fully intact and reachable by _id. Only the
email_automation.sales_accounts mirror row (what the Accounts page lists)
is removed. The reconcile task's adopt query already excludes this flag
(see tasks/crm_spine_tasks.py), so these won't silently reappear.

Usage:
    python cleanup_websearch_accounts.py            # dry run
    python cleanup_websearch_accounts.py --apply
    python cleanup_websearch_accounts.py --rollback <run_id>
"""

import argparse
import os
import sys
import uuid
from datetime import datetime

from pymongo import MongoClient
from bson import ObjectId

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", metavar="RUN_ID")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    ea = client["email_automation"]
    crm = client["crm_db"]
    log = ea["websearch_accounts_cleanup_log"]

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

    rows = list(ea["sales_accounts"].find(
        {"source": "websearch"}, {"account_name": 1, "crm_account_id": 1}))
    print(f"=== {'DRY RUN' if dry_run else f'APPLY (run_id={run_id})'} — "
          f"{len(rows)} websearch accounts ===")

    if dry_run:
        for r in rows[:15]:
            print(f"  {r.get('account_name')!r}")
        if len(rows) > 15:
            print(f"  ... and {len(rows) - 15} more")
        print("\nNo writes made. Re-run with --apply.")
        return 0

    removed = 0
    flagged = 0
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
    print(f"\nRollback with: python cleanup_websearch_accounts.py --rollback {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
