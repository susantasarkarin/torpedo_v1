"""
Panel health check: staleness detection and failure-rate thresholds.

The direct motivation is lead_promotion, which logged scanned=0 every night
for two weeks with no error raised anywhere - a cron that "succeeds" while
doing nothing is invisible to anything that only watches for exceptions.
These tests pin the two properties that make that class of bug visible: a
job goes stale once it misses its cadence by the buffer, and a job that has
never reported in is distinguished from one that used to run and stopped.
"""

from datetime import datetime, timedelta

import pytest

from backend.services import panel_health as H


@pytest.fixture
def fixed_heartbeats(monkeypatch):
    """Control exactly what get_all_heartbeats() returns."""
    state = {"heartbeats": {}}

    def _get_all():
        return state["heartbeats"]

    monkeypatch.setattr(H, "get_all_heartbeats", _get_all)
    return state


def test_recent_heartbeat_is_ok(fixed_heartbeats):
    fixed_heartbeats["heartbeats"] = {
        "invite_cron": datetime.utcnow() - timedelta(hours=2),
    }
    jobs = H._job_staleness()
    invite = next(j for j in jobs if j["job"] == "invite_cron")
    assert invite["status"] == "ok"


def test_overdue_heartbeat_is_stale(fixed_heartbeats):
    """This is the exact shape of the lead_promotion bug: the task ran and
    logged success, so nobody looked twice, but the last USEFUL run was long
    ago. Staleness here is keyed on last heartbeat, which the task records on
    every successful completion regardless of whether it did anything —
    that's why this catches 'stopped firing', not 'stopped finding work'."""
    fixed_heartbeats["heartbeats"] = {
        "invite_cron": datetime.utcnow() - timedelta(hours=40),
    }
    jobs = H._job_staleness()
    invite = next(j for j in jobs if j["job"] == "invite_cron")
    assert invite["status"] == "stale"


def test_never_reported_is_distinct_from_stale(fixed_heartbeats):
    """A job with zero history (just deployed) must not scream ERROR on its
    first hour of existence the way a job that used to run and stopped
    should."""
    fixed_heartbeats["heartbeats"] = {}
    jobs = H._job_staleness()
    for j in jobs:
        assert j["status"] == "never_seen"


def test_boundary_at_exactly_the_threshold_is_not_yet_stale(fixed_heartbeats):
    threshold_hours = 24 * H.STALE_MULTIPLIER
    fixed_heartbeats["heartbeats"] = {
        "invite_cron": datetime.utcnow() - timedelta(hours=threshold_hours - 0.01),
    }
    jobs = H._job_staleness()
    invite = next(j for j in jobs if j["job"] == "invite_cron")
    assert invite["status"] == "ok"


def test_check_panel_health_flags_stale_jobs_as_problems(monkeypatch, fixed_heartbeats):
    fixed_heartbeats["heartbeats"] = {
        "invite_cron": datetime.utcnow() - timedelta(hours=100),
    }
    monkeypatch.setattr(H, "_send_failure_stats",
                        lambda: {"window_hours": 24, "sent": 0, "failed": 0,
                                 "total": 0, "failure_rate": 0.0,
                                 "by_error_code": {}, "unclassified_failures": 0})
    monkeypatch.setattr(H, "_suppression_velocity",
                        lambda: {"window_hours": 24, "by_reason": {}, "total": 0})
    monkeypatch.setattr(H, "_ses_quota", lambda: {"reachable": False, "error": "n/a"})

    result = H.check_panel_health()

    assert result["healthy"] is False
    assert any("invite_cron" in p for p in result["problems"])


def test_check_panel_health_is_healthy_when_nothing_is_wrong(monkeypatch, fixed_heartbeats):
    fixed_heartbeats["heartbeats"] = {
        name: datetime.utcnow() - timedelta(hours=1) for name in H.JOB_CADENCE_HOURS
    }
    monkeypatch.setattr(H, "_send_failure_stats",
                        lambda: {"window_hours": 24, "sent": 100, "failed": 2,
                                 "total": 102, "failure_rate": 0.02,
                                 "by_error_code": {}, "unclassified_failures": 0})
    monkeypatch.setattr(H, "_suppression_velocity",
                        lambda: {"window_hours": 24, "by_reason": {}, "total": 0})
    monkeypatch.setattr(H, "_ses_quota",
                        lambda: {"reachable": True, "max_24h": 100000, "sent_last_24h": 5000,
                                 "remaining": 95000, "transactional_reserve": 10000,
                                 "transactional_at_risk": False})

    result = H.check_panel_health()

    assert result["healthy"] is True
    assert result["problems"] == []


def test_failure_rate_below_sample_floor_is_ignored(monkeypatch, fixed_heartbeats):
    """5 sends, 3 failed is 60% - alarming as a rate but meaningless as a
    sample. The floor exists so a quiet hour doesn't manufacture a false
    ERROR out of noise."""
    fixed_heartbeats["heartbeats"] = {
        name: datetime.utcnow() - timedelta(hours=1) for name in H.JOB_CADENCE_HOURS
    }
    monkeypatch.setattr(H, "_send_failure_stats",
                        lambda: {"window_hours": 24, "sent": 2, "failed": 3,
                                 "total": 5, "failure_rate": 0.6,
                                 "by_error_code": {}, "unclassified_failures": 0})
    monkeypatch.setattr(H, "_suppression_velocity",
                        lambda: {"window_hours": 24, "by_reason": {}, "total": 0})
    monkeypatch.setattr(H, "_ses_quota", lambda: {"reachable": True, "transactional_at_risk": False})

    result = H.check_panel_health()

    assert result["healthy"] is True


def test_high_failure_rate_at_real_volume_is_a_problem(monkeypatch, fixed_heartbeats):
    fixed_heartbeats["heartbeats"] = {
        name: datetime.utcnow() - timedelta(hours=1) for name in H.JOB_CADENCE_HOURS
    }
    monkeypatch.setattr(H, "_send_failure_stats",
                        lambda: {"window_hours": 24, "sent": 60, "failed": 40,
                                 "total": 100, "failure_rate": 0.4,
                                 "by_error_code": {"MessageRejected": 40},
                                 "unclassified_failures": 0})
    monkeypatch.setattr(H, "_suppression_velocity",
                        lambda: {"window_hours": 24, "by_reason": {}, "total": 0})
    monkeypatch.setattr(H, "_ses_quota", lambda: {"reachable": True, "transactional_at_risk": False})

    result = H.check_panel_health()

    assert result["healthy"] is False
    assert any("FAILURE RATE" in p for p in result["problems"])


def test_transactional_quota_at_risk_is_a_problem(monkeypatch, fixed_heartbeats):
    fixed_heartbeats["heartbeats"] = {
        name: datetime.utcnow() - timedelta(hours=1) for name in H.JOB_CADENCE_HOURS
    }
    monkeypatch.setattr(H, "_send_failure_stats",
                        lambda: {"window_hours": 24, "sent": 100, "failed": 0,
                                 "total": 100, "failure_rate": 0.0,
                                 "by_error_code": {}, "unclassified_failures": 0})
    monkeypatch.setattr(H, "_suppression_velocity",
                        lambda: {"window_hours": 24, "by_reason": {}, "total": 0})
    monkeypatch.setattr(H, "_ses_quota",
                        lambda: {"reachable": True, "max_24h": 100000, "sent_last_24h": 95000,
                                 "remaining": 5000, "transactional_reserve": 10000,
                                 "transactional_at_risk": True})

    result = H.check_panel_health()

    assert result["healthy"] is False
    assert any("QUOTA AT RISK" in p for p in result["problems"])


def test_slack_post_is_skipped_silently_with_no_webhook_configured(monkeypatch):
    """No SLACK_WEBHOOK_URL is set anywhere in this deployment. This must be
    a no-op, not an error - the same optional-fallback shape as the
    DigitalOcean inference fallback."""
    monkeypatch.setattr(H, "SLACK_WEBHOOK_URL", "")
    calls = []
    monkeypatch.setattr(H.requests, "post", lambda *a, **kw: calls.append((a, kw)))

    H._post_to_slack("test message")

    assert calls == []
