"""
Hide consolidation_synthesized accounts whose derived domain doesn't
exist (NXDOMAIN) or has no mail routing (SOA-only, no MX) — the same
company-domain-fabrication defect diagnosed in BOUNCE_DIAGNOSIS_2026-08-28.md
(the AI web-search enrichment pipeline sometimes invents a domain from a
company name), inherited here because consolidate_accounts.py synthesizes
these parent-account names from the same upstream data.

Checked all 42 non-Researchilluminous consolidation_synthesized accounts
live via MX/SOA lookup on 2026-08-29; 7 are confirmed fabricated/dead,
the other 35 resolve to a real mail-routed domain and are left alone —
this is NOT a blanket removal of the source, only the ones individually
confirmed bad, since most of this source (real vendor/research-industry
names like Disqo, Bareinternational, Criticalmix) is legitimate.

FABRICATED = frozenset({
    "Researchilluminous", "Globalmr Online", "Elitetechpark",
    "Whataboutresearch", "Adwise Research", "Tis Research", "Nativebyte",
})

Same non-destructive treatment: crm_db.accounts flagged
(metadata.hidden_from_accounts_list), never deleted; only the
sales_accounts mirror row removed.

Usage:
    python cleanup_fabricated_domain_accounts.py            # dry run
    python cleanup_fabricated_domain_accounts.py --apply
    python cleanup_fabricated_domain_accounts.py --rollback <run_id>
"""

import argparse
import os
import sys
import uuid
from datetime import datetime

from pymongo import MongoClient
from bson import ObjectId

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

FABRICATED = frozenset({
    "Researchilluminous", "Globalmr Online", "Elitetechpark",
    "Whataboutresearch", "Adwise Research", "Tis Research", "Nativebyte",
})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", metavar="RUN_ID")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    ea = client["email_automation"]
    crm = client["crm_db"]
    log = ea["fabricated_domain_cleanup_log"]

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
        {"source": "consolidation_synthesized", "account_name": {"$in": list(FABRICATED)}},
        {"account_name": 1, "crm_account_id": 1}))

    print(f"=== {'DRY RUN' if dry_run else f'APPLY (run_id={run_id})'} — "
          f"{len(rows)} fabricated-domain accounts ===")
    for r in rows:
        print(f"  {r.get('account_name')!r}")

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
    print(f"\nRollback with: python cleanup_fabricated_domain_accounts.py --rollback {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
