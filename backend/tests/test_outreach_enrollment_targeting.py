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

def test_dual_fit_enrolls_sfw_and_cogentix_only(db):
    """D means 'Dual Fit: SFW + Cogentix'. BIMwave is AEC and must not appear."""
    ci._auto_enroll_in_outreach(_lead("D"), "enr-1")
    assert _businesses(db) == ["cogentix", "sfw"]
    assert "bimwave" not in _businesses(db)


def test_dual_fit_creates_exactly_two_rows(db):
    ci._auto_enroll_in_outreach(_lead("D"), "enr-1")
    assert len(db.leads.docs) == 2


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


def test_single_after_dual_fit_does_not_add(db):
    ci._auto_enroll_in_outreach(_lead("D"), "enr-1")
    assert len(db.leads.docs) == 2
    ci._auto_enroll_in_outreach(_lead("C"), "enr-1")
    assert len(db.leads.docs) == 2, "bimwave was added on top of a dual fit"


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
