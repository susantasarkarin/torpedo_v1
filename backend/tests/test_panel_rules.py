"""Panel rules (CRM plan 3.7b): feasibility, exclusions, waves, quality, incentives, privacy."""
from datetime import datetime, timedelta

from panel_rules import rules
from panel_rules.rules import DEFAULTS as CFG

NOW = datetime(2026, 10, 24, 12, 0)


def _m(i, country="IN", status="active", **kw):
    return {"_id": f"m{i}", "country": country, "status": status, "double_opt_in": True, **kw}


def test_feasibility_is_members_x_response_rate_x_ir():
    members = [_m(1, profile={"gender": "F"}), _m(2, profile={"gender": "M"}), _m(3, country="US"), _m(4, status="inactive")]
    inv = {"m1": [{"sent_at": NOW - timedelta(days=5), "started": True}, {"sent_at": NOW - timedelta(days=6)}],
           "m2": [{"sent_at": NOW - timedelta(days=5), "started": True}, {"sent_at": NOW - timedelta(days=200), "started": True}]}
    f = rules.feasibility(members, country="in", ir_percent=50, invites_by_member=inv, now=NOW)
    assert f["matching_active"] == 2 and f["expected_starts"] == 1.5 and f["feasible_completes"] == 0
    fq = rules.feasibility(members, country="IN", ir_percent=100, invites_by_member=inv, now=NOW, quota={"gender": "M"})
    assert fq["matching_active"] == 1 and fq["feasible_completes"] == 1


def test_invite_exclusions():
    m = _m(1)
    week = [{"sent_at": NOW - timedelta(days=d)} for d in (1, 2, 3)]
    assert "invites in the last 7 days" in rules.invite_exclusion(m, week, None, NOW)
    cat = [{"sent_at": NOW - timedelta(days=20), "category": "auto"}]
    assert "same category" in rules.invite_exclusion(m, cat, "auto", NOW)
    assert rules.invite_exclusion(m, cat, "fmcg", NOW) is None
    assert rules.invite_exclusion({**m, "double_opt_in": False}, [], None, NOW) == "no double opt-in"


def test_next_wave_tops_up_from_actual_ir_and_is_capped():
    assert rules.next_wave(target=100, completes=40, ir_percent=50, response=0.2, pending_invites=100, eligible=10000) == 620
    assert rules.next_wave(target=100, completes=40, ir_percent=50, response=0.2, pending_invites=0, eligible=1000) == 250
    assert rules.next_wave(target=100, completes=100, ir_percent=50, response=0.2, pending_invites=0, eligible=1000) == 0


def test_reminder_once_after_24h():
    i = {"sent_at": NOW - timedelta(hours=25)}
    assert rules.reminder_due(i, NOW) and not rules.reminder_due({**i, "reminded_at": NOW}, NOW)
    assert not rules.reminder_due({"sent_at": NOW - timedelta(hours=2)}, NOW)


def test_quality_flags():
    seen = {}
    a = {"member_id": "m1", "fingerprint": "f1", "ip": "1.1.1.1", "country": "IN", "ip_country": "IN", "loi_minutes": 12}
    assert rules.quality_flags(a, median_loi=12, seen=seen) == []
    b = {"member_id": "m2", "fingerprint": "f1", "ip": "1.1.1.1", "country": "IN", "ip_country": "US", "loi_minutes": 3,
         "grids": [[3, 3, 3, 3, 3]], "open_ends": ["asdf"]}
    flags = rules.quality_flags(b, median_loi=12, seen=seen)
    assert set(flags) == {"duplicate device", "duplicate ip", "IP country US vs IN", "speeder", "straight-lining", "junk open-end"}


def test_suspension_is_flag_only_until_enforced():
    low = {"quality_score": 10}
    assert rules.suspend(low) == {"suspend": False, "flag": True, "reason": "quality score below 30"}
    assert rules.suspend(low, {**CFG, "enforce_quality": True})["suspend"]
    assert not rules.suspend({})["flag"]


def test_incentive_only_after_client_reconciliation():
    c = {"rid": "R1"}
    assert rules.incentive_status(c, None) == "pending_reconciliation"
    assert rules.incentive_status(c, {"received": True, "accepted": ["R1"]}) == "confirmed"
    assert rules.incentive_status(c, {"received": True, "rejected": ["R1"]}) == "rejected"
    assert rules.project_incentive_cost([{"incentive": 50, "incentive_status": "confirmed"},
                                         {"incentive": 50, "incentive_status": "pending_reconciliation"}]) == 50


def test_redemption_fraud_checks():
    m = {"confirmed_balance": 100, "quality_flags": ["speeder"]}
    probs = rules.redemption_check(m, {"amount": 150}, [{"at": NOW - timedelta(days=d)} for d in (1, 5, 9)], NOW)
    assert len(probs) == 3


def test_erasure_blanks_pii_and_never_deletes():
    upd = rules.erasure_update({"_id": "m1", "email": "x", "phone": "y", "country": "IN"}, NOW, "req1")
    assert upd["$set"]["email"] is None and upd["$set"]["phone"] is None and "country" not in upd["$set"]
    assert upd["$set"]["status"] == "erased" and upd["$set"]["suppressed"] is True


def test_panel_book_per_bu():
    b = rules.panel_book({"active_by_country": {"IN": 900, "US": 100}, "response_rate_90d": 0.12}, "SFW", "2026-10")
    assert b["active_members"] == 1000 and b["countries"][0] == {"country": "IN", "active": 900}
