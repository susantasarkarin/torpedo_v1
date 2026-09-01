"""
Fold the three suppression lists into one (TOR-06).

    email_automation.suppression_list          <- canonical, the destination
    torpedo.outreach_bounce_suppression        11,508 docs
    campaign_platform.panel_email_suppression

Until this runs, `messaging/suppression.py` reads all three (canonical first,
then the legacy pair), so nothing that is currently suppressed can leak through.
This just makes that read-through unnecessary.

SAFETY
------
Additive only. Nothing is deleted from the legacy collections, and an address
already in canonical is never downgraded — if canonical says "complaint" and a
legacy list says "bounced", canonical wins, because a complaint is the stronger
signal and the harder one to re-earn.

Run the dry run first. It reports exactly what would move and, more usefully,
how many addresses were suppressed in ONE channel only — every one of those is
a person who has been receiving mail from the other two.

    python -m scripts.migrate_suppressions_unified --dry-run
    python -m scripts.migrate_suppressions_unified

Idempotent. Safe to re-run.
"""

import argparse
import logging
import sys
from collections import Counter
from datetime import datetime

try:
    from database import get_database
    from messaging import suppression
except ImportError:  # pragma: no cover
    from backend.database import get_database
    from backend.messaging import suppression

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate_suppressions")

SOURCES = [
    ("torpedo", "outreach_bounce_suppression", "bounced"),
    ("campaign_platform", "panel_email_suppression", None),  # has its own reason
]

BATCH = 1000


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report only; write nothing")
    args = ap.parse_args(argv)

    canonical = get_database(suppression.CANONICAL_DB)[suppression.CANONICAL_COLLECTION]

    if not args.dry_run:
        suppression.ensure_indexes()

    existing = set()
    try:
        existing = {d["email"] for d in canonical.find({}, {"email": 1})
                    if d.get("email")}
    except Exception:
        logger.exception("could not read canonical list; aborting")
        return 1
    logger.info("canonical currently holds %d addresses", len(existing))

    seen_in = Counter()          # address -> how many lists hold it
    per_source_new = Counter()
    to_write = {}

    for dbname, colname, default_reason in SOURCES:
        try:
            cursor = get_database(dbname)[colname].find({})
        except Exception:
            logger.warning("could not read %s.%s — skipping", dbname, colname)
            continue

        count = 0
        for doc in cursor:
            addr = suppression.normalize(doc.get("email"))
            if not addr:
                continue
            count += 1
            seen_in[addr] += 1
            if addr in existing or addr in to_write:
                continue
            to_write[addr] = {
                "email": addr,
                "reason": doc.get("reason") or default_reason or "bounced",
                "source": f"migrated:{dbname}.{colname}",
                "metadata": {k: v for k, v in doc.items()
                             if k not in ("_id", "email", "reason")},
                "suppressed_at": doc.get("suppressed_at") or datetime.utcnow(),
                "suppressed_by": "migration",
            }
            per_source_new[f"{dbname}.{colname}"] += 1
        logger.info("%s.%s: %d addresses", dbname, colname, count)

    # The number worth reading: addresses suppressed in exactly one place were
    # still being mailed by the other channels.
    only_one = sum(1 for n in seen_in.values() if n == 1)
    logger.info("addresses present in only ONE legacy list: %d "
                "(each was still mailable from the other channels)", only_one)
    for source, n in per_source_new.items():
        logger.info("  %s contributes %d addresses new to canonical", source, n)
    logger.info("total to insert: %d", len(to_write))

    if args.dry_run:
        logger.info("dry run: nothing written")
        return 0

    inserted = 0
    batch = []
    for record in to_write.values():
        batch.append(record)
        if len(batch) >= BATCH:
            inserted += _flush(canonical, batch)
            batch = []
    if batch:
        inserted += _flush(canonical, batch)

    logger.info("inserted %d addresses into %s.%s",
                inserted, suppression.CANONICAL_DB, suppression.CANONICAL_COLLECTION)
    logger.info("post-migration counts: %s", suppression.stats())
    logger.info(
        "Legacy collections were NOT deleted. Leave them until every sender "
        "calls messaging.suppression, then drop the _LEGACY read-through."
    )
    return 0


def _flush(collection, batch) -> int:
    """Insert a batch, tolerating the unique-index collisions a re-run causes."""
    from pymongo import UpdateOne
    try:
        result = collection.bulk_write(
            [UpdateOne({"email": r["email"]},
                       {"$setOnInsert": r}, upsert=True) for r in batch],
            ordered=False)
        return result.upserted_count
    except Exception:
        logger.exception("batch write failed (%d records)", len(batch))
        return 0


if __name__ == "__main__":
    sys.exit(main())
