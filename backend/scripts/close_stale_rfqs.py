"""
Close RFQs that have been sitting open with no recorded outcome.

A bulk backfill (2026-08-31 / 09-01) turned years of old mail into ~5,300
"open" RFQs, including non-RFQs such as "HDFC Life Introductory Mail". An
RFQ whose mail is months old and that nobody ever touched is not waiting for
a quote; it is history without an outcome. This closes those -- it does not
delete them: they keep their data and show under Closed.

Closed only when ALL hold:
  stage "rfq" and status "open"
  the RFQ mail (metadata.rfq.received_at) is older than --days (default 60)
  never staged through the review queue and never approved by a person
  nobody edited it (updated_at within an hour of created_at)

  python scripts/close_stale_rfqs.py              # dry run: counts + sample
  python scripts/close_stale_rfqs.py --apply
  python scripts/close_stale_rfqs.py --rollback   # reopen everything this closed
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

from pymongo import MongoClient

TAG = "close_stale_rfqs"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    args = ap.parse_args()
    opp = MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/")["crm_db"]["opportunities"]
    now = datetime.utcnow()

    if args.rollback:
        res = opp.update_many({"closed_by": TAG}, [{"$set": {"status": "$previous_status", "updated_at": now}},
                                                 {"$unset": ["closed_at", "closed_reason", "closed_by",
                                                             "previous_status"]}])
        print("reopened:", res.modified_count)
        return 0

    q = {"stage": "rfq", "status": "open",
         "metadata.rfq.received_at": {"$lt": now - timedelta(days=args.days)},
         "metadata.rfq.review_queue_id": {"$exists": False},
         "metadata.rfq.approved_by": {"$exists": False},
         "$expr": {"$lte": [{"$subtract": ["$updated_at", "$created_at"]}, 3600 * 1000]}}
    n = opp.count_documents(q)
    print(f"open RFQs to close (mail older than {args.days} days, never reviewed or edited): {n}")
    for d in opp.find(q, {"title": 1, "metadata.rfq.received_at": 1}).limit(8):
        print("  ", str((d.get("metadata") or {}).get("rfq", {}).get("received_at"))[:10], d.get("title"))
    if not args.apply:
        print("dry run -- nothing changed (use --apply)")
        return 0
    res = opp.update_many(q, [{"$set": {
        "previous_status": "$status", "status": "closed", "closed_at": now,
        "closed_reason": f"stale: RFQ mail older than {args.days} days, no outcome recorded",
        "closed_by": TAG, "updated_at": now}}])
    print("closed:", res.modified_count, "| undo: python scripts/close_stale_rfqs.py --rollback")
    return 0


if __name__ == "__main__":
    sys.exit(main())
