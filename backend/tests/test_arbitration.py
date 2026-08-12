"""
CROSS-ENTITY ARBITRATION TESTS
==============================

One person, one entity. Covers the auto-pick path (shipping), the gated
review branch (written, defaulted off), and the global cooldown.

Run with:
    pytest backend/tests/test_arbitration.py -v
"""

import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import arbitration as arb  # noqa: E402


NOW = datetime(2026, 8, 12, 12, 0, 0)


def _interest(bucket, conf, score=5, icp=None, discovered=None):
    return {
        "icp_id": icp or bucket.lower(),
        "bucket": bucket,
        "bucket_confidence": conf,
        "score": score,
        "discovered_at": discovered or NOW,
    }


# ===========================================================================
# Auto-pick — ships now
# ===========================================================================

def test_single_interest_needs_no_arbitration():
    r = arb.arbitrate([_interest("SFW", 0.9)], now=NOW)
    assert r.outcome == "single_interest"
    assert r.winner == "SFW"
    assert r.may_send


def test_highest_confidence_wins():
    r = arb.arbitrate([_interest("SFW", 0.60), _interest("BIM", 0.95)], now=NOW)
    assert r.outcome == "arbitrated"
    assert r.winner == "BIM"
    assert r.may_send


def test_only_the_winner_may_send():
    r = arb.arbitrate(
        [_interest("SFW", 0.95), _interest("BIM", 0.40),
         _interest("COGENTIX_RESEARCH", 0.30)], now=NOW)
    assert r.winner == "SFW"
    assert {l["bucket"] for l in r.losers} == {"BIM", "COGENTIX_RESEARCH"}
    assert all(l["reason"] == "lost_arbitration" for l in r.losers)


def test_losers_record_both_winner_and_runner_up():
    """
    The runner-up is the evidence for the classifier-vs-market question. If
    one bucket is consistently runner-up to another across the corpus, that is
    a market overlap wearing a confidence score — and the data has to already
    exist when someone asks, not need a backfill.
    """
    r = arb.arbitrate(
        [_interest("SFW", 0.95), _interest("COGENTIX_RESEARCH", 0.70),
         _interest("BIM", 0.20)], now=NOW)
    assert r.winner == "SFW"
    assert r.runner_up == "COGENTIX_RESEARCH"
    for loser in r.losers:
        assert loser["winning_entity"] == "SFW"
        assert loser["runner_up_entity"] == "COGENTIX_RESEARCH"


def test_runner_up_is_the_best_of_a_different_bucket_not_merely_second():
    """Two ICPs may share the winning bucket; the runner-up must differ."""
    r = arb.arbitrate([
        _interest("SFW", 0.95, icp="sfw_a"),
        _interest("SFW", 0.90, icp="sfw_b"),
        _interest("BIM", 0.50),
    ], now=NOW)
    assert r.winner == "SFW"
    assert r.runner_up == "BIM"


def test_tie_breaks_order_interests_within_a_bucket():
    """
    Score then discovered_at, as specified. Demonstrated WITHIN one bucket —
    see test_cross_bucket_tie_is_ambiguity_not_a_tie_break for why that
    matters.
    """
    earlier = NOW - timedelta(days=10)
    r = arb.arbitrate([
        _interest("SFW", 0.80, score=3, icp="sfw_a"),
        _interest("SFW", 0.80, score=9, icp="sfw_b"),
    ], now=NOW)
    assert r.winning_interest["icp_id"] == "sfw_b", "equal confidence should fall to score"

    r2 = arb.arbitrate([
        _interest("SFW", 0.80, score=5, icp="late", discovered=NOW),
        _interest("SFW", 0.80, score=5, icp="early", discovered=earlier),
    ], now=NOW)
    assert r2.winning_interest["icp_id"] == "early", "equal on both -> first to find them"


def test_cross_bucket_tie_is_ambiguity_not_a_tie_break():
    """
    SPEC TENSION, resolved deliberately — documented so it is not read as a bug.

    The plan specified BOTH "tie-break on score, then discovered_at" AND
    "route to review when the top two are within 0.15 confidence". For two
    DIFFERENT buckets these conflict: an exact confidence tie is 0.0 apart,
    which is inside the margin, so ambiguity fires and the tie-breaks never
    run.

    Ambiguity wins, and that is the right way round. Two entities the
    classifier scored identically is the definition of "we cannot tell who
    should own this person" — picking on ICP score would be a coin flip
    dressed as a rule, and the plan's own reasoning says a person who looks
    like a fit for two entities deserves a human eye.

    Consequence: under default config, score and discovered_at order interests
    WITHIN a bucket, and rarely decide between buckets. They regain
    cross-bucket influence only if ARBITRATION_AMBIGUITY_MARGIN is lowered or
    ARBITRATION_ORDERING is repointed.
    """
    r = arb.arbitrate([
        _interest("SFW", 0.80, score=3),
        _interest("BIM", 0.80, score=9),
    ], now=NOW)
    assert r.outcome == "review_branch_disabled", (
        "an exact cross-bucket confidence tie must be treated as ambiguous, "
        "not silently resolved on ICP score")
    assert not r.may_send


def test_ordering_is_configurable(monkeypatch):
    """Ordering is policy, not a constant. Must be changeable without code."""
    monkeypatch.setenv("ARBITRATION_ORDERING", "score:desc")
    monkeypatch.setattr(arb, "ORDERING", arb._parse_ordering())
    try:
        r = arb.arbitrate([
            _interest("SFW", 0.99, score=1),
            _interest("BIM", 0.10, score=99),
        ], now=NOW)
        assert r.winner == "BIM", "score-first ordering was not honoured"
    finally:
        monkeypatch.setattr(arb, "ORDERING", arb._DEFAULT_ORDERING)


def test_missing_confidence_never_outranks_a_present_one():
    r = arb.arbitrate([_interest("SFW", None), _interest("BIM", 0.30)], now=NOW)
    assert r.winner == "BIM"


def test_no_bucket_is_a_recorded_reason_not_a_silent_drop():
    r = arb.arbitrate([{"icp_id": "sfw", "bucket": None, "score": 9}], now=NOW)
    assert r.outcome == "no_bucket"
    assert not r.may_send


# ===========================================================================
# Cooldown — global, never scoped by entity
# ===========================================================================

def test_recent_contact_by_another_entity_blocks():
    person = {"last_contacted_at": NOW - timedelta(days=30),
              "last_contacted_by_entity": "SFW"}
    r = arb.arbitrate([_interest("BIM", 0.9)], person=person, now=NOW)
    assert r.outcome == "cooldown_block"
    assert not r.may_send
    assert "SFW" in r.detail


def test_same_entity_may_follow_up_with_its_own_prospect():
    person = {"last_contacted_at": NOW - timedelta(days=3),
              "last_contacted_by_entity": "SFW"}
    r = arb.arbitrate([_interest("SFW", 0.9)], person=person, now=NOW)
    assert r.may_send


def test_cooldown_expires():
    person = {"last_contacted_at": NOW - timedelta(days=120),
              "last_contacted_by_entity": "SFW"}
    r = arb.arbitrate([_interest("BIM", 0.9)], person=person, now=NOW)
    assert r.may_send


def test_dual_fit_33_day_gap_is_blocked():
    """
    The exact shape being killed: basket D scheduled SFW at T+0 and Cogentix
    at T+33d. 33 < 90, so the second entity is blocked.
    """
    person = {"last_contacted_at": NOW - timedelta(days=33),
              "last_contacted_by_entity": "SFW"}
    r = arb.arbitrate([_interest("COGENTIX_RESEARCH", 0.9)], person=person, now=NOW)
    assert r.outcome == "cooldown_block"


# ===========================================================================
# Review branch — written, gated, fails closed
# ===========================================================================

def test_review_branch_is_disabled_by_default():
    """
    A flag defaulting ON with a TODO to find an owner is the deferred 9,747 in
    miniature. It stays off until a human owns the queue.
    """
    assert arb.REVIEW_BRANCH_ENABLED is False


def test_ambiguous_leads_are_blocked_while_the_branch_is_off():
    r = arb.arbitrate([_interest("SFW", 0.72), _interest("COGENTIX_RESEARCH", 0.70)],
                      now=NOW)
    assert r.outcome == "review_branch_disabled"
    assert not r.may_send
    assert r.runner_up == "COGENTIX_RESEARCH"
    assert "no named owner" in r.detail


def test_ambiguous_routes_to_review_when_enabled(monkeypatch):
    monkeypatch.setattr(arb, "REVIEW_BRANCH_ENABLED", True)
    r = arb.arbitrate([_interest("SFW", 0.72), _interest("COGENTIX_RESEARCH", 0.70)],
                      now=NOW, review_queue_depth=10)
    assert r.outcome == "ambiguous_review"
    assert not r.may_send
    assert r.margin == pytest.approx(0.02)


def test_review_queue_fails_closed_at_cap(monkeypatch):
    """
    The cap is an INSTRUMENT, not backpressure. Filling it is the measurement,
    and blocking is the correct output: if we cannot tell which entity should
    contact someone, not contacting them is right.
    """
    monkeypatch.setattr(arb, "REVIEW_BRANCH_ENABLED", True)
    r = arb.arbitrate([_interest("SFW", 0.72), _interest("COGENTIX_RESEARCH", 0.70)],
                      now=NOW, review_queue_depth=arb.REVIEW_QUEUE_CAP)
    assert r.outcome == "blocked_review_capacity"
    assert not r.may_send
    assert "at cap" in r.detail


def test_blocked_review_capacity_is_distinct_from_lost_arbitration():
    """
    Distinct reasons so the cost of the classifier problem shows up in the
    per-entity funnel where someone would act on it, instead of the leads
    vanishing from reporting.
    """
    disabled = arb.arbitrate(
        [_interest("SFW", 0.72), _interest("COGENTIX_RESEARCH", 0.70)], now=NOW)
    lost = arb.arbitrate(
        [_interest("SFW", 0.95), _interest("COGENTIX_RESEARCH", 0.20)], now=NOW)

    assert disabled.outcome == "review_branch_disabled"
    assert lost.outcome == "arbitrated"
    assert lost.losers[0]["reason"] == "lost_arbitration"


def test_disabled_branch_and_full_queue_are_different_reasons(monkeypatch):
    """
    Three distinct states, three distinct remedies, three distinct owners:

        review_branch_disabled   nobody owns the queue    -> name a human
        blocked_review_capacity  queue is full            -> work it / fix the
                                                             classifier
        lost_arbitration         a winner was chosen      -> nothing, working

    Collapsing the first two would point whoever reads the funnel at raising
    a cap that is not the problem.
    """
    off = arb.arbitrate(
        [_interest("SFW", 0.72), _interest("COGENTIX_RESEARCH", 0.70)], now=NOW)
    assert off.outcome == "review_branch_disabled"

    monkeypatch.setattr(arb, "REVIEW_BRANCH_ENABLED", True)
    full = arb.arbitrate(
        [_interest("SFW", 0.72), _interest("COGENTIX_RESEARCH", 0.70)],
        now=NOW, review_queue_depth=arb.REVIEW_QUEUE_CAP)
    assert full.outcome == "blocked_review_capacity"
    assert off.outcome != full.outcome


def test_clear_winner_is_not_sent_to_review():
    r = arb.arbitrate([_interest("SFW", 0.95), _interest("BIM", 0.10)], now=NOW)
    assert r.outcome == "arbitrated"
    assert r.may_send


def test_the_cap_default_is_small_on_purpose():
    """
    500, not 5,000. Sized as an instrument that surfaces the problem
    immediately, not a buffer that absorbs ~11k people silently.
    """
    assert arb.REVIEW_QUEUE_CAP == 500
