"""
Remove the rfq_backfill placeholder accounts from the visible Accounts
page. These were created by backfill_rfq_account_links.py, deriving a
"company name" from whoever's email domain sent an RFQ — which produces
real research-industry names (Ogilvy, Dupont, Gongos) sitting next to
personal ISP webmail (Bellsouth, Bigpond, Ntlworld, Embarqmail) and SaaS
notification domains (Mailersend, Zohomeeting, Sproutsocial, Callhippo)
that were never a real client relationship, just whoever's address
happened to send one inbound email. The underlying RFQ titles are real
business inquiries — the mistake was manufacturing a full "Account" (with
"prospect" status, implying a tracked sales relationship) from a single
sender domain rather than a real, reviewed company record.

Same non-destructive treatment as cleanup_person_fallback_accounts.py:
crm_db.accounts is flagged (metadata.hidden_from_accounts_list), never
deleted, so crm_db.opportunities.account_id keeps resolving correctly if
you open that specific RFQ. Only the email_automation.sales_accounts
mirror row (what the Accounts page actually lists) is removed.

Usage:
    python cleanup_rfq_backfill_accounts.py            # dry run
    python cleanup_rfq_backfill_accounts.py --apply
    python cleanup_rfq_backfill_accounts.py --rollback <run_id>
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
    crm = client["crm_db"]
    ea = client["email_automation"]
    log = ea["rfq_backfill_cleanup_log"]

    if args.rollback:
        entries = list(log.find({"run_id": args.rollback}))
        for e in entries:
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

    accounts = list(crm["accounts"].find({"metadata.source": "rfq_backfill"}, {"name": 1}))
    print(f"=== {'DRY RUN' if dry_run else f'APPLY (run_id={run_id})'} — "
          f"{len(accounts)} rfq_backfill accounts ===")

    if dry_run:
        for a in accounts[:15]:
            print(f"  {a.get('name')!r}")
        if len(accounts) > 15:
            print(f"  ... and {len(accounts) - 15} more")
        print("\nNo writes made. Re-run with --apply.")
        return 0

    removed = 0
    for acct in accounts:
        now = datetime.utcnow()
        crm["accounts"].update_one(
            {"_id": acct["_id"]},
            {"$set": {"metadata.hidden_from_accounts_list": True, "updated_at": now}})
        sales_doc = ea["sales_accounts"].find_one({"crm_account_id": str(acct["_id"])})
        log.insert_one({
            "run_id": run_id,
            "account_id": str(acct["_id"]),
            "sales_account_doc": sales_doc,
            "applied_at": now,
        })
        if sales_doc:
            ea["sales_accounts"].delete_one({"_id": sales_doc["_id"]})
            removed += 1

    print(f"Flagged {len(accounts)} crm_db.accounts as hidden_from_accounts_list.")
    print(f"Removed {removed} rows from email_automation.sales_accounts.")
    print("crm_db.opportunities.account_id links are untouched — an RFQ opened "
          "directly still resolves to its account.")
    print(f"\nRollback with: python cleanup_rfq_backfill_accounts.py --rollback {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
