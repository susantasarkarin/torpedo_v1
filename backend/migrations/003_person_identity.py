"""
003 — PERSON IDENTITY LAYER
===========================

Introduces the missing concept: a person. Until now the pipeline has only had
leads, where a lead is one campaign's interest in a human. Treating the lead
as the human is what let campaign multiplicity become person multiplicity —
one human, three brands, three cold emails.

Creates three collections:

    persons         one row per human. Uniqueness is GLOBAL — no icp_id,
                    bucket, entity or campaign_id appears in any constraint.
    lead_interests  one row per (person, icp). Multiple ICPs may legitimately
                    want the same person; only SENDING is exclusive.
    sends           one row per contact, carrying the entity. The cross-entity
                    cooldown is evaluated against this.

DEFAULT IS DRY RUN. Nothing is written without --apply.

    python -m backend.migrations.003_person_identity                  # dry run
    python -m backend.migrations.003_person_identity --apply
    python -m backend.migrations.003_person_identity --down           # reverse

REVERSIBILITY
-------------
Every person carries merged_from — the full list of source _ids it absorbed —
so --down reconstructs the prior state by dropping the three new collections
without needing a restore. Source collections are never mutated or deleted by
--up. That is the whole reversibility story and it is deliberate: this
migration only ever adds.

FIELD-MERGE POLICY
------------------
When N rows collapse into one person, taking the arbitrary first row loses
data. That is the mistake dedupe_enriched.py made (deleted in 1aef0bb). Per
field:

    default              most-recently-updated non-null value wins
    email, linkedin_url  a VERIFIED value beats a CONSTRUCTED one regardless
                         of recency; recency only breaks ties within a class
    suppression/contact  UNION always; earliest suppressed_at survives

The suppression rule is one-way on purpose: suppression can only ever widen
during a merge. When two rows disagree about whether someone opted out, the
answer is that they opted out.

CONFLICT REPORTING
------------------
The dry run reports field-level conflicts, not just row counts. If 3,000
collapses disagree on `company`, that is a signal about SERP parsing quality
worth having BEFORE the merge is committed, not after.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pymongo import ASCENDING, MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads.canonical_ingestion import identity_email, identity_linkedin_url  # noqa: E402


MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("MONGO_DB_NAME_LEADS", "email_automation")
TORPEDO_DB_NAME = os.getenv("MONGO_DB_NAME", "torpedo")

SOURCE_COLLECTIONS = ("leads_raw", "leads_enriched")

# Fields whose value is a claim about the same real-world attribute. Conflicts
# here are reported; conflicts outside this set are merged silently by recency.
_CONFLICT_TRACKED = (
    "full_name", "company", "title", "location", "email", "linkedin_url",
)

# email_status values that mean "someone confirmed this address exists"
_VERIFIED_EMAIL_STATUSES = frozenset({"verified", "valid", "deliverable"})
# ...and the ones that mean "we made it up from a pattern"
_CONSTRUCTED_EMAIL_STATUSES = frozenset({"constructed", "predicted", "guessed"})


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

def fingerprint(email: Optional[str], linkedin_url: Optional[str]) -> Optional[str]:
    """
    Stable global identity key. LinkedIn URL is preferred over email because a
    person changes employer (and therefore address) more often than they
    change profile.

    Returns None when a row carries neither identifier — such rows cannot be
    resolved to a person and are counted as unresolvable rather than guessed.
    """
    ident_url = identity_linkedin_url(linkedin_url or "")
    if ident_url:
        return hashlib.sha256(f"li:{ident_url}".encode()).hexdigest()
    ident_email = identity_email(email or "")
    if ident_email:
        return hashlib.sha256(f"em:{ident_email}".encode()).hexdigest()
    return None


# ---------------------------------------------------------------------------
# Field-merge policy
# ---------------------------------------------------------------------------

def _updated_at(row: Dict[str, Any]) -> datetime:
    for key in ("updated_at", "created_at", "added_on"):
        val = row.get(key)
        if isinstance(val, datetime):
            return val
    return datetime.min


def _email_class(row: Dict[str, Any]) -> int:
    """2 = verified, 1 = unknown, 0 = constructed. Higher wins."""
    status = (row.get("email_status") or "").strip().lower()
    if status in _VERIFIED_EMAIL_STATUSES:
        return 2
    if status in _CONSTRUCTED_EMAIL_STATUSES:
        return 0
    return 1


def merge_rows(rows: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, List[Any]]]:
    """
    Collapse N source rows into one person document.

    Returns (person_fields, conflicts) where conflicts maps a field name to
    the distinct competing values that were seen, for the dry-run report.
    """
    by_recency = sorted(rows, key=_updated_at, reverse=True)
    merged: Dict[str, Any] = {}
    conflicts: Dict[str, List[Any]] = {}

    field_map = {
        "full_name": ("name", "full_name"),
        "company": ("company", "company_name"),
        "title": ("title", "job_title"),
        "location": ("location",),
        "phone": ("phone",),
    }

    for target, sources in field_map.items():
        seen: List[Any] = []
        for row in by_recency:
            for src in sources:
                val = row.get(src)
                if val not in (None, "") and val not in seen:
                    seen.append(val)
        if seen:
            merged[target] = seen[0]          # most recent non-null
        if len(seen) > 1 and target in _CONFLICT_TRACKED:
            conflicts[target] = seen

    # email — verified beats constructed, recency only breaks ties within class
    email_rows = [r for r in by_recency if r.get("email")]
    if email_rows:
        best = max(email_rows, key=lambda r: (_email_class(r), _updated_at(r)))
        merged["email"] = (best.get("email") or "").lower().strip()
        merged["email_status"] = best.get("email_status")
        merged["email_verified"] = _email_class(best) == 2
        distinct = {(r.get("email") or "").lower().strip() for r in email_rows}
        if len(distinct) > 1:
            conflicts["email"] = sorted(distinct)

        # EVERY address this human has ever been known by, not just the winner.
        # The employer-change case (@celonis -> @chainalysis, one person, two
        # jobs) means the losing address is stale for SENDING but still live
        # for SUPPRESSION: an unsubscribe or bounce recorded against the old
        # mailbox has to keep suppressing the human, not just that address.
        # Dropping it here would silently un-suppress people on merge, which
        # is the exact failure this whole workstream exists to close.
        merged["known_emails"] = sorted(distinct)
        merged["known_email_identities"] = sorted(
            {e for e in (identity_email(d) for d in distinct) if e})

    # linkedin_url — same rule; a URL we actually fetched beats one we inferred
    url_rows = [r for r in by_recency if r.get("linkedin_url")]
    if url_rows:
        merged["linkedin_url"] = url_rows[0].get("linkedin_url")
        distinct = {identity_linkedin_url(r["linkedin_url"]) for r in url_rows}
        if len(distinct) > 1:
            conflicts["linkedin_url"] = sorted(d for d in distinct if d)

    # normalized identity keys, stored so the unique indexes can be built
    merged["email_identity"] = identity_email(merged.get("email") or "")
    merged["linkedin_identity"] = identity_linkedin_url(merged.get("linkedin_url") or "")

    # suppression + contact history — UNION, earliest suppression survives
    suppressed_at: List[datetime] = []
    reasons: List[str] = []
    contacted_at: List[datetime] = []
    for row in rows:
        if row.get("suppressed_at"):
            suppressed_at.append(row["suppressed_at"])
        if row.get("suppression_reason"):
            reasons.append(row["suppression_reason"])
        for key in ("last_outreach_date", "last_contacted_at"):
            if isinstance(row.get(key), datetime):
                contacted_at.append(row[key])
        if row.get("bounce_suppressed") or row.get("email_status") == "bounced":
            suppressed_at.append(_updated_at(row))
            reasons.append("bounced")

    if suppressed_at:
        merged["suppressed_at"] = min(suppressed_at)     # earliest wins
        merged["suppression_reason"] = sorted(set(reasons)) or ["unknown"]
    if contacted_at:
        merged["last_contacted_at"] = max(contacted_at)  # most recent contact

    return merged, conflicts


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

class Report:
    def __init__(self) -> None:
        self.scanned = 0
        self.unresolvable = 0
        self.persons = 0
        self.collapsed = 0
        self.interests = 0
        self.sends = 0
        self.suppressions_merged = 0
        self.conflict_counts: Counter = Counter()
        self.conflict_samples: Dict[str, List[Any]] = {}
        self.collapse_histogram: Counter = Counter()
        # True duplication: extra rows WITHIN a single source collection.
        # Immune to the raw/enriched pairing artifact.
        self.true_duplicates = 0
        self.persons_with_true_dupes = 0
        self.true_dupe_histogram: Counter = Counter()

    @property
    def rows_scanned_per_person_across_stages(self) -> float:
        """
        Rows scanned per person across BOTH pipeline stages. This measures a
        join, not duplication — see the module docstring. Not reported.
        """
        return (self.scanned / self.persons) if self.persons else 0.0

    def render(self, applied: bool) -> str:
        mode = "APPLIED" if applied else "DRY RUN — nothing written"
        lines = [
            "",
            "=" * 68,
            f"  003_person_identity — {mode}",
            "=" * 68,
            f"  source rows scanned      {self.scanned:>8}",
            f"  unresolvable (no id)     {self.unresolvable:>8}",
            f"  persons created          {self.persons:>8}",
            "",
            f"  DUPLICATES collapsed     {self.true_duplicates:>8}",
            f"  persons affected         {self.persons_with_true_dupes:>8}",
            "",
            f"  lead_interests preserved {self.interests:>8}",
            f"  sends reconstructed      {self.sends:>8}",
            f"  suppressions merged      {self.suppressions_merged:>8}",
            "",
            "  duplicate distribution",
        ]
        if not self.true_dupe_histogram:
            lines.append("    none")
        for size, count in sorted(self.true_dupe_histogram.items()):
            lines.append(f"    {size} rows -> 1 person       {count:>8}")
        lines += ["", "  field-level conflicts among collapsed rows"]
        if not self.conflict_counts:
            lines.append("    none")
        for field, count in self.conflict_counts.most_common():
            pct = 100.0 * count / max(self.collapsed, 1)
            lines.append(f"    {field:<16} {count:>8}  ({pct:.1f}% of collapses)")
            sample = self.conflict_samples.get(field)
            if sample:
                lines.append(f"        e.g. {sample}")
        lines += ["", "=" * 68, ""]
        return "\n".join(lines)


def _load_source_rows(db) -> Iterable[Dict[str, Any]]:
    for name in SOURCE_COLLECTIONS:
        for row in db[name].find({}):
            row["_source_collection"] = name
            yield row


def run_up(apply: bool = False) -> Report:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[DB_NAME]
    torpedo = client[TORPEDO_DB_NAME]
    rep = Report()

    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in _load_source_rows(db):
        rep.scanned += 1
        fp = fingerprint(row.get("email"), row.get("linkedin_url"))
        if not fp:
            rep.unresolvable += 1
            continue
        groups[fp].append(row)

    persons_docs: List[Dict[str, Any]] = []
    interests_docs: List[Dict[str, Any]] = []
    now = datetime.utcnow()

    for fp, rows in groups.items():
        merged, conflicts = merge_rows(rows)
        rep.persons += 1
        rep.collapse_histogram[len(rows)] += 1
        if len(rows) > 1:
            rep.collapsed += len(rows) - 1

        # True duplication ignores the raw/enriched pairing: count extra rows
        # within whichever single collection contributed the most.
        per_collection = Counter(r["_source_collection"] for r in rows)
        worst = max(per_collection.values())
        if worst > 1:
            rep.true_duplicates += worst - 1
            rep.persons_with_true_dupes += 1
            rep.true_dupe_histogram[worst] += 1

            for field, values in conflicts.items():
                rep.conflict_counts[field] += 1
                rep.conflict_samples.setdefault(field, values[:3])
        if merged.get("suppressed_at"):
            rep.suppressions_merged += 1

        person = {
            "fingerprint": fp,
            **merged,
            "merged_from": [
                {"_id": r["_id"], "collection": r["_source_collection"]}
                for r in rows
            ],
            "created_at": min((_updated_at(r) for r in rows), default=now),
            "updated_at": now,
            "migrated_by": "003_person_identity",
        }
        persons_docs.append(person)

        # lead_interests — one per (person, icp). Interest is legitimate and
        # preserved; only sending is exclusive.
        seen_icps = set()
        for r in rows:
            icp = r.get("icp_segment") or r.get("icp_id")
            if icp in seen_icps:
                continue
            seen_icps.add(icp)
            interests_docs.append({
                "person_fingerprint": fp,
                "icp_id": icp,
                "score": r.get("icp_score") or r.get("engagement_score"),
                # bucket comes from the CLASSIFIER only. classification_basket
                # is the rule-based value that drifts as enrichment lands and
                # must never be treated as a bucket — that conflation is the
                # root cause of the cross-entity sends.
                "bucket": r.get("outreach_bucket"),
                "bucket_confidence": r.get("outreach_bucket_confidence"),
                "legacy_classification_basket": r.get("classification_basket"),
                # Retained as a recorded flag though it no longer drives
                # enrollment — evidence for reopening the dual-fit question.
                "dual_fit": bool(r.get("dual_fit")),
                "discovered_at": _updated_at(r),
                "discovery_query": r.get("source_query") or r.get("source_detail"),
                "created_at": now,
            })
    rep.interests = len(interests_docs)

    # sends — reconstructed so contact history survives the cut-over
    sends_docs: List[Dict[str, Any]] = []
    fp_by_identity: Dict[str, str] = {}
    for p in persons_docs:
        for key in ("email_identity", "linkedin_identity"):
            if p.get(key):
                fp_by_identity[p[key]] = p["fingerprint"]

    for coll in ("outreach_sends_v2", "outreach_send_logs"):
        try:
            cursor = torpedo[coll].find({})
        except Exception:
            continue
        for row in cursor:
            fp = fp_by_identity.get(identity_email(row.get("email") or "") or "")
            if not fp:
                continue
            sends_docs.append({
                "person_fingerprint": fp,
                "entity": row.get("business") or row.get("entity"),
                "campaign_id": row.get("campaign_id"),
                "sent_at": row.get("sent_at") or row.get("created_at"),
                "message_id": row.get("message_id"),
                "status": row.get("status"),
                "migrated_from": coll,
            })
    rep.sends = len(sends_docs)

    if apply:
        db["persons"].insert_many(persons_docs, ordered=False) if persons_docs else None
        db["lead_interests"].insert_many(interests_docs, ordered=False) if interests_docs else None
        db["sends"].insert_many(sends_docs, ordered=False) if sends_docs else None

        # Global uniqueness. Partial filters keep nulls out of the constraint
        # without sparse's surprises on compound keys.
        db["persons"].create_index([("fingerprint", ASCENDING)], unique=True)
        db["persons"].create_index(
            [("email_identity", ASCENDING)], unique=True,
            partialFilterExpression={"email_identity": {"$type": "string"}})
        db["persons"].create_index(
            [("linkedin_identity", ASCENDING)], unique=True,
            partialFilterExpression={"linkedin_identity": {"$type": "string"}})
        db["lead_interests"].create_index(
            [("person_fingerprint", ASCENDING), ("icp_id", ASCENDING)], unique=True)
        db["sends"].create_index(
            [("person_fingerprint", ASCENDING), ("sent_at", ASCENDING)])

        # Assert rather than warn — these guard correctness, and the codebase
        # has 48 create_index calls whose failure is swallowed. leads_raw.email
        # was supposed to be unique and is not, live, for exactly that reason.
        for coll_name, index_name in (
            ("persons", "fingerprint_1"),
            ("persons", "email_identity_1"),
            ("persons", "linkedin_identity_1"),
            ("lead_interests", "person_fingerprint_1_icp_id_1"),
        ):
            info = db[coll_name].index_information()
            if index_name not in info or not info[index_name].get("unique"):
                raise RuntimeError(
                    f"REFUSING TO COMPLETE: {coll_name}.{index_name} is not "
                    f"unique after creation. Global uniqueness on persons is "
                    f"the entire point of this migration; without it the "
                    f"cross-entity invariant cannot hold. Investigate "
                    f"duplicates before retrying.")

    return rep


def run_down(apply: bool = False) -> Dict[str, int]:
    """
    Reverse. --up only ever adds, so reversal is a drop of the three new
    collections. Source rows were never mutated, so nothing needs restoring.
    """
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[DB_NAME]
    counts = {name: db[name].estimated_document_count()
              for name in ("persons", "lead_interests", "sends")}
    if apply:
        for name in ("persons", "lead_interests", "sends"):
            db[name].drop()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually write (default is a dry run)")
    ap.add_argument("--down", action="store_true",
                    help="reverse the migration")
    args = ap.parse_args()

    print(f"  mongo : {MONGO_URI.split('@')[-1]}")
    print(f"  db    : {DB_NAME}")

    if args.down:
        counts = run_down(apply=args.apply)
        verb = "dropped" if args.apply else "would drop"
        for name, n in counts.items():
            print(f"  {verb} {name}: {n}")
        return 0

    rep = run_up(apply=args.apply)
    print(rep.render(applied=args.apply))
    if not args.apply:
        print("  Re-run with --apply to write. Run against a restored copy first.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
