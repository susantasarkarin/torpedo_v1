"""
004 — REPAIR THE UNIQUENESS GUARANTEES THAT LAPSED
==================================================

canonical_ingestion asks for `leads_raw.email` to be UNIQUE. The live index is
not. The call is wrapped in `except Exception: logger.warning(...)`, so it
failed once, was logged at warning level, and the pipeline has been reading
duplicate rows as distinct humans ever since.

This repairs that class of defect for the enumerable subset of indexes that
carry a correctness guarantee (see leads/index_guard.CRITICAL_INDEXES).

    python -m backend.migrations.004_repair_unique_indexes            # dry run
    python -m backend.migrations.004_repair_unique_indexes --apply
    python -m backend.migrations.004_repair_unique_indexes --down

NEVER DELETES DATA
------------------
If duplicates block a unique index, this REPORTS them and refuses. It does not
resolve them by deleting rows — that is precisely what dedupe_enriched.py did
(3,337 documents destroyed, deleted in 1aef0bb). Collapsing duplicates is
migration 003's job, where a field-merge policy decides what survives.

So the order is: 003 collapses, then 004 locks the door behind it.

REVERSIBLE
----------
--down drops each repaired index and recreates it non-unique, restoring the
prior state exactly. No data is touched in either direction.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError, OperationFailure

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads.index_guard import CRITICAL_INDEXES, audit, render  # noqa: E402

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("MONGO_DB_NAME_LEADS", "email_automation")


def find_blocking_duplicates(db, collection: str, field: str,
                             limit: int = 20) -> List[Dict[str, Any]]:
    """Values appearing more than once — each one blocks a unique index."""
    try:
        return list(db[collection].aggregate([
            {"$match": {field: {"$nin": [None, ""]}}},
            {"$group": {"_id": f"${field}", "n": {"$sum": 1}}},
            {"$match": {"n": {"$gt": 1}}},
            {"$sort": {"n": -1}},
            {"$limit": limit},
        ]))
    except Exception:
        return []


def run(apply: bool = False, down: bool = False) -> int:
    db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)[DB_NAME]

    print(f"  mongo : {MONGO_URI.split('@')[-1]}")
    print(f"  db    : {DB_NAME}")
    print(render(audit(db)))

    repaired, blocked, skipped = [], [], []

    for spec in CRITICAL_INDEXES:
        label = f"{spec.collection}.{spec.field}"
        try:
            info = db[spec.collection].index_information()
        except Exception as exc:
            skipped.append(f"{label}: unreadable ({exc})")
            continue

        entry = info.get(spec.index_name)

        if down:
            if entry and entry.get("unique") and apply:
                db[spec.collection].drop_index(spec.index_name)
                db[spec.collection].create_index([(spec.field, ASCENDING)],
                                                 unique=False)
                repaired.append(f"{label}: reverted to non-unique")
            elif entry and entry.get("unique"):
                repaired.append(f"{label}: WOULD revert to non-unique")
            continue

        if entry and entry.get("unique"):
            skipped.append(f"{label}: already unique")
            continue

        dupes = find_blocking_duplicates(db, spec.collection, spec.field)
        if dupes:
            blocked.append({
                "index": label,
                "distinct_duplicated_values": len(dupes),
                "worst": [{"value": str(d["_id"])[:60], "rows": d["n"]}
                          for d in dupes[:5]],
            })
            continue

        if not apply:
            repaired.append(f"{label}: WOULD create UNIQUE index")
            continue

        try:
            if entry is not None:
                # Mongo refuses to redefine an existing name with new options.
                db[spec.collection].drop_index(spec.index_name)
            db[spec.collection].create_index(
                [(spec.field, ASCENDING)], unique=True, sparse=spec.sparse)
            repaired.append(f"{label}: UNIQUE index created")
        except (OperationFailure, DuplicateKeyError) as exc:
            blocked.append({"index": label, "error": str(exc)[:200]})

    verb = "reverted" if down else ("repaired" if apply else "would repair")
    print(f"\n  {verb}: {len(repaired)}")
    for r in repaired:
        print(f"    {r}")
    print(f"  skipped: {len(skipped)}")
    for s in skipped:
        print(f"    {s}")
    print(f"  BLOCKED by existing duplicates: {len(blocked)}")
    for b in blocked:
        print(f"    {b}")

    if blocked:
        print("\n  Blocked indexes are NOT resolved by deleting rows. Run "
              "migration 003 first — it collapses duplicates under a "
              "field-merge policy that decides what survives. Deleting them "
              "here is what dedupe_enriched.py did (3,337 documents).")

    if not apply and not down:
        print("\n  Dry run. Re-run with --apply. Use a restored copy first.\n")
    return 1 if blocked else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--down", action="store_true")
    args = ap.parse_args()
    return run(apply=args.apply, down=args.down)


if __name__ == "__main__":
    raise SystemExit(main())
