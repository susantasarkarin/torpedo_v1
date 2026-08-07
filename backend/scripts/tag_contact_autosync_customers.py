"""
TAG CONTACT-AUTOSYNCED CUSTOMERS (restore the Operations > Clients list)
=======================================================================
POST /contacts/ used to mint a finance_db.customers record for every sales
contact that carried a companyName. Contacts are leads, so the Clients page
(which reads /finance/customers/) filled up with lead companies like "2MRRI"
and ".NEWD WI-S2 Golinski, Dennis" instead of real clients.

The write path is fixed. This backfills the records it already created.

NOTHING IS DELETED. Every legitimate creation path — the finance UI
(create_customer), CSV import, and the RFQ promotion script — assigns a
`customer_number`; the auto-sync was the only path that skipped it. So records
without one get stamped `source: "contact_autosync"`, and the Clients page
filters them out via ?origin=clients. They stay queryable everywhere else, and
their contacts keep `linked_customer_id` pointing at them, so the sales-module
link survives intact.

Contacts whose company has no real client yet also get a
`pending_customer_company` placeholder, matching what the fixed write path now
stores, so the sales module can promote the company to a client later.

Usage:
    python -m scripts.tag_contact_autosync_customers --dry-run
    python -m scripts.tag_contact_autosync_customers
"""

import argparse
import os
import sys
from datetime import datetime

from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

AUTOSYNC_SOURCE = "contact_autosync"

# Two independent signals, because a single one risks hiding a real client:
#   1. no `customer_number`  — every legit creation path assigns one
#   2. no `total_receivables` — create_customer and CSV import both set it to 0
# The old auto-sync block wrote neither. Requiring both keeps pre-existing
# hand-made records that merely lack a customer number out of the match.
AUTOSYNC_QUERY = {
    "$and": [
        {"$or": [
            {"customer_number": {"$exists": False}},
            {"customer_number": None},
            {"customer_number": ""},
        ]},
        {"total_receivables": {"$exists": False}},
        {"source": {"$ne": AUTOSYNC_SOURCE}},
    ]
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing")
    ap.add_argument("--samples", type=int, default=15,
                    help="how many sample names to print")
    args = ap.parse_args()

    mongo = MongoClient(MONGO_URI)
    customers = mongo["finance_db"]["customers"]
    contacts = mongo["email_automation"]["contacts"]

    total = customers.count_documents({})
    autosynced = customers.count_documents(AUTOSYNC_QUERY)
    already_tagged = customers.count_documents({"source": AUTOSYNC_SOURCE})
    real_clients = total - autosynced - already_tagged

    print(f"finance_db.customers total ......... {total}")
    print(f"  real clients (customer_number) ... {real_clients}")
    print(f"  already tagged autosync .......... {already_tagged}")
    print(f"  to tag as autosync ............... {autosynced}")

    if autosynced:
        print(f"\nsample of records to be tagged (first {args.samples}):")
        for doc in customers.find(AUTOSYNC_QUERY, {"name": 1, "email": 1}).limit(args.samples):
            print(f"  - {doc.get('name') or '(no name)'} <{doc.get('email') or ''}>")

    # Contacts whose company is not a real client get the placeholder.
    real_client_query = {"$nor": [AUTOSYNC_QUERY, {"source": AUTOSYNC_SOURCE}]}
    real_client_names = set()
    for doc in customers.find(real_client_query, {"company_name": 1, "name": 1}):
        for key in ("company_name", "name"):
            if doc.get(key):
                real_client_names.add(doc[key])

    pending_query = {
        "companyName": {"$exists": True, "$nin": [None, "", *real_client_names]},
        "pending_customer_company": {"$exists": False},
    }
    pending = contacts.count_documents(pending_query)
    print(f"\ncontacts needing pending_customer_company placeholder: {pending}")

    if args.dry_run:
        print("\n[dry-run] no writes performed")
        return 0

    if autosynced:
        res = customers.update_many(
            AUTOSYNC_QUERY,
            {"$set": {"source": AUTOSYNC_SOURCE, "updated_at": datetime.utcnow()}},
        )
        print(f"\ntagged {res.modified_count} customers as source={AUTOSYNC_SOURCE}")

    if pending:
        res = contacts.update_many(
            pending_query,
            [{"$set": {"pending_customer_company": "$companyName",
                       "updatedAt": datetime.utcnow()}}],
        )
        print(f"set placeholder on {res.modified_count} contacts")

    remaining = customers.count_documents({"source": {"$ne": AUTOSYNC_SOURCE}})
    print(f"\nClients page (?origin=clients) will now show {remaining} clients")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
