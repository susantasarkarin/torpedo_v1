"""
PIPELINE HEALTH TESTS

The monitoring has to be trustworthy before it is trusted. Two properties
matter most and are pinned here:

  * a stage at zero alerts WITHOUT having errored (the 2026-08-09 shape)
  * a review queue that looks healthy by depth alerts on AGE
"""

import os
import sys
from datetime import datetime, timedelta

import pytest
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import pipeline_health as ph  # noqa: E402


TEST_DB = "torpedo_test_pipeline_health"
NOW = datetime.utcnow()


@pytest.fixture
def db():
    try:
        c = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"),
                        serverSelectionTimeoutMS=1500)
        c.server_info()
    except ServerSelectionTimeoutError:
        pytest.skip("no mongo reachable")
    c.drop_database(TEST_DB)
    yield c[TEST_DB]
    c.drop_database(TEST_DB)


# ===========================================================================
# Duplicate-send canary — the regression guard for the whole remediation
# ===========================================================================

def test_canary_is_clean_when_one_entity_contacts_a_person(db):
    db.sends.insert_many([
        {"person_fingerprint": "fp1", "entity": "SFW", "sent_at": NOW},
        {"person_fingerprint": "fp1", "entity": "SFW", "sent_at": NOW - timedelta(days=5)},
    ])
    assert ph.canary_violations(db) == []


def test_canary_catches_two_entities_inside_the_cooldown(db):
    """The original bug, recurring. Must never be empty-passed."""
    db.sends.insert_many([
        {"person_fingerprint": "fp1", "entity": "SFW", "sent_at": NOW - timedelta(days=33)},
        {"person_fingerprint": "fp1", "entity": "COGENTIX_RESEARCH", "sent_at": NOW},
    ])
    v = ph.canary_violations(db)
    assert len(v) == 1
    assert v[0]["entities"] == ["COGENTIX_RESEARCH", "SFW"]
    assert v[0]["span_days"] == 33


def test_canary_ignores_two_entities_outside_the_cooldown(db):
    """Beyond 90 days a second brand is permitted; flagging it would cry wolf."""
    db.sends.insert_many([
        {"person_fingerprint": "fp1", "entity": "SFW", "sent_at": NOW - timedelta(days=200)},
        {"person_fingerprint": "fp1", "entity": "BIM", "sent_at": NOW},
    ])
    assert ph.canary_violations(db) == []


def test_canary_does_not_conflate_different_people(db):
    db.sends.insert_many([
        {"person_fingerprint": "fp1", "entity": "SFW", "sent_at": NOW},
        {"person_fingerprint": "fp2", "entity": "BIM", "sent_at": NOW},
    ])
    assert ph.canary_violations(db) == []


# ===========================================================================
# Zero-alerts — must fire without an error having occurred
# ===========================================================================

def test_zero_streak_increments_from_persisted_state(db):
    db.pipeline_health_state.insert_one({"stage": "classify", "zero_streak": 2})
    streaks = ph.zero_streaks(db, {"classify": 0})
    assert streaks["classify"] == 3, "streak must survive a restart"


def test_any_throughput_resets_the_streak(db):
    db.pipeline_health_state.insert_one({"stage": "classify", "zero_streak": 9})
    assert ph.zero_streaks(db, {"classify": 1})["classify"] == 0


def test_silent_zero_alerts_with_no_error_recorded():
    """
    THE 2026-08-09 SHAPE. Classification stopped for a day. Nothing errored
    from the monitoring's point of view — downstream stages simply had nothing
    to do, which is indistinguishable from "no work available".

    The alert must fire on the zero alone.
    """
    rep = ph.HealthReport(
        stage_counts={"classify": 0},
        stage_zero_streaks={"classify": ph.ZERO_CYCLE_ALERT_THRESHOLD},
        runway={}, review_queue={},
    )
    alerts = ph.build_alerts(rep)
    codes = [a.code for a in alerts]
    assert "stage_zero_classify" in codes
    assert any(a.severity == "critical" for a in alerts)


def test_brief_zero_does_not_alert():
    rep = ph.HealthReport(stage_counts={"classify": 0},
                          stage_zero_streaks={"classify": 1},
                          runway={}, review_queue={})
    assert [a for a in ph.build_alerts(rep) if a.code.startswith("stage_zero")] == []


# ===========================================================================
# Runway in days, not a raw count
# ===========================================================================

def test_runway_is_reported_in_days(db):
    db.lead_interests.insert_many([{"bucket": "SFW"} for _ in range(400)])
    r = ph.runway(db, daily_cap=200)
    assert r["eligible_pool"] == 400
    assert r["runway_days"] == 2.0


def test_low_runway_warns_and_short_runway_is_critical():
    warn = ph.build_alerts(ph.HealthReport(
        runway={"runway_days": ph.RUNWAY_WARN_DAYS}, review_queue={}))
    crit = ph.build_alerts(ph.HealthReport(
        runway={"runway_days": ph.RUNWAY_CRITICAL_DAYS}, review_queue={}))
    assert [a.severity for a in warn if a.code == "runway_low"] == ["warning"]
    assert [a.severity for a in crit if a.code == "runway_critical"] == ["critical"]


def test_a_large_pool_that_is_nearly_drained_still_alerts():
    """
    The specific misread this exists to prevent: a cap-bound pipeline shows
    nothing in send rate while the pool drains. 1,000 eligible reads as
    healthy; at a 200/day cap it is 5 days of runway.
    """
    rep = ph.HealthReport(runway={"eligible_pool": 1000, "runway_days": 5.0},
                          review_queue={})
    assert any(a.code == "runway_critical" for a in ph.build_alerts(rep))


# ===========================================================================
# Review queue — depth alone is not enough
# ===========================================================================

def test_shallow_but_stale_queue_alerts():
    """
    Steady depth with nothing older than a day is healthy. Steady depth where
    the oldest item is weeks old is the deferred 9,747 again — a queue nothing
    drains. Depth alone would call this fine.
    """
    rep = ph.HealthReport(
        runway={}, review_queue={"depth": 12,
                                 "oldest_item_age_days": ph.REVIEW_AGE_ALERT_DAYS})
    assert any(a.code == "review_queue_stale" for a in ph.build_alerts(rep))


def test_deep_but_fresh_queue_does_not_alert():
    rep = ph.HealthReport(runway={},
                          review_queue={"depth": 400, "oldest_item_age_days": 1})
    assert [a for a in ph.build_alerts(rep) if a.code == "review_queue_stale"] == []


def test_oldest_age_is_measured_from_the_queue(db):
    db.ai_review_queue.insert_many([
        {"status": "pending", "queued_at": NOW - timedelta(days=40)},
        {"status": "pending", "queued_at": NOW - timedelta(days=1)},
        {"status": "approved", "queued_at": NOW - timedelta(days=99)},
    ])
    state = ph.review_queue_state(db)
    assert state["depth"] == 2, "approved items are not pending"
    assert state["oldest_item_age_days"] == 40


# ===========================================================================
# Funnel + report contract
# ===========================================================================

def test_funnel_preserves_rejection_reasons_per_entity(db):
    db.lead_interests.insert_many([
        {"bucket": "SFW", "outcome_reason": "qualified"},
        {"bucket": "SFW", "outcome_reason": "generic_email"},
        {"bucket": "SFW", "outcome_reason": "generic_email"},
        {"bucket": "BIM", "outcome_reason": "lost_arbitration"},
    ])
    f = ph.funnel(db)
    assert f["SFW"]["generic_email"] == 2
    assert f["SFW"]["qualified"] == 1
    assert f["BIM"]["lost_arbitration"] == 1


def test_report_is_json_serializable_for_alerting():
    rep = ph.HealthReport(runway={"runway_days": 3.0}, review_queue={})
    rep.alerts = ph.build_alerts(rep)
    import json
    payload = json.loads(json.dumps(rep.to_dict(), default=str))
    assert payload["healthy"] is False
    assert payload["alerts"][0]["code"] == "runway_critical"


def test_healthy_report_has_no_alerts_and_no_violations():
    rep = ph.HealthReport(runway={"runway_days": 365.0},
                          review_queue={"depth": 0, "oldest_item_age_days": None},
                          stage_zero_streaks={"send": 0})
    rep.alerts = ph.build_alerts(rep)
    assert rep.healthy
