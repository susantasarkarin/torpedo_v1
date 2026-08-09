"""
REPAIR UNUSABLE LEAD EMAILS
===========================
Clears email values that are not addresses — literal enrichment templates
(`firstname.lastname`) and local parts whose domain was dropped
(`hunter.evans`) — and marks the record for pattern discovery to fill in.

Deliberately NOT a delete. These records belong to real, named people at real
companies (Kantar, Vector Consulting, …); only the address is unusable. The
value is preserved in `guessed_email` so nothing is lost, and email_status is
set to `pending_pattern`, which is the state the ingestion path already uses
for a lead awaiting a verified domain pattern.

Prevention is in leads/canonical_ingestion.py — the guard that strips
unverified guesses used to `return` early when the value had no "@", so the
most broken values were the ones it waved through.

    python -m scripts.repair_placeholder_emails --dry-run
    python -m scripts.repair_placeholder_emails
"""

import argparse
import os
import sys
from collections import Counter

from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads.system_addresses import (  # noqa: E402
    is_malformed_address,
    is_placeholder_address,
)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

TARGETS = [
    ("email_automation", "leads_raw"),
    ("email_automation", "leads_enriched"),
    ("email_automation", "leads"),
    ("torpedo", "outreach_leads_v2"),
    ("crm_db", "leads"),
    ("campaign_platform", "leads"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    client = MongoClient(MONGO_URI)
    grand_total = 0

    for db_name, coll_name in TARGETS:
        coll = client[db_name][coll_name]
        try:
            coll.estimated_document_count()
        except Exception as exc:
            print(f"[skip] {db_name}.{coll_name}: {exc}")
            continue

        repairs = []
        kinds = Counter()
        samples = []

        for doc in coll.find({}, {"email": 1, "name": 1, "company_name": 1}):
            email = (doc.get("email") or "").strip()
            if not email:
                continue
            # `.invalid` is reserved for deliberate test data (RFC 2606). Smoke
            # fixtures live there on purpose; they are not enrichment failures
            # and blanking them would break the tests that look them up.
            if email.lower().split("@")[-1].startswith("test.invalid"):
                continue
            if is_placeholder_address(email):
                kind = "template"
            elif is_malformed_address(email):
                kind = "no_domain"
            else:
                continue
            kinds[kind] += 1
            repairs.append(doc["_id"])
            if len(samples) < 6:
                samples.append(f"{doc.get('name') or '(no name)'} <{email}> "
                               f"[{doc.get('company_name') or '-'}] -> {kind}")

        if not repairs:
            print(f"{db_name}.{coll_name}: clean")
            continue

        print(f"\n{db_name}.{coll_name}: {len(repairs):,} to repair {dict(kinds)}")
        for s in samples:
            print(f"   {s}")

        if not args.dry_run:
            fixed = 0
            for i in range(0, len(repairs), 500):
                chunk = repairs[i:i + 500]
                for doc in coll.find({"_id": {"$in": chunk}}, {"email": 1}):
                    coll.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {
                            "guessed_email": doc.get("email"),
                            "email": None,
                            "email_status": "pending_pattern",
                        }},
                    )
                    fixed += 1
            print(f"   repaired {fixed:,}")
            grand_total += fixed
        else:
            grand_total += len(repairs)

    print(f"\n{'WOULD REPAIR' if args.dry_run else 'REPAIRED'} {grand_total:,} record(s)")
    if args.dry_run:
        print("(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
