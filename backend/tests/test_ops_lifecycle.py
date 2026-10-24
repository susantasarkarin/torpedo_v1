"""Operations (CRM plan 3.6): lifecycle, redirects, intents, consolidated mails."""
from datetime import datetime, timedelta

import pytest
from bson import ObjectId

from ops import lifecycle, mails, runner
from ops.lifecycle import DEFAULTS as CFG
from tests._fakemongo import FakeDB

MON = datetime(2026, 10, 26, 12, 30)     # a Monday


def test_legacy_fields_map_to_spec_statuses():
    assert lifecycle.legacy_status({"status": "completed"}) == "closed"
    assert lifecycle.legacy_status({"status": "active", "projectStatus": "live", "actualCompletes": 5}) == "live"
    assert lifecycle.legacy_status({"status": "active"}) == "awaiting_setup"
    assert lifecycle.legacy_status({"invoice_ids": ["x"], "status": "completed"}) == "invoiced"
    assert lifecycle.legacy_status({"lifecycle_status": "paused", "status": "active"}) == "paused"


def test_transition_checks_records_history_and_rejects_skips():
    db = FakeDB()
    pid = db["projects"].insert_one({"lifecycle_status": "live"}).inserted_id
    p = db["projects"].find_one({"_id": pid})
    lifecycle.transition(db["projects"], p, "paused", actor="pm", reason="client hold", now=MON)
    p = db["projects"].find_one({"_id": pid})
    assert p["lifecycle_status"] == "paused" and p["paused_reason"] == "client hold"
    assert p["lifecycle_history"][-1]["from"] == "live"
    with pytest.raises(lifecycle.TransitionError):
        lifecycle.transition(db["projects"], p, "invoiced", actor="pm", reason="skip")


def test_pm_rule_by_bu_and_round_robin():
    assert lifecycle.assign_pm("SFW", {**CFG, "pm_by_bu": {"SFW": "asha"}}, {}) == "asha"
    assert lifecycle.assign_pm("SFW", CFG, {}) is None
    rr = {**CFG, "pm_rule": "round_robin", "pm_round_robin": ["a", "b"]}
    assert lifecycle.assign_pm(None, rr, {"a": 3, "b": 1}) == "b"


def test_redirect_mail_uses_our_past_format():
    body = mails.redirect_mail(mails.redirect_set("https://torpedo.cogentixresearch.com/"))
    assert body.splitlines() == ["Complete Page URL", "https://torpedo.cogentixresearch.com/surveycomplete?rid={RID}",
                                 "Terminate Page URL", "https://torpedo.cogentixresearch.com/surveyterminate?rid={RID}",
                                 "Quota Full Page URL", "https://torpedo.cogentixresearch.com/surveyquotafull?rid={RID}"]


def test_intents_read_only_the_new_part_of_a_reply():
    assert mails.detect_intents("OK, let's do it. Kindly share redirect links.") == ["redirects_requested"]
    assert "test_confirmed" in mails.detect_intents("Test links working fine, please go live")
    quoted = "Thanks\n\nOn Fri, 23 Oct, 2026, 7:03 pm Mike wrote:\n> please cancel"
    assert mails.detect_intents(quoted) == []


def test_soft_launch_variance_against_config():
    p = {"clientIR": 60, "actualIR": 45, "loi": 15, "actualLOI": 20, "totalCompletesRequired": 100, "actualCompletes": 10}
    assert mails.soft_launch_reached(p, CFG)
    v = mails.soft_launch_variance(p, CFG)
    assert len(v) == 2 and "IR 45%" in v[0] and "LOI 20" in v[1]
    assert mails.soft_launch_variance({"clientIR": 60, "actualIR": 55}, CFG) == []


def test_field_update_is_one_mail_per_contact():
    ps = [{"_id": ObjectId(), "projectName": n, "_contact_email": e, "actualCompletes": 1, "totalCompletesRequired": 10}
          for n, e in (("A", "x@c.com"), ("B", "x@c.com"), ("C", "y@c.com"))]
    out = mails.field_updates(ps)
    assert sorted(len(m["project_ids"]) for m in out) == [1, 2]


def test_paused_digest_mondays_only_after_7_days_and_capped():
    old, fresh = MON - timedelta(days=9), MON - timedelta(days=2)
    ps = [{"_id": ObjectId(), "projectName": "A", "_contact_email": "x@c.com", "paused_at": old},
          {"_id": ObjectId(), "projectName": "B", "_contact_email": "x@c.com", "paused_at": fresh},
          {"_id": ObjectId(), "projectName": "C", "_contact_email": "x@c.com", "paused_at": old, "paused_mails_sent": 4}]
    out = mails.paused_digests(ps, MON, CFG)
    assert len(out["mails"]) == 1 and len(out["mails"][0]["project_ids"]) == 1 and len(out["review"]) == 1
    assert mails.paused_digests(ps, MON + timedelta(days=1), CFG) == {"mails": [], "review": []}


def test_reconciliation_request_reminders_then_bill_on_our_count():
    start = MON - timedelta(days=4)
    p = {"_id": ObjectId(), "reconciliation_started_at": start}
    assert mails.reconciliation_step(p, MON, CFG) == "request"
    p["reconciliation_mails"] = ["request"]
    assert mails.reconciliation_step(p, MON, CFG) == "reminder_3"
    p["reconciliation_mails"] += ["reminder_3", "reminder_7"]
    assert mails.reconciliation_step(p, MON, CFG) is None
    assert mails.reconciliation_step(p, start + timedelta(days=15), CFG) == "bill_on_our_count"
    p["reconciliation_ids_received"] = True
    assert mails.reconciliation_step(p, start + timedelta(days=15), CFG) is None


def test_shadow_run_plans_but_changes_nothing(monkeypatch):
    d = {n: FakeDB() for n in ("email_automation", "crm_db")}
    monkeypatch.setattr(runner, "_gd", lambda: (lambda name: d[name]))
    from platform_core import config_store
    monkeypatch.setattr(config_store, "get", lambda s, db=None: config_store.defaults(s))
    pid = d["email_automation"]["projects"].insert_one({"lifecycle_status": "live", "status": "active",
                                                        "actualCompletes": 100, "totalCompletesRequired": 100}).inserted_id
    s = runner.run(now=MON)
    assert s["mode"] == "shadow" and s["moves"] == 1
    assert d["email_automation"]["projects"].find_one({"_id": pid})["lifecycle_status"] == "live"
    assert d["email_automation"]["ops_decisions"].find_one({})["moves"][0]["to"] == "field_closed"
