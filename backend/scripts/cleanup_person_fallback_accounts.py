"""
Clean up crm_db.accounts / email_automation.sales_accounts rows created by
the person-name fallback bug fixed in sales/mail_pool_ai.py (2026-08-29).

Precise, non-heuristic identification: a finance_client-sourced account
whose metadata.source_id points to a finance_db.customers doc with
source="mail_pool_ai" AND no email on file. Empty email is the tell — a
real data-entry customer record almost always has one; the bug's fallback
path only ran when the deep-scan chunk projection didn't carry from_email
either (a related, separate gap). Spot-checked 20 of 1,577 matches by hand
— all were real person names or a bare email address, zero real companies
misidentified. This is NOT the earlier word-shape heuristic (which also
flagged real companies like "IPSOS Japan Retail") — it's a structural
data-lineage fact.

Non-destructive: crm_db.accounts is never deleted, only flagged
(metadata.is_likely_person = true) so future reconciles skip it. The
finance_db.customers doc is corrected to customer_type="individual" /
name_is_person_fallback=true (matching what new records get today).
email_automation.sales_accounts rows ARE deleted, because that collection
is a disposable, rebuildable mirror — deleting a row there just means the
account won't be adopted back next reconcile run, not data loss (the
account still exists on the CRM spine so its full history stays reachable
by whoever created it, and the account_id flag now written stops the
reconcile job from ever re-adopting it into the mirror).

Usage:
    python cleanup_person_fallback_accounts.py            # dry run
    python cleanup_person_fallback_accounts.py --apply
    python cleanup_person_fallback_accounts.py --rollback <run_id>
"""

import argparse
import os
import sys
import uuid
from datetime import datetime

from pymongo import MongoClient
from bson import ObjectId

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")


def find_candidates(crm, finance):
    accounts = crm["accounts"]
    customers = finance["customers"]
    candidates = []
    for acct in accounts.find({"metadata.source": "finance_client"},
                              {"name": 1, "metadata": 1}):
        source_id = (acct.get("metadata") or {}).get("source_id")
        if not source_id:
            continue
        try:
            cust = customers.find_one({"_id": ObjectId(source_id)})
        except Exception:
            continue
        if cust and cust.get("source") == "mail_pool_ai" and not (cust.get("email") or "").strip():
            candidates.append({
                "account_id": str(acct["_id"]),
                "account_name": acct.get("name"),
                "customer_id": str(cust["_id"]),
            })
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", metavar="RUN_ID")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    crm = client["crm_db"]
    finance = client["finance_db"]
    ea = client["email_automation"]
    log = ea["person_fallback_cleanup_log"]

    if args.rollback:
        entries = list(log.find({"run_id": args.rollback}))
        for e in entries:
            crm["accounts"].update_one(
                {"_id": ObjectId(e["account_id"])},
                {"$unset": {"metadata.is_likely_person": ""}})
            finance["customers"].update_one(
                {"_id": ObjectId(e["customer_id"])},
                {"$set": {"customer_type": "business"},
                 "$unset": {"name_is_person_fallback": ""}})
            if e.get("sales_account_doc"):
                ea["sales_accounts"].insert_one(e["sales_account_doc"])
        log.delete_many({"run_id": args.rollback})
        print(f"Rolled back {len(entries)} accounts from run {args.rollback}")
        return 0

    dry_run = not args.apply
    run_id = str(uuid.uuid4())
    candidates = find_candidates(crm, finance)
    print(f"=== {'DRY RUN' if dry_run else f'APPLY (run_id={run_id})'} — "
          f"{len(candidates)} candidates ===")
    for c in candidates[:15]:
        print(f"  {c['account_name']!r}")
    if len(candidates) > 15:
        print(f"  ... and {len(candidates) - 15} more")

    if dry_run:
        print("\nNo writes made. Re-run with --apply.")
        return 0

    removed_from_mirror = 0
    for c in candidates:
        now = datetime.utcnow()
        crm["accounts"].update_one(
            {"_id": ObjectId(c["account_id"])},
            {"$set": {"metadata.is_likely_person": True, "updated_at": now}})
        finance["customers"].update_one(
            {"_id": ObjectId(c["customer_id"])},
            {"$set": {"customer_type": "individual",
                      "name_is_person_fallback": True, "updated_at": now}})

        sales_doc = ea["sales_accounts"].find_one({"crm_account_id": c["account_id"]})
        log.insert_one({
            "run_id": run_id,
            "account_id": c["account_id"],
            "customer_id": c["customer_id"],
            "sales_account_doc": sales_doc,
            "applied_at": now,
        })
        if sales_doc:
            ea["sales_accounts"].delete_one({"_id": sales_doc["_id"]})
            removed_from_mirror += 1

    print(f"Flagged {len(candidates)} crm_db.accounts as is_likely_person.")
    print(f"Corrected {len(candidates)} finance_db.customers to customer_type=individual.")
    print(f"Removed {removed_from_mirror} rows from email_automation.sales_accounts "
          f"(the Accounts page's junk you were seeing).")
    print(f"\nRollback with: python cleanup_person_fallback_accounts.py --rollback {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
