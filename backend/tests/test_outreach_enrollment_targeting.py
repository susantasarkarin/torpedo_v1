"""
OUTREACH ENROLLMENT TARGETING TESTS
===================================

Guards the fix for a live targeting failure found 2026-08-06: 2,402 addresses
had received cold email from all three brands (surveyfieldwork, cogentix,
bimwave), and 9,747 people were enrolled in all three campaigns.

Two independent causes, both covered here:

1. Per-campaign dedup. _auto_enroll_in_outreach checked
   {email, campaign_id}, which never blocked the same person being enrolled
   into a DIFFERENT brand. Baskets are recomputed as enrichment fills fields,
   so a lead classified A today and B tomorrow accumulated one enrollment per
   brand. 8,037 of the 9,747 (82%) came from this.

2. Basket D enrolled into ['sfw','cogentix','bimwave'] despite meaning
   "Dual Fit: SFW + Cogentix". D is 55% of classified leads.

Run with: pytest backend/tests/test_outreach_enrollment_targeting.py -v
"""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import leads.canonical_ingestion as ci


CAMPAIGNS = [
    {"campaign_id": "camp-sfw", "business": "sfw", "is_active": True},
    {"campaign_id": "camp-cog", "business": "cogentix", "is_active": True},
    {"campaign_id": "camp-bim", "business": "bimwave", "is_active": True},
]


class _Col:
    """Minimal mongo collection stand-in."""

    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, q=None, proj=None):
        q = q or {}
        out = []
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()
                   if not isinstance(v, dict)):
                out.append(d)
        return out

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
            "name": "Asha Rao", "first_name": "Asha", "title": "Head of Insights"}


def _businesses(db):
    by_id = {c["campaign_id"]: c["business"] for c in CAMPAIGNS}
    return sorted(by_id[d["campaign_id"]] for d in db.leads.docs)


# ============================================
# CAUSE 2 — basket D scope
# ============================================

def test_dual_fit_enrolls_nobody(db):
    """
    INVERTED 2026-08-12. Was test_dual_fit_enrolls_sfw_and_cogentix_only,
    asserting D -> ['cogentix', 'sfw'].

    Its original point still stands historically and is preserved here: D
    means "Dual Fit: SFW + Cogentix", and BIMwave is AEC, so the pre-6c97319
    loop over ['sfw','cogentix','bimwave'] was wrong. That fix was correct as
    far as it went.

    It did not go far enough. Two brands 33 days apart still breaches a 90-day
    cross-entity cooldown, so D now enrolls NOBODY and leads.arbitration owns
    the decision. See test_dual_fit_no_longer_creates_two_rows for the full
    reasoning.
    """
    ci._auto_enroll_in_outreach(_lead("D"), "enr-1")
    assert _businesses(db) == [], "basket D must no longer enroll anyone directly"


def test_dual_fit_no_longer_creates_two_rows(db):
    """
    INVERTED 2026-08-12. This test previously asserted len(...) == 2 — that
    basket D correctly enrolled one person into BOTH SFW and Cogentix. That
    behaviour is now killed, and the test is inverted rather than deleted so
    the decision survives in the place someone will look for it.

    WHY DUAL-FIT WAS KILLED

    D scheduled SFW at T+0 and Cogentix at T+33d (12-day sequence + 21-day
    gap). The cross-entity cooldown is 90 days, so 33 days put two brands in
    front of one human inside the window.

    The gap was never a contact policy — it is a scheduling artifact, derived
    from sequence length plus padding, and nothing in it refers to the
    recipient's experience.

    More decisively: basket D is assigned by compute_icp_basket, a rule-based
    function recomputed as enrichment fills industry/department/seniority. A
    person's dual-fit status is therefore not stable, so "we intended to
    contact this human twice" describes no decision anyone ever made about
    them. What existed was a rule that recomputed.

    And D was 11,291 of 20,639 classified leads (55%). A classifier placing
    the majority of leads in "fits two of our three businesses" is not
    describing the market, it is failing to separate SFW from Cogentix. That
    is now tracked as its own problem, with review-queue depth as its metric:
    a fixable classifier converges as it improves, a genuine market overlap
    does not.

    Contact for a dual-fit person is decided by leads.arbitration, which picks
    one winner and records the loser with reason='lost_arbitration' plus the
    runner-up. dual_fit is retained as a recorded flag on lead_interests — it
    no longer drives enrollment, but if the real SFW+Cogentix pair count comes
    back large it is the evidence for reopening the question.
    """
    ci._auto_enroll_in_outreach(_lead("D"), "enr-1")
    assert len(db.leads.docs) <= 1, (
        "basket D fanned out to a second brand; dual-fit enrollment was "
        "removed and arbitration owns this decision now")


# ============================================
# CAUSE 1 — cross-campaign dedup
# ============================================

@pytest.mark.parametrize("first,second", [
    ("A", "B"), ("A", "C"), ("B", "C"), ("B", "A"), ("C", "A"), ("C", "B"),
])
def test_reclassification_never_adds_a_second_brand(db, first, second):
    """The exact ('A','B','C') drift shape seen in production."""
    ci._auto_enroll_in_outreach(_lead(first), "enr-1")
    assert len(db.leads.docs) == 1
    ci._auto_enroll_in_outreach(_lead(second), "enr-1")
    assert len(db.leads.docs) == 1, (
        f"basket {first}->{second} created a second brand enrollment")


def test_first_enrollment_wins(db):
    ci._auto_enroll_in_outreach(_lead("A"), "enr-1")
    ci._auto_enroll_in_outreach(_lead("C"), "enr-1")
    assert _businesses(db) == ["sfw"]


def test_dual_fit_after_single_does_not_add(db):
    ci._auto_enroll_in_outreach(_lead("B"), "enr-1")
    ci._auto_enroll_in_outreach(_lead("D"), "enr-1")
    assert len(db.leads.docs) == 1


def test_single_after_dual_fit_enrolls_at_most_one_brand(db):
    """
    INVERTED 2026-08-12. Was test_single_after_dual_fit_does_not_add, which
    asserted that a D enrollment (2 rows) blocked a later C from adding a
    third.

    D now enrolls nobody, so a later C is the FIRST enrollment and is allowed.
    The invariant that actually matters is unchanged and is what this asserts:
    at most one brand ends up in front of the person.

    This is a deliberate loosening in one narrow respect — a lead classified D
    then reclassified C now reaches BIMwave, where before it was blocked by
    the SFW/Cogentix rows D had already created. That is correct: the block
    was a side effect of an enrollment that should never have existed, and C
    is a genuine AEC fit reached on its own merits.
    """
    ci._auto_enroll_in_outreach(_lead("D"), "enr-1")
    assert len(db.leads.docs) == 0, "D should have enrolled nobody"

    ci._auto_enroll_in_outreach(_lead("C"), "enr-1")
    assert len(db.leads.docs) <= 1, "more than one brand reached the person"
    assert _businesses(db) == ["bimwave"]


def test_different_people_are_unaffected(db):
    ci._auto_enroll_in_outreach(_lead("A", "one@acme.com"), "enr-1")
    ci._auto_enroll_in_outreach(_lead("C", "two@acme.com"), "enr-2")
    assert len(db.leads.docs) == 2
    assert _businesses(db) == ["bimwave", "sfw"]


# ============================================
# EXISTING GUARDS STILL HOLD
# ============================================

def test_basket_e_never_enrolls(db):
    ci._auto_enroll_in_outreach(_lead("E"), "enr-1")
    assert db.leads.docs == []


def test_no_email_never_enrolls(db):
    lead = _lead("A")
    lead["email"] = None
    ci._auto_enroll_in_outreach(lead, "enr-1")
    assert db.leads.docs == []


def test_cold_outreach_blocked_never_enrolls(db):
    lead = _lead("A")
    lead["cold_outreach_blocked"] = True
    ci._auto_enroll_in_outreach(lead, "enr-1")
    assert db.leads.docs == []


def test_suppressed_email_never_enrolls(db):
    db.suppression.insert_one({"email": "asha@acme.com"})
    ci._auto_enroll_in_outreach(_lead("A"), "enr-1")
    assert db.leads.docs == []
