"""
RE-DERIVE LEGACY DUAL-FIT (BASKET D) LEADS
==========================================
Basket D no longer exists. compute_icp_basket now assigns exactly one basket
per lead — one person, one ICP, one brand. This re-runs that logic over the
leads still carrying the legacy D so they land in A, B, C or E.

Why D had to go: it fired whenever a lead cleared the threshold for BOTH
survey-fieldwork and brand, and those keyword sets overlap structurally
("consumer insights" is an MR industry AND a brand department; _match_ind
matches bidirectionally). The result was 11,291 of 20,639 classified leads
(55%) labelled "Dual Fit" and fanned into all three campaigns.

No AI calls — compute_icp_basket is pure rule-based scoring, so this is fast
and free.

Usage:
    python -m scripts.rederive_dual_fit_baskets --dry-run
    python -m scripts.rederive_dual_fit_baskets
"""

import argparse
import logging
import os
import sys
from collections import Counter
from datetime import datetime

from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads.canonical_ingestion import compute_icp_basket  # noqa: E402

logger = logging.getLogger("rederive")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    c = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    enr = c["email_automation"]["leads_enriched"]

    fp = c["email_automation"]["leads_raw"].count_documents({})
    print("FINGERPRINT leads_raw =", fp)
    if not (19000 <= fp <= 25000):
        print("NOT PRODUCTION - refusing to run")
        return 2

    q = {"classification_basket": "D"}
    total = enr.count_documents(q)
    print(f"legacy basket-D leads: {total}")

    cur = enr.find(q)
    if args.limit:
        cur = cur.limit(args.limit)

    moves = Counter()
    n = 0
    now = datetime.utcnow()
    for doc in cur:
        n += 1
        # compute_icp_basket prefers an existing icp_segment; D leads carry
        # icp_segment='dual_fit' which maps straight back to D. Clear it so the
        # keyword scoring path runs and produces a single best basket.
        probe = dict(doc)
        if (probe.get("icp_segment") or "").lower() == "dual_fit":
            probe["icp_segment"] = None
        result = compute_icp_basket(probe)
        new_basket = result.get("classification_basket")
        moves[f"D -> {new_basket}"] += 1
        if not args.dry_run:
            enr.update_one({"_id": doc["_id"]},
                           {"$set": {**result,
                                     "basket_rederived_at": now,
                                     "basket_rederived_from": "D"}})
        if n % 2000 == 0:
            print(f"   ...{n}/{total}")

    print(f"\nprocessed {n}")
    for k, v in moves.most_common():
        print(f"   {k:<12} {v}")
    if args.dry_run:
        print("\nDRY RUN - nothing written")
    else:
        print("\nremaining basket D:", enr.count_documents({"classification_basket": "D"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
