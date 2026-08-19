"""
INDEX GUARD — assert the indexes that guard correctness
======================================================

48 `create_index` calls in this repo wrap their failure in a
`logger.warning` or a bare `pass`. Most are performance indexes where that is
fine. A small, enumerable subset carries a CORRECTNESS guarantee, and for
those a swallowed failure is silent data corruption.

That is not hypothetical. canonical_ingestion asks for:

    leads_raw.create_index([("email", ASCENDING)], unique=True, sparse=True)

wrapped in `except Exception: logger.warning(...)`. The live index is NOT
unique. The call failed once, long ago, was logged at warning level, and the
pipeline carried on reading duplicates as distinct humans ever since.

THE RULE
--------
An index whose absence would break a correctness guarantee must ASSERT on
startup, not warn. Performance indexes may keep warning. The distinction is
whether the code above the index is written as if uniqueness holds.

Usage:
    from leads.index_guard import assert_critical_indexes
    assert_critical_indexes(db)          # raises on any missing guarantee

    python -m leads.index_guard          # report, exit 1 if any are missing
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
LEADS_DB = os.getenv("MONGO_DB_NAME_LEADS", "email_automation")


@dataclass(frozen=True)
class CriticalIndex:
    collection: str
    field: str
    why: str
    sparse: bool = True

    @property
    def index_name(self) -> str:
        return f"{self.field}_1"


# The uniqueness-guarding subset. Small and enumerable on purpose — a list
# that grows to cover every index stops being read.
CRITICAL_INDEXES: List[CriticalIndex] = [
    CriticalIndex(
        "persons", "fingerprint",
        "person_repo.resolve_person is a single atomic upsert on this key. "
        "Without uniqueness it silently degrades into the read-then-write race "
        "it exists to close, and one human becomes several.",
        sparse=False),
    CriticalIndex(
        "persons", "email_identity",
        "Global email identity. Two persons sharing one identity means "
        "suppression and contact history split across them."),
    CriticalIndex(
        "persons", "linkedin_identity",
        "Global profile identity. Same failure as email_identity."),
    CriticalIndex(
        "leads_raw", "email",
        "canonical_ingestion asks for this and the live index is NOT unique — "
        "its creation failure was swallowed by a logger.warning. Duplicate "
        "rows inflate per-ICP yield counts feeding the coverage matrix's "
        "exhaustion rule, so a dry dimension cell looks productive."),
    CriticalIndex(
        "leads_raw", "linkedin_url",
        "Second identifier for leads with no email."),
    CriticalIndex(
        "leads_enriched", "linkedin_url",
        "Enriched-side identity. Absent uniqueness here is how three locale "
        "spellings of one profile became three rows."),
]


class MissingCriticalIndex(RuntimeError):
    """A correctness-guarding index is absent or not unique."""


def audit(db) -> List[Dict[str, Any]]:
    """Report the state of every critical index. Never writes."""
    results = []
    for spec in CRITICAL_INDEXES:
        try:
            info = db[spec.collection].index_information()
        except Exception as exc:
            results.append({"collection": spec.collection, "field": spec.field,
                            "status": "unreadable", "detail": str(exc),
                            "why": spec.why})
            continue

        entry = info.get(spec.index_name)
        if entry is None:
            status = "missing"
        elif not entry.get("unique"):
            status = "not_unique"
        else:
            status = "ok"
        results.append({"collection": spec.collection, "field": spec.field,
                        "status": status, "why": spec.why})
    return results


def assert_critical_indexes(db, ignore_missing_collections: bool = True) -> None:
    """
    Raise if any correctness-guarding index is absent or non-unique.

    `ignore_missing_collections` lets this run before migration 003 has created
    persons/lead_interests — a collection that does not exist yet is a
    different situation from one whose guarantee has quietly lapsed.
    """
    problems = []
    for row in audit(db):
        if row["status"] == "ok":
            continue
        if row["status"] == "missing" and ignore_missing_collections:
            try:
                if db[row["collection"]].estimated_document_count() == 0:
                    continue     # collection not populated yet
            except Exception:
                continue
        problems.append(
            f"{row['collection']}.{row['field']}: {row['status']} — {row['why']}")

    if problems:
        raise MissingCriticalIndex(
            "correctness-guarding indexes are not in place:\n  - "
            + "\n  - ".join(problems)
            + "\n\nThese ASSERT rather than warn deliberately: leads_raw.email "
              "was supposed to be unique and is not, live, because its "
              "creation failure was swallowed by a logger.warning.")


def render(rows: List[Dict[str, Any]]) -> str:
    lines = ["", "=" * 68, "  CRITICAL INDEX AUDIT", "=" * 68]
    for r in rows:
        mark = "ok " if r["status"] == "ok" else "!! "
        lines.append(f"  {mark}{r['collection']}.{r['field']:<20} [{r['status']}]")
        if r["status"] != "ok":
            lines.append(f"        {r['why']}")
    bad = [r for r in rows if r["status"] != "ok"]
    lines += ["", f"  {len(rows) - len(bad)}/{len(rows)} guarantees in place",
              "=" * 68, ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)[LEADS_DB]
    rows = audit(db)
    print(json.dumps(rows, indent=2) if args.json else render(rows))
    return 0 if all(r["status"] == "ok" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
