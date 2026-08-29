"""
Hide finance_client accounts whose name is a contact identity, not a
company identity — the dominant remaining junk on the Accounts page
(2026-08-29): 736 of 878 finance_client accounts (84%) match "Person Name
(Company)" — e.g. "Zarna Naik (Yescrm)", "Zoho (Intovex)", "Sales
(Spikra)" — the exact auto-import artifact pattern already documented in
consolidate_accounts.py::is_auto_generated_person_name() ("never a good
parent/canonical name for the company itself"), which was written for
account *grouping* but never used to gate what's visible on the Accounts
page at all. A further 79 are role-address or literal email identities
(no-reply@schlesingergroup.com, postmaster@burke.com, "Support (Rekkon)",
"Zohoadmin (Nynit)") — automated senders, not a company or a contact.

This is broader than the two earlier finance_client cleanups this
session (which only matched accounts traceable to a specific
mail_pool_ai-created, no-email finance customer) — this one applies to
ALL finance_client accounts regardless of origin, keyed purely on the
name shape itself. Deliberately does NOT touch bare person names with no
parenthetical/role signal (e.g. "Suman Talreja") — that's exactly the
word-shape-only heuristic that produced false positives (flagging real
companies like "IPSOS Japan Retail") earlier this session, and doing it
again without a precise signal isn't a fix, it's the same mistake with a
different target.

Same non-destructive treatment as the other cleanup scripts: crm_db.
accounts flagged (metadata.hidden_from_accounts_list), never deleted;
only the sales_accounts mirror row removed.

Usage:
    python cleanup_contact_identity_accounts.py            # dry run
    python cleanup_contact_identity_accounts.py --apply
    python cleanup_contact_identity_accounts.py --rollback <run_id>
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

# "Person Name (Company)" — the same pattern consolidate_accounts.py's
# is_auto_generated_person_name() matches.
_PAREN_SUFFIX_RE = re.compile(r"\([^)]+\)\s*$")
# Role-address / automated-sender identities, with or without a
# parenthetical company: "Sales", "Support", "Zoho", "Zohoadmin",
# "Reachus", "Reachme", "Suppliers", "no-reply@x", "postmaster@x".
_ROLE_RE = re.compile(
    r"^(sales|support|reachus|reachme|research|suppliers|zoho|zohoadmin|"
    r"sales in|no-reply|postmaster|noreply|info|admin)\b|@",
    re.IGNORECASE,
)


# Confirmed-by-hand real company names that happen to match the pattern
# above (a legitimate descriptive parenthetical, not a person's employer)
# — checked against all 14 "company suffix before the paren" cases found
# live on 2026-08-29; these were the only two that were actually real
# companies, not a contact/role identity in different clothing.
_CONFIRMED_REAL_COMPANIES = frozenset({
    "Points2Shop LLC (A Cint Group Company)",
    "Dipsticks Research Ltd (Panel Base)",
})


def is_contact_identity(name: str) -> bool:
    name = (name or "").strip()
    if not name or name in _CONFIRMED_REAL_COMPANIES:
        return False
    return bool(_PAREN_SUFFIX_RE.search(name) or _ROLE_RE.match(name))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", metavar="RUN_ID")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    ea = client["email_automation"]
    crm = client["crm_db"]
    log = ea["contact_identity_cleanup_log"]

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
        {"source": "finance_client"}, {"account_name": 1, "crm_account_id": 1})
        if is_contact_identity(d.get("account_name") or "")]

    print(f"=== {'DRY RUN' if dry_run else f'APPLY (run_id={run_id})'} — "
          f"{len(rows)} contact-identity accounts ===")
    for r in rows[:15]:
        print(f"  {r.get('account_name')!r}")
    if len(rows) > 15:
        print(f"  ... and {len(rows) - 15} more")

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
    print(f"\nRollback with: python cleanup_contact_identity_accounts.py --rollback {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
