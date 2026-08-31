"""
Re-run the mail pool through the CURRENT analysis code, in controlled
batches.

Why this is needed: 448,730 of 448,873 emails (99.97%) still carry
ai_analysis written by the OLD code path — the one that blanket-copied a
single sender-level blurb onto every email from that sender via one
update_many, so a sender with 50 emails showed the identical "who this
sender is" text on all 50 instead of each mail's own content (fixed in
sales/mail_pool_ai.py, commit 9ed5b17). Only mail that has arrived since
that deploy (141 emails) has a real per-email summary. The fix is live but
historical data was never reprocessed.

How it works: clearing `ai_analysis` puts a sender's mail back into
process_sender_batch()'s candidate query, and the already-running celery
beat ("mail-pool-ai-sender-batch", every 10 min, 50 senders/run) picks it
up and rewrites it with the current code — including the per-email
summaries and the widened RFQ deep-scan trigger.

Deliberately batched by SENDER rather than one bulk update over all
448k docs: that keeps each run small and reversible, lets the beat drain
at its own rate instead of a thundering herd of Bedrock calls, and means
a bad result can be caught after the first batch instead of after the
whole pool has been rewritten.

Only touches docs still carrying the old-code stub
(ai_analysis.sender_level == true AND no ai_analysis.own_summary), so
re-running never re-clears mail the new code has already handled.

Usage:
    python resummarize_mail_pool.py --status            # progress only
    python resummarize_mail_pool.py --senders 50        # dry run
    python resummarize_mail_pool.py --senders 50 --apply
"""

import argparse
import os
import sys
from datetime import datetime

from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MAIL_DB = "torpedo_gmail"
MAIL_COLLECTION = "email_metadata"

# Docs written by the old sender-blanket path.
OLD_STUB_QUERY = {
    "ai_analysis.sender_level": True,
    "ai_analysis.own_summary": {"$exists": False},
}


def print_status(col):
    total = col.count_documents({})
    old = col.count_documents(OLD_STUB_QUERY)
    new = col.count_documents({"ai_analysis.own_summary": True})
    pending = col.count_documents({"ai_analysis": {"$exists": False}})
    done_pct = (new / total * 100) if total else 0
    print(f"  total emails            : {total}")
    print(f"  reprocessed (new code)  : {new}  ({done_pct:.2f}%)")
    print(f"  still old-code stub     : {old}")
    print(f"  queued (no ai_analysis) : {pending}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--senders", type=int, default=50,
                        help="How many senders to release per run (default 50, "
                             "matching one beat cycle).")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--status", action="store_true",
                        help="Show progress and exit.")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    col = client[MAIL_DB][MAIL_COLLECTION]

    print("=== mail pool resummarize ===")
    print_status(col)
    if args.status:
        return 0

    senders = col.distinct("from_email", OLD_STUB_QUERY)
    senders = [s for s in senders if s][: args.senders]
    if not senders:
        print("\nNothing left to reprocess — pool is current.")
        return 0

    n_docs = col.count_documents({**OLD_STUB_QUERY, "from_email": {"$in": senders}})
    print(f"\nThis run would release {len(senders)} senders / {n_docs} emails "
          f"back to the beat for reprocessing.")
    for s in senders[:10]:
        print(f"    {s}")
    if len(senders) > 10:
        print(f"    ... and {len(senders) - 10} more")

    if not args.apply:
        print("\nDry run — no writes. Re-run with --apply to release this batch.")
        return 0

    res = col.update_many(
        {**OLD_STUB_QUERY, "from_email": {"$in": senders}},
        {"$unset": {"ai_analysis": "", "ai_summary": "", "ai_processed_at": ""}},
    )
    print(f"\nReleased {res.modified_count} emails across {len(senders)} senders.")
    print("The celery beat ('mail-pool-ai-sender-batch', every 10 min) will "
          "reprocess them with the current code.")
    print(f"Released at {datetime.utcnow().isoformat()}Z")
    print("\nRe-run with --status in a few minutes to watch progress.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
