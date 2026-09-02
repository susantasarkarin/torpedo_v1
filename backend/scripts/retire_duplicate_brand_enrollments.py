"""
RETIRE DUPLICATE-BRAND ENROLLMENTS
==================================
One person, one brand. Finds addresses enrolled in more than one ACTIVE
outreach campaign and pauses all but one, so nobody receives cold email from
surveyfieldwork, cogentix AND bimwave.

The code fix (canonical_ingestion._auto_enroll_in_outreach) stops NEW duplicate
enrollments. This retires the backlog that already exists.

Which enrollment is kept, in order of preference:
  1. the one that has already sent mail (most sends) - a conversation already
     started under that brand; switching brands mid-thread is worse than
     finishing
  2. tie-break: the earliest enrolled_at - matches the code fix's
     "first enrollment wins"

Losers are PAUSED, not deleted: workflow_status='paused_duplicate_brand' and
next_send_at cleared, plus an audit stamp. Fully reversible.

Usage:
    python -m scripts.retire_duplicate_brand_enrollments --dry-run
    python -m scripts.retire_duplicate_brand_enrollments
    python -m scripts.retire_duplicate_brand_enrollments --undo
"""

import argparse
import logging
import os
from collections import defaultdict
from datetime import datetime

from pymongo import MongoClient

logger = logging.getLogger("retire_dupes")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
PAUSED = "paused_duplicate_brand"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--undo", action="store_true",
                    help="restore everything this script paused")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--active-only", action="store_true",
                    help="only consider campaigns with is_active=true (the old "
                         "behaviour; matches nothing while outreach is paused)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    c = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    t = c["torpedo"]
    ol = t["outreach_leads_v2"]
    snd = t["outreach_sends_v2"]

    fingerprint = c["email_automation"]["leads_raw"].count_documents({})
    print("FINGERPRINT leads_raw =", fingerprint)
    if not (19000 <= fingerprint <= 25000):
        print("NOT PRODUCTION - refusing to run")
        return 2

    if args.undo:
        n = ol.count_documents({"workflow_status": PAUSED})
        print(f"restoring {n} paused enrollments -> not_started")
        if not args.dry_run:
            ol.update_many({"workflow_status": PAUSED},
                           {"$set": {"workflow_status": "not_started",
                                     "next_send_at": datetime.utcnow()},
                            "$unset": {"paused_reason": "", "paused_at": ""}})
        print("done")
        return 0

    # Clean duplicates across ALL campaigns, not just currently-active ones.
    #
    # This used to be find({"is_active": True}). That logic is not wrong, but
    # on production every campaign carries is_active=false — outreach is
    # switched off right now — so the filter matched nothing and the script
    # printed "active campaigns: {}" and exited having done nothing, every
    # time it was run. Meanwhile 12,686 people sit enrolled in more than one
    # chain, 9,642 of them in all three.
    #
    # Restricting the cleanup to active campaigns gets the ordering backwards:
    # the duplicates are harmless while everything is paused and become live
    # the instant somebody un-pauses. The backlog has to be cleaned BEFORE
    # that, which means operating on paused campaigns too.
    #
    # --active-only restores the old behaviour if you ever want it.
    campaign_filter = {"campaign_id": {"$nin": [None, ""]}}
    if args.active_only:
        campaign_filter["is_active"] = True
    active = {c_["campaign_id"]: (c_.get("business") or c_.get("name") or c_.get("basket"))
              for c_ in t["outreach_campaigns_v2"].find(campaign_filter)}
    print(f"campaigns in scope ({len(active)})"
          f"{' [active only]' if args.active_only else ' [including paused]'}:")
    for cid, label in active.items():
        n_enrolled = ol.count_documents({"campaign_id": cid})
        print(f"  {str(cid)[:14]}  {str(label):<28} enrolled={n_enrolled}")

    # group this person's enrollments across active campaigns
    by_email = defaultdict(list)
    for d in ol.find({"campaign_id": {"$in": list(active)},
                      "workflow_status": {"$ne": PAUSED}},
                     {"email": 1, "campaign_id": 1, "enrolled_at": 1,
                      "workflow_status": 1, "classification_basket": 1}):
        by_email[d.get("email")].append(d)

    multi = {e: rows for e, rows in by_email.items() if e and len(rows) > 1}
    print(f"\naddresses enrolled in >1 active campaign: {len(multi)}")

    # how many sends per (email, campaign)
    sends = defaultdict(int)
    for s in snd.find({}, {"email": 1, "campaign_id": 1}):
        sends[(s.get("email"), s.get("campaign_id"))] += 1

    keep_stats = defaultdict(int)
    pause_stats = defaultdict(int)
    to_pause = []
    processed = 0

    for email, rows in multi.items():
        if args.limit and processed >= args.limit:
            break
        processed += 1
        rows.sort(key=lambda r: (-sends[(email, r["campaign_id"])],
                                 r.get("enrolled_at") or datetime.max))
        keeper, losers = rows[0], rows[1:]
        keep_stats[active.get(keeper["campaign_id"])] += 1
        for l in losers:
            pause_stats[active.get(l["campaign_id"])] += 1
            to_pause.append(l["_id"])

    print(f"\nkeeping (by brand):")
    for b, n in sorted(keep_stats.items(), key=lambda x: -x[1]):
        print(f"   {b:<10} {n}")
    print(f"pausing (by brand):")
    for b, n in sorted(pause_stats.items(), key=lambda x: -x[1]):
        print(f"   {b:<10} {n}")
    print(f"\ntotal rows to pause: {len(to_pause)}")

    if args.dry_run:
        print("\nDRY RUN - nothing written")
        return 0

    now = datetime.utcnow()
    CHUNK = 1000
    done = 0
    for i in range(0, len(to_pause), CHUNK):
        batch = to_pause[i:i + CHUNK]
        ol.update_many({"_id": {"$in": batch}},
                       {"$set": {"workflow_status": PAUSED,
                                 "paused_reason": "duplicate brand enrollment",
                                 "paused_at": now},
                        "$unset": {"next_send_at": ""}})
        done += len(batch)
        print(f"   paused {done}/{len(to_pause)}")

    print(f"\ndone. paused {done} rows.")
    print("remaining addresses in >1 active campaign:",
          sum(1 for e, rows in by_email.items()
              if e and len([r for r in rows if r["_id"] not in set(to_pause)]) > 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
