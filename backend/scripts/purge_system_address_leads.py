"""
PURGE NON-HUMAN LEADS
=====================
Removes leads created from bounce notifiers and other automated senders —
Postmaster, MAILER-DAEMON, no-reply and friends — that reply-based promotion
harvested before leads/system_addresses.py existed.

These are not merely cosmetic. Each one was ICP-classified, fanned into a
campaign and then mailed, where it bounced again, feeding the account bounce
rate that gets an SES identity throttled.

Role mailboxes (info@, sales@, billing@) are reported but NOT deleted by
default: they are junk as *named leads* but they are real, reachable addresses
and someone may have worked them. Pass --include-role to remove them too.

    python -m scripts.purge_system_address_leads --dry-run
    python -m scripts.purge_system_address_leads
    python -m scripts.purge_system_address_leads --include-role
"""

import argparse
import os
import sys
from collections import Counter

from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads.system_addresses import (  # noqa: E402
    is_malformed_address,
    is_role_address,
    is_system_address,
)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

# Every collection reply-promotion writes a lead into, verified against prod by
# counting postmaster/mailer-daemon rows in each. Kept explicit rather than
# discovered by scanning for "lead" in the name, so this can never wander into
# a collection it should not touch.
TARGETS = [
    ("email_automation", "leads_enriched"),
    ("email_automation", "leads_raw"),
    ("email_automation", "leads"),
    ("torpedo", "outreach_leads_v2"),
    ("crm_db", "leads"),
    ("campaign_platform", "leads"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-role", action="store_true",
                    help="also remove shared mailboxes (info@, sales@, billing@)")
    args = ap.parse_args()

    client = MongoClient(MONGO_URI)
    grand_total = 0

    for db_name, coll_name in TARGETS:
        coll = client[db_name][coll_name]
        try:
            total_docs = coll.estimated_document_count()
        except Exception as exc:
            print(f"[skip] {db_name}.{coll_name}: {exc}")
            continue
        if not total_docs:
            continue

        doomed_ids = []
        reasons = Counter()
        samples = []
        malformed = 0

        for doc in coll.find({}, {"email": 1, "name": 1, "company_name": 1}):
            email = (doc.get("email") or "").strip()
            if not email:
                continue
            # Never deleted. A record whose email is an unresolved enrichment
            # placeholder ("firstname.lastname") still belongs to a real named
            # person at a real company — it is a data-quality problem to fix,
            # not junk to throw away.
            if is_malformed_address(email):
                malformed += 1
                continue
            if is_system_address(email):
                reason = "system"
            elif args.include_role and is_role_address(email):
                reason = "role"
            else:
                continue
            reasons[reason] += 1
            doomed_ids.append(doc["_id"])
            if len(samples) < 8:
                samples.append(f"{doc.get('name') or '(no name)'} <{email}> "
                               f"[{doc.get('company_name') or '-'}]")

        malformed_note = f"  [{malformed:,} malformed emails left alone]" if malformed else ""

        if not doomed_ids:
            print(f"{db_name}.{coll_name}: clean ({total_docs:,} docs){malformed_note}")
            continue

        print(f"\n{db_name}.{coll_name}: {len(doomed_ids):,} of {total_docs:,} to remove "
              f"{dict(reasons)}{malformed_note}")
        for s in samples:
            print(f"   {s}")
        if len(doomed_ids) > len(samples):
            print(f"   … and {len(doomed_ids) - len(samples):,} more")

        if not args.dry_run:
            # Chunked so a very large delete cannot build one oversized command.
            removed = 0
            for i in range(0, len(doomed_ids), 1000):
                removed += coll.delete_many({"_id": {"$in": doomed_ids[i:i + 1000]}}).deleted_count
            print(f"   removed {removed:,}")
            grand_total += removed
        else:
            grand_total += len(doomed_ids)

    print(f"\n{'WOULD REMOVE' if args.dry_run else 'REMOVED'} {grand_total:,} lead(s) total")
    if args.dry_run:
        print("(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
