"""Shared platform (CRM plan 3.1): config store, Review Queue, escalation ladder, throttle."""
import json
from datetime import datetime, timedelta

import pytest

from tests._fakemongo import FakeDB
from platform_core import config_store, ladder as gw, review_queue as rq


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


# ------------------------------------------------------------ escalation ladder
def test_clean_input_keeps_newest_message_only():
    body = "Please quote India n=500 LOI 15.\n\nRegards,\nAsha\n\nOn Mon, 1 Jan 2026 at 10:00 Bob wrote:\n> old"
    out = gw.clean_input("RFQ", body)
    assert "n=500" in out and "old" not in out and "Asha" not in out and out.startswith("SUBJECT: RFQ")


def _tx(text, calls=None, tin=10, tout=10):
    """A cloud transport: (text, input_tokens, output_tokens), as anthropic_transport returns."""
    def t(*a, **k):
        if calls is not None:
            calls.append(k.get("model"))
        return text, tin, tout
    return t


def _run(dbs, transport, task="reply_classification", **kw):
    return gw.run(task=task, system="Return JSON", subject="s", body="hello", cloud_transport=transport,
                  schema={"type": "object", "required": ["category"]}, db=dbs["gov"],
                  now=datetime(2026, 10, 24, 6, 0), **kw)


def test_accepted_answer_stops_the_ladder_at_haiku(dbs):
    calls = []
    out = _run(dbs, _tx(json.dumps({"category": "positive"}), calls))
    assert out["status"] == "ok" and out["tier"] == "haiku" and len(calls) == 1


def test_invalid_json_on_every_tier_goes_to_review_never_ok(dbs):
    calls = []
    out = _run(dbs, _tx("not json", calls))
    assert out["status"] == "review" and out["review_item"] and len(calls) == 2    # haiku, then sonnet
    assert rq.list_items()[0]["type"] == "ai_invalid_output"


def test_code_check_problems_send_valid_output_to_review(dbs):
    out = _run(dbs, _tx(json.dumps({"category": "rfq"})), code_check=lambda d, t: ["LOI 150 not in mail"])
    assert out["status"] == "review" and "LOI 150" in out["problems"][0]


def test_always_review_task_never_returns_ok(dbs):
    out = gw.run(task="rfq_extraction", system="x", body="RFQ", cloud_transport=_tx(json.dumps({"line_items": []})),
                 db=dbs["gov"], now=datetime(2026, 10, 24, 6, 0))
    assert out["status"] == "review" and out["review_item"]


def test_failing_rung_is_tried_once_then_next_rung_runs(dbs):
    calls = []

    def bad(*a, **k):
        calls.append(k.get("model"))
        raise ValueError("400 exceeds context")          # not an outage: the tier stays on
    out = _run(dbs, bad)
    assert out["status"] == "review" and len(calls) == 2                       # one call per rung, no retry
    assert [a["tier"] for a in out["attempts"]] == ["haiku", "sonnet"]


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
