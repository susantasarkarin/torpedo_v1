"""
GATE RESET -- the one-time migration for leads a fixed config problem retired
==============================================================================

Covers leads/gate_reset.py: evaluate_candidates (every send-time check re-run
live, first failure wins) and stage_batches (deterministic, capped daily
staggering). No live Mongo/DNS -- every check is an injected fake.
"""
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads.gate_reset import Candidate, evaluate_candidates, stage_batches


def _checks(**overrides):
    base = dict(
        is_suppressed=lambda e: False,
        is_legacy_bounced=lambda e: False,
        has_own_bounced_send=lambda e: False,
        has_own_reply=lambda e: False,
        live_deliverability_ok=lambda e: (True, ""),
        domain_lifetime_stats=lambda d: (0, 0),
    )
    base.update(overrides)
    return base


def _lead(email="a@corp.com", _id="L1"):
    return {"_id": _id, "email": email}


def test_clean_lead_survives_every_check():
    out = evaluate_candidates([_lead()], **_checks())
    assert out[0].clean
    assert out[0].held_reason is None


@pytest.mark.parametrize("field,value,expect_substr", [
    ("is_suppressed", True, "suppression"),
    ("is_legacy_bounced", True, "legacy"),
    ("has_own_bounced_send", True, "bounced before"),
    ("has_own_reply", True, "replied"),
])
def test_each_check_holds_the_lead_with_its_own_reason(field, value, expect_substr):
    out = evaluate_candidates([_lead()], **_checks(**{field: lambda e: value}))
    assert not out[0].clean
    assert expect_substr in out[0].held_reason


def test_live_deliverability_failure_is_held_with_the_real_reason():
    out = evaluate_candidates([_lead()], **_checks(
        live_deliverability_ok=lambda e: (False, "no_mx_records")))
    assert not out[0].clean
    assert "no_mx_records" in out[0].held_reason


def test_missing_or_malformed_email_is_held_before_any_check_runs():
    calls = []
    out = evaluate_candidates([_lead(email="")], **_checks(
        is_suppressed=lambda e: calls.append(e) or False))
    assert not out[0].clean
    assert calls == []            # never even asked


def test_risky_domain_needs_both_thresholds():
    # 4 sends, 100% bounced -- below the minimum sample size, must NOT hold
    ok = evaluate_candidates([_lead()], **_checks(domain_lifetime_stats=lambda d: (4, 4)))
    assert ok[0].clean
    # 5 sends, 30% bounced -- meets both thresholds, must hold
    held = evaluate_candidates([_lead()], **_checks(domain_lifetime_stats=lambda d: (10, 3)))
    assert not held[0].clean
    assert "bounce rate" in held[0].held_reason


def test_risky_domain_just_under_threshold_is_clean():
    out = evaluate_candidates([_lead()], **_checks(domain_lifetime_stats=lambda d: (10, 2)))
    assert out[0].clean       # 20% < 30%


def test_checks_run_cheapest_first_and_short_circuit():
    """A suppressed lead must never pay for a live deliverability call."""
    called = []
    evaluate_candidates([_lead()], **_checks(
        is_suppressed=lambda e: True,
        live_deliverability_ok=lambda e: called.append(e) or (True, "")))
    assert called == []


# ----------------------------------------------------------------- batching

def test_stage_batches_caps_per_day_and_preserves_order():
    clean = [Candidate(f"L{i}", f"a{i}@x.com") for i in range(7)]
    start = datetime(2026, 10, 1)
    staged = stage_batches(clean, daily_cap=3, start=start)
    assert [s[1] for s in staged] == (
        [start] * 3 + [start + timedelta(days=1)] * 3 + [start + timedelta(days=2)])
    assert [s[0].lead_id for s in staged] == [c.lead_id for c in clean]


def test_stage_batches_is_deterministic_across_runs():
    clean = [Candidate(f"L{i}", f"a{i}@x.com") for i in range(10)]
    a = stage_batches(clean, daily_cap=4)
    b = stage_batches(clean, daily_cap=4)
    # can't compare "now" defaults directly across two calls, so compare offsets
    assert [(c.lead_id, t - a[0][1]) for c, t in a] == [(c.lead_id, t - b[0][1]) for c, t in b]


def test_stage_batches_rejects_non_positive_cap():
    with pytest.raises(ValueError):
        stage_batches([Candidate("L1", "a@x.com")], daily_cap=0)


def test_empty_input_produces_empty_schedule():
    assert stage_batches([], daily_cap=25) == []


# ------------------------------------------------------------------ apply_reset

def test_apply_reset_dry_run_writes_nothing():
    from unittest.mock import MagicMock
    from leads.gate_reset import apply_reset
    db = MagicMock()
    staged = [(Candidate("L1", "a@x.com"), datetime(2026, 10, 1))]
    result = apply_reset(db, staged, dry_run=True)
    assert result == {"would_reset": 1, "applied": 0}
    db["outreach_leads_v2"].update_one.assert_not_called()


def test_apply_reset_writes_workflow_status_and_clears_error():
    from unittest.mock import MagicMock
    from leads.gate_reset import apply_reset
    db = MagicMock()
    db["outreach_leads_v2"].update_one.return_value.modified_count = 1
    when = datetime(2026, 10, 1)
    staged = [(Candidate("L1", "a@x.com"), when)]
    result = apply_reset(db, staged, dry_run=False)
    assert result == {"would_reset": 1, "applied": 1}
    flt, update = db["outreach_leads_v2"].update_one.call_args.args
    assert flt == {"_id": "L1"}
    assert update["$set"]["workflow_status"] == "in_sequence"
    assert update["$set"]["next_send_at"] == when
    assert update["$unset"] == {"last_send_error": ""}
