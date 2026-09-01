"""
BACKFILL MAIL SEGMENTS
======================
Re-derive the `segment` / `segment_source` fields for emails that were already
AI-processed, from their STORED `ai_analysis` — no new model calls.

This exists because the AI-category -> segment mapping (mail_pool_ai.derive_segment)
became the single source of truth for the MailPool UI after those emails were
already analyzed. Rather than re-paying to reprocess them, we recompute the
segment locally from what the model already said.

Handles both shapes stored under ai_analysis:
  - full analysis  -> uses ai_analysis.category + ai_analysis.rule_classification
  - sender stub     -> uses ai_analysis.category (sender_level=True)
  - prefilter skip  -> uses ai_analysis.rule_classification (skipped=True)

Idempotent: only writes when the derived value differs from what's stored.

Usage:
    python -m sales.backfill_mail_segments --dry-run
    python -m sales.backfill_mail_segments --limit 5000
"""

import argparse
import logging
import os
import sys

logger = logging.getLogger("backfill_mail_segments")

MAIL_DB = "torpedo_gmail"
MAIL_COLLECTION = "email_metadata"


def _col():
    try:
        from db_pools import get_db
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db_pools import get_db
    return get_db(MAIL_DB)[MAIL_COLLECTION]


def _derive(ai_analysis: dict):
    """Local (no-model) segment derivation from a stored ai_analysis doc."""
    from sales.mail_pool_ai import derive_segment
    rule_result = ai_analysis.get("rule_classification")
    # A prefilter-skip marker has no AI category; its category IS the rule's.
    ai_category = ai_analysis.get("category")
    return derive_segment(ai_category, rule_result)


def run(dry_run: bool = False, limit: int = 0) -> dict:
    col = _col()
    query = {"ai_analysis": {"$exists": True}}
    cursor = col.find(query, {"ai_analysis": 1, "segment": 1, "segment_source": 1})
    if limit:
        cursor = cursor.limit(limit)

    stats = {"scanned": 0, "updated": 0, "unchanged": 0, "skipped_no_data": 0}
    for doc in cursor:
        stats["scanned"] += 1
        ai_analysis = doc.get("ai_analysis") or {}
        if not isinstance(ai_analysis, dict):
            stats["skipped_no_data"] += 1
            continue
        segment, source = _derive(ai_analysis)
        if doc.get("segment") == segment and doc.get("segment_source") == source:
            stats["unchanged"] += 1
            continue
        if dry_run:
            stats["updated"] += 1
            logger.debug("WOULD set email=%s segment=%s source=%s",
                         doc.get("_id"), segment, source)
            continue
        col.update_one({"_id": doc["_id"]},
                       {"$set": {"segment": segment, "segment_source": source}})
        stats["updated"] += 1
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill segment/segment_source from stored ai_analysis")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="0 = all")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.dry_run:
        logger.info("DRY RUN — no writes")

    stats = run(dry_run=args.dry_run, limit=args.limit)
    logger.info("=== backfill complete === %s", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
