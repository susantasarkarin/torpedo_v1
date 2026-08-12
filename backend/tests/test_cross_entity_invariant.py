"""
CROSS-ENTITY CONTACT INVARIANT
==============================

THE INVARIANT
-------------
    For any one person, at most one send may exist across ALL entities
    within CROSS_ENTITY_COOLDOWN_DAYS.

"Person" is a human, not a lead. A lead is one campaign's interest in a human;
the pipeline currently has no representation of the human itself, which is the
root cause this suite exists to guard.

These tests are EXPECTED TO FAIL on the current codebase. That is the point —
they are the regression guard for the Phase 1/2 identity work, written before
it so the failure is demonstrable rather than asserted. Each failure below
corresponds to a diagnosed defect:

  1. Basket D ("Dual Fit: SFW + Cogentix") enrolls one person into two
     entities 33 days apart (12-day sequence + 21-day gap). 33 < 90, so two
     brands contact the same human inside the cooldown. Ratified for removal;
     `dual_fit` is retained as a recorded flag on lead_interests.

  2. LinkedIn locale path suffixes (/es, /de, /fi) are not normalized, so one
     profile yields three lead rows. Observed in leads_enriched:
     ericdohertygloballeader/{es,de,fi} — three rows, one human, all three
     ingested within the same second by parallel ICP tasks.

  3. canonical_ingestion.normalize_email only lowercases. Plus-tags and
     Gmail-family dots are not folded, so one mailbox yields several rows.
     The correct normalizer exists in deduplication.py and has never been
     wired to the canonical door.

Once the identity layer lands, `_identity_of` and `_sends_for` are repointed
at persons.fingerprint and the sends table. The invariant itself does not
change — that is why it is expressed independently of the current schema.

Run with:
    pytest backend/tests/test_cross_entity_invariant.py -v
"""

import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import leads.canonical_ingestion as ci


# Phase 2 config. Default 90 days; overridable so the policy is not hardcoded.
CROSS_ENTITY_COOLDOWN_DAYS = int(os.getenv("CROSS_ENTITY_COOLDOWN_DAYS", "90"))


CAMPAIGNS = [
    {"campaign_id": "camp-sfw", "business": "sfw", "is_active": True},
    {"campaign_id": "camp-cog", "business": "cogentix", "is_active": True},
    {"campaign_id": "camp-bim", "business": "bimwave", "is_active": True},
]

_CAMPAIGN_TO_ENTITY = {
    "camp-sfw": "SFW",
    "camp-cog": "COGENTIX_RESEARCH",
    "camp-bim": "BIM",
}


# ---------------------------------------------------------------------------
# Minimal mongo stand-ins (same shape as test_outreach_enrollment_targeting.py,
# kept local so the two suites can diverge as the schema moves)
# ---------------------------------------------------------------------------

class _Col:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, q=None, proj=None):
        q = q or {}
        return [d for d in self.docs
                if all(d.get(k) == v for k, v in q.items()
                       if not isinstance(v, dict))]

    def find_one(self, q=None, proj=None):
        q = q or {}
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict) and "$in" in v:
                    if d.get(k) not in v["$in"]:
                        ok = False
                        break
                elif d.get(k) != v:
                    ok = False
                    break
            if ok:
                return d
        return None

    def insert_one(self, doc):
        self.docs.append(doc)

    def count_documents(self, q=None):
        return len(self.find(q or {}))


class _DB:
    def __init__(self, enrolled=None):
        self.campaigns = _Col(CAMPAIGNS)
        self.leads = _Col(enrolled)
        self.suppression = _Col([])

    def __getitem__(self, name):
        return {"outreach_campaigns_v2": self.campaigns,
                "outreach_leads_v2": self.leads,
                "outreach_bounce_suppression": self.suppression}[name]


@pytest.fixture
def db(monkeypatch):
    d = _DB()
    monkeypatch.setattr(ci, "_get_torpedo_db", lambda: d)
    return d


def _lead(basket, email="asha@acme.com"):
    return {"classification_basket": basket, "email": email,
            "name": "Asha Rao", "first_name": "Asha",
            "title": "Head of Insights"}


# ---------------------------------------------------------------------------
# Schema-independent invariant
#
# Repoint these two adapters at persons/sends after Phase 1. Everything below
# them is policy and stays put.
# ---------------------------------------------------------------------------

def _identity_of(row):
    """The human this row is about. Post-Phase-1 this becomes person_id."""
    return (row.get("email") or "").lower().strip()


def _sends_for(db):
    """(identity, entity, scheduled_at) for every scheduled contact."""
    return [
        (_identity_of(r),
         _CAMPAIGN_TO_ENTITY[r["campaign_id"]],
         r.get("next_send_at") or r.get("enrolled_at") or datetime.utcnow())
        for r in db.leads.docs
    ]


def cross_entity_violations(sends, cooldown_days=CROSS_ENTITY_COOLDOWN_DAYS):
    """
    Return [(identity, entity_a, entity_b, gap_days)] for every pair of sends
    to one person from DIFFERENT entities inside the cooldown window.

    Same-entity follow-ups within a sequence are not violations — a brand may
    follow up with its own prospect. Only crossing a brand boundary counts.
    """
    window = timedelta(days=cooldown_days)
    by_identity = {}
    for identity, entity, when in sends:
        by_identity.setdefault(identity, []).append((when, entity))

    violations = []
    for identity, rows in by_identity.items():
        rows.sort()
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                (t_a, ent_a), (t_b, ent_b) = rows[i], rows[j]
                if ent_a == ent_b:
                    continue
                gap = t_b - t_a
                if gap < window:
                    violations.append(
                        (identity, ent_a, ent_b, gap.days))
    return violations


# ===========================================================================
# THE INVARIANT
# ===========================================================================

def test_dual_fit_violates_cross_entity_cooldown(db):
    """
    EXPECTED FAIL until basket D is retired.

    D schedules SFW at T+0 and Cogentix at T+33d. The cooldown is 90d, so the
    same human hears from two brands inside the window.
    """
    ci._auto_enroll_in_outreach(_lead("D"), "enr-1")

    violations = cross_entity_violations(_sends_for(db))
    assert violations == [], (
        f"cross-entity cooldown breached: {violations} "
        f"(cooldown={CROSS_ENTITY_COOLDOWN_DAYS}d)")


def test_at_most_one_entity_per_person_after_arbitration(db):
    """
    EXPECTED FAIL until arbitration lands.

    Arbitration must pick exactly one winning entity per person. Basket D
    currently produces two.
    """
    ci._auto_enroll_in_outreach(_lead("D"), "enr-1")

    entities = {e for _, e, _ in _sends_for(db)}
    assert len(entities) <= 1, (
        f"person addressed by {len(entities)} entities: {sorted(entities)}")


@pytest.mark.parametrize("first,second", [("A", "B"), ("D", "C"), ("C", "D")])
def test_reclassification_never_crosses_entity_boundary(db, first, second):
    """
    Baskets drift as enrichment lands. Re-running ingestion must never let a
    second brand in. Guards the 8,037-person drift path from 6c97319 (this
    one should already pass — it is here so the invariant covers it).
    """
    ci._auto_enroll_in_outreach(_lead(first), "enr-1")
    ci._auto_enroll_in_outreach(_lead(second), "enr-1")

    violations = cross_entity_violations(_sends_for(db))
    assert violations == [], f"drift introduced a second brand: {violations}"


# ===========================================================================
# IDENTITY RESOLUTION — the reason the invariant is violable at all
# ===========================================================================

LOCALE_VARIANTS = [
    "https://www.linkedin.com/in/ericdohertygloballeader/es",
    "https://www.linkedin.com/in/ericdohertygloballeader/de",
    "https://www.linkedin.com/in/ericdohertygloballeader/fi",
    "https://www.linkedin.com/in/ericdohertygloballeader",
    "https://www.linkedin.com/in/ericdohertygloballeader/",
    "https://in.linkedin.com/in/ericdohertygloballeader",
    "http://LinkedIn.com/in/EricDohertyGlobalLeader?trk=public_profile",
    "https://www.linkedin.com/in/ericdohertygloballeader/#experience",
]


def test_linkedin_locale_and_host_variants_collapse_to_one_identity():
    """
    EXPECTED FAIL: locale path suffixes are not stripped by any normalizer.

    deduplication.normalize_linkedin_url handles host, www, trailing slash,
    query and fragment — but not a trailing /es, /de, /fi. These three
    variants are live in leads_enriched as three separate rows for one human.
    """
    from leads.deduplication import normalize_linkedin_url

    normalized = {normalize_linkedin_url(u) for u in LOCALE_VARIANTS}
    assert len(normalized) == 1, (
        f"{len(LOCALE_VARIANTS)} variants of one profile produced "
        f"{len(normalized)} identities: {sorted(normalized)}")


EMAIL_VARIANTS = [
    "Asha.Rao@Gmail.com",
    "asha.rao@gmail.com",
    "asharao@gmail.com",
    "asha.rao+newsletter@gmail.com",
    "asha.rao@googlemail.com",
]


def test_email_variants_collapse_at_the_canonical_door():
    """
    EXPECTED FAIL: canonical_ingestion.normalize_email only lowercases.

    The correct implementation is deduplication.normalize_email, which folds
    plus-tags and Gmail dots. ingest_lead does not call it. This asserts on
    the normalizer the ingestion path actually uses.
    """
    normalized = {ci.normalize_email(e) for e in EMAIL_VARIANTS}
    assert len(normalized) == 1, (
        f"{len(EMAIL_VARIANTS)} variants of one mailbox produced "
        f"{len(normalized)} identities: {sorted(normalized)}")


def test_dots_are_preserved_outside_gmail_family():
    """
    Dots are significant on most providers. Over-normalizing merges two
    different humans, which is worse than the bug being fixed. This must pass
    both before and after — it is a guard on the fix, not on the defect.
    """
    from leads.deduplication import normalize_email as dedup_normalize

    assert dedup_normalize("a.b@fastmail.com") != dedup_normalize("ab@fastmail.com")
    assert dedup_normalize("a.b@gmail.com") == dedup_normalize("ab@gmail.com")
