"""
ENROLLMENT MUST NOT PULL IN A LEAD THE AI CLASSIFIER HAS REJECTED
==================================================================

2026-09-26 finding: _build_basket_enrollment_query only ever read
classification_basket (set by the separate, earlier, rule-based
canonical_ingestion.compute_icp_basket), never outreach_bucket (set by
leads/bucket_classifier.py). A lead the AI classifier later rejected or sent to
REVIEW kept whatever basket the earlier classifier gave it and stayed
enrollable -- measured: 5,569 REJECT- and 3,190 REVIEW-bucketed leads had
already been mailed.

A tiny local matcher (not a real Mongo) evaluates the exact operators this
query produces ($exists, $ne, $nin, $in, $or) against sample documents, so
these tests check real matching semantics, not just the dict's shape.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.cold_outreach_router import _build_basket_enrollment_query


def _matches(doc, query):
    for key, cond in query.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
            continue
        val = doc.get(key)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$exists":
                    if (key in doc) != arg:
                        return False
                elif op == "$ne":
                    if val == arg:
                        return False
                elif op == "$nin":
                    if val in arg:
                        return False
                elif op == "$in":
                    if val not in arg:
                        return False
                else:
                    raise NotImplementedError(op)
        else:
            if val != cond:
                return False
    return True


BASE_OK = {"email": "a@corp.com", "email_status": "unknown", "lead_status": "Active"}


def test_query_carries_the_outreach_bucket_exclusion():
    q = _build_basket_enrollment_query("A")
    assert q["outreach_bucket"] == {"$nin": ["REJECT", "REVIEW"]}


def test_unclassified_lead_still_matches_exactly_as_before():
    """The dominant, working case: a lead the AI classifier has never touched
    at all (no outreach_bucket field) must keep enrolling normally."""
    doc = dict(BASE_OK, classification_basket="A")
    assert _matches(doc, _build_basket_enrollment_query("A")) is True


def test_ai_rejected_lead_is_excluded_even_with_a_matching_basket():
    doc = dict(BASE_OK, classification_basket="A", outreach_bucket="REJECT")
    assert _matches(doc, _build_basket_enrollment_query("A")) is False


def test_ai_review_lead_is_excluded_even_with_a_matching_basket():
    doc = dict(BASE_OK, classification_basket="A", outreach_bucket="REVIEW")
    assert _matches(doc, _build_basket_enrollment_query("A")) is False


def test_ai_accepted_lead_still_matches():
    doc = dict(BASE_OK, classification_basket="A", outreach_bucket="SFW")
    assert _matches(doc, _build_basket_enrollment_query("A")) is True


def test_bounced_and_negative_exclusions_are_unaffected_by_the_new_clause():
    bounced = dict(BASE_OK, classification_basket="A", email_status="bounced")
    negative = dict(BASE_OK, classification_basket="A", lead_status="Negative")
    assert _matches(bounced, _build_basket_enrollment_query("A")) is False
    assert _matches(negative, _build_basket_enrollment_query("A")) is False


@pytest.mark.parametrize("basket", ["A", "B", "C"])
def test_every_basket_carries_the_exclusion(basket):
    q = _build_basket_enrollment_query(basket)
    doc = dict(BASE_OK, classification_basket=basket, outreach_bucket="REJECT")
    assert _matches(doc, q) is False
