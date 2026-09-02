"""
Propagate outreach_bucket from leads_raw to leads_enriched, and re-derive the
ICP segment and cold-email basket from it.

THE BUG
-------
`leads/bucket_classifier.py` writes `outreach_bucket` (SFW /
COGENTIX_RESEARCH / BIM / REVIEW / REJECT) to **leads_raw**. Everything
downstream — ICP segmentation, basket assignment, campaign enrollment — reads
**leads_enriched**, where the field was never written. Measured 2026-09-02:

    leads_raw     with outreach_bucket : 17,457
    leads_enriched with outreach_bucket:      0

The consequence cascades, because the derivation is a chain:

    outreach_bucket --(outreach_config.BUCKETS[b]["icp_slug"])--> icp_segment
    icp_segment     --(canonical_ingestion.SEG_TO_BASKET)-------> basket A/B/C

With the first link missing, `icp_segment` stayed "unknown" for 87% of leads
and `compute_icp_basket` fell through to its keyword fallback, which parks
almost everything in basket **E (Nurture / Unqualified)** — 17,836 of 22,117.

So the 80% sitting in E is not a classification failure. The AI bucket
classifier had already decided; its answer just never reached the collection
that needed it.

WHAT THIS FIXES, AND WHAT IT CANNOT
-----------------------------------
Only the three *mappable* buckets carry an ICP segment. REJECT and REVIEW
deliberately do not:

    SFW / COGENTIX_RESEARCH / BIM   2,856 leads  -> 2,383 gain a real segment
    REJECT                         10,059 leads  -> correctly excluded
    REVIEW                          4,542 leads  -> the model was not confident
    (never bucket-classified)       4,539 leads

So this is worth ~2,383 leads and needs no model calls at all. The remaining
~9,081 (REVIEW + unclassified) genuinely need the bucket classifier to run.

Idempotent. Safe to re-run.

    python -m scripts.backfill_bucket_to_enriched --dry-run
    python -m scripts.backfill_bucket_to_enriched
"""

import argparse
import logging
import sys
from collections import Counter

from bson import ObjectId

from database import get_database
from leads.outreach_config import BUCKETS
from leads.canonical_ingestion import compute_icp_basket

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backfill_bucket")

# Buckets that correspond to a service line. REJECT/REVIEW intentionally absent:
# a rejected lead has no ICP, and a REVIEW lead has no *decided* one.
BUCKET_TO_SEGMENT = {
    name: cfg["icp_slug"]
    for name, cfg in BUCKETS.items()
    if cfg.get("icp_slug")
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report only")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    db = get_database("email_automation")
    R, E = db["leads_raw"], db["leads_enriched"]

    logger.info("bucket -> segment mapping: %s", BUCKET_TO_SEGMENT)

    stats = Counter()
    basket_moves = Counter()

    query = {"outreach_bucket": {"$in": list(BUCKET_TO_SEGMENT)}}
    cursor = R.find(query, {"enriched_lead_id": 1, "outreach_bucket": 1})
    if args.limit:
        cursor = cursor.limit(args.limit)

    for raw in cursor:
        stats["scanned"] += 1
        bucket = raw.get("outreach_bucket")
        segment = BUCKET_TO_SEGMENT.get(bucket)
        eid = raw.get("enriched_lead_id")
        if not eid or not segment:
            stats["no_enriched_link"] += 1
            continue
        try:
            enriched = E.find_one({"_id": ObjectId(eid)})
        except Exception:
            stats["bad_link"] += 1
            continue
        if not enriched:
            stats["no_enriched_link"] += 1
            continue

        before = enriched.get("classification_basket")
        update = {"outreach_bucket": bucket, "icp_segment": segment}

        # Re-derive the basket with the segment now present. compute_icp_basket
        # takes the PRIMARY path on a known segment, so this is deterministic —
        # it does not fall through to keyword scoring.
        merged = dict(enriched)
        merged.update(update)
        try:
            update.update(compute_icp_basket(merged))
        except Exception:
            logger.warning("basket recompute failed for %s", eid, exc_info=True)
            stats["basket_failed"] += 1

        after = update.get("classification_basket", before)
        if before != after:
            basket_moves[f"{before} -> {after}"] += 1

        if enriched.get("outreach_bucket") == bucket and \
                (enriched.get("icp_segment") or "").lower() == segment and \
                before == after:
            stats["unchanged"] += 1
            continue

        if not args.dry_run:
            E.update_one({"_id": enriched["_id"]}, {"$set": update})
        stats["written"] += 1

    logger.info("=== backfill %s ===", "DRY RUN" if args.dry_run else "complete")
    for k in sorted(stats):
        logger.info("  %-20s %d", k, stats[k])
    logger.info("  basket transitions:")
    for move, n in basket_moves.most_common(12):
        logger.info("    %-16s %d", move, n)
    if args.dry_run:
        logger.info("dry run: nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
