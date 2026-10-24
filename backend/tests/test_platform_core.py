"""Shared platform (CRM plan 3.1): config store, Review Queue, Qwen gateway, throttle."""
import json
from datetime import datetime, timedelta

import pytest

from tests._fakemongo import FakeDB
from platform_core import config_store, qwen_gateway as gw, review_queue as rq


@pytest.fixture
def dbs(monkeypatch):
    settings, email_db, gov, crm = FakeDB(), FakeDB(), FakeDB(), FakeDB()
    monkeypatch.setattr(config_store, "_db", lambda: settings)
    monkeypatch.setattr(rq, "_db", lambda name="email_automation": gov if name == "ai_governance" else email_db)
    import platform_core.audit as audit
    monkeypatch.setattr(audit, "_db", lambda: crm)
    return {"settings": settings, "email": email_db, "gov": gov, "crm": crm}


# ----------------------------------------------------------------- config
def test_config_defaults_and_override_and_unknown_key(dbs):
    assert config_store.get("pricing")["markup"]["SFW"] == 1.5
    config_store.set("pricing", {"margin_floor": 0.35}, actor="owner")
    assert config_store.get("pricing")["margin_floor"] == 0.35
    assert config_store.get("pricing")["markup"]["COGENTIX"] == 1.6        # untouched keys keep defaults
    with pytest.raises(ValueError):
        config_store.set("pricing", {"nonsense": 1}, actor="owner")
    assert dbs["crm"]["audit_log"].count_documents({"entity_type": "config"}) == 1


def test_entities_blank_by_default_never_inferred(dbs):
    ent = config_store.get("entities")
    assert ent["SFW"]["gstin"] == "" and ent["BIM"]["invoice_prefix"] == "BIM"


# ----------------------------------------------------------- review queue
def test_enqueue_is_idempotent_per_type_and_ref(dbs):
    a = rq.enqueue(type="entity_link", module="linking", ref={"collection": "crm_db.accounts", "id": "x1"}, reason="fuzzy 0.8")
    b = rq.enqueue(type="entity_link", module="linking", ref={"collection": "crm_db.accounts", "id": "x1"}, reason="again")
    assert a == b and len(rq.list_items()) == 1


def test_approve_resumes_the_workflow_and_correct_saves_a_labelled_example(dbs):
    seen = []
    rq.register_handler("test:resume", lambda item, decision: seen.append(decision["value"]) or "done")
    i1 = rq.enqueue(type="rfq_extraction", module="rfq", ref={"collection": "c", "id": "1"}, reason="review",
                    suggested={"n": 100}, payload={"task": "rfq_extraction", "clean_input": "N=100"},
                    resume={"handler": "test:resume"})
    out = rq.resolve(i1, "correct", actor="owner", correction={"n": 150})
    assert out["ok"] and out["resumed"] == "done" and seen == [{"n": 150}]
    assert dbs["gov"]["labelled_examples"].count_documents({"task": "rfq_extraction"}) == 1
    assert rq.resolve(i1, "approve", actor="owner")["ok"] is False             # already decided


def test_reject_does_not_resume(dbs):
    seen = []
    rq.register_handler("test:r2", lambda item, decision: seen.append(1))
    i = rq.enqueue(type="other", module="m", ref={"collection": "c", "id": "2"}, reason="r", resume={"handler": "test:r2"})
    assert rq.resolve(i, "reject", actor="owner")["status"] == "rejected" and seen == []


# ------------------------------------------------------------ qwen gateway
def test_clean_input_keeps_newest_message_only():
    body = "Please quote India n=500 LOI 15.\n\nRegards,\nAsha\n\nOn Mon, 1 Jan 2026 at 10:00 Bob wrote:\n> old"
    out = gw.clean_input("RFQ", body)
    assert "n=500" in out and "old" not in out and "Asha" not in out and out.startswith("SUBJECT: RFQ")


def test_p3_runs_only_at_night():
    assert gw.in_p3_window(datetime(2026, 10, 24, 17, 0)) is True      # 22:30 IST
    assert gw.in_p3_window(datetime(2026, 10, 24, 6, 0)) is False      # 11:30 IST


def _run(dbs, transport, task="reply_classification", **kw):
    return gw.run(task=task, system="Return JSON", subject="s", body="hello", transport=transport,
                  schema={"type": "object", "required": ["category"]}, db=dbs["gov"],
                  now=datetime(2026, 10, 24, 6, 0), sleep=lambda s: None, **kw)


def test_ok_result_is_cached_by_content_hash(dbs):
    calls = []
    t = lambda *a, **k: calls.append(1) or json.dumps({"category": "positive"})
    assert _run(dbs, t)["status"] == "ok"
    again = _run(dbs, t)
    assert again["cached"] is True and len(calls) == 1


def test_invalid_json_twice_goes_to_review_never_ok(dbs):
    out = _run(dbs, lambda *a, **k: "not json")
    assert out["status"] == "review" and out["review_item"]
    assert rq.list_items()[0]["type"] == "ai_invalid_output"


def test_code_check_problems_send_valid_output_to_review(dbs):
    out = _run(dbs, lambda *a, **k: json.dumps({"category": "rfq"}), code_check=lambda d, t: ["LOI 150 not in mail"])
    assert out["status"] == "review" and "LOI 150" in out["problems"][0]


def test_always_review_task_never_returns_ok(dbs):
    t = lambda *a, **k: json.dumps({"line_items": []})
    out = gw.run(task="rfq_extraction", system="x", body="RFQ", transport=t, db=dbs["gov"],
                 now=datetime(2026, 10, 24, 6, 0), sleep=lambda s: None)
    assert out["status"] == "review"


def test_transport_failure_retries_then_records_failed_job(dbs):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise TimeoutError("slow")
    out = _run(dbs, boom)
    assert out["status"] == "failed" and len(calls) == 4                    # 1 + 3 retries
    assert gw.failed_jobs(db=dbs["gov"])[0]["task"] == "reply_classification"


def test_client_error_is_not_retried(dbs):
    import requests
    calls = []

    def bad(*a, **k):
        calls.append(1)
        resp = requests.Response()
        resp.status_code = 400
        raise requests.HTTPError("400 exceeds context", response=resp)
    out = _run(dbs, bad)
    assert out["status"] == "failed" and len(calls) == 1


def test_small_model_tasks_get_a_smaller_input_budget(dbs):
    seen = []

    def t(model, system, user, *a, **k):
        seen.append(user)
        return json.dumps({"category": "other", "confidence": 0.9})
    gw.run(task="reply_classification", system="Return JSON", body="x " * 5000, transport=t,
           schema={"type": "object", "required": ["category"]}, db=dbs["gov"], now=datetime(2026, 10, 24, 6, 0), sleep=lambda s: None)
    assert len(seen[0]) <= 2600


def test_p3_task_deferred_in_daytime(dbs):
    out = gw.run(task="lead_bucketing", system="x", body="Acme", transport=lambda *a, **k: "{}",
                 db=dbs["gov"], now=datetime(2026, 10, 24, 6, 0))
    assert out["status"] == "deferred"


# ----------------------------------------------------------------- throttle
@pytest.mark.live_send_state
def test_throttle_one_automated_mail_per_contact_per_day(monkeypatch):
    from messaging import facade
    sent = FakeDB()["email_send_log"]
    monkeypatch.setattr(facade._log, "_col", lambda: sent)
    monkeypatch.setattr(facade, "_throttle_settings", lambda: (1, ("outreach", "finance")))
    assert facade._throttle_block("a@kantar.com", "outreach") is None
    sent.insert_one({"to_email": "a@kantar.com", "status": "sent", "channel": "finance",
                     "sent_at": datetime.utcnow() - timedelta(hours=2)})
    assert "already received" in facade._throttle_block("a@kantar.com", "outreach")
    assert facade._throttle_block("a@kantar.com", "manual") is None          # a person's own mail is never throttled
