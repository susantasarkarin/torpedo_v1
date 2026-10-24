"""CRM plan 3.3: link -> sender -> category -> actions."""
import re
from datetime import datetime

import pytest

from tests._fakemongo import FakeDB
from mail_pipeline import pipeline as p

PATTERNS = (re.compile(r"mailer-daemon|postmaster", re.I), re.compile(r"undeliverable|delivery status", re.I),
            re.compile(r"out of (the )?office|automatic reply", re.I))
NOW = datetime(2026, 10, 24, 10, 0)


class Ctx:
    def __init__(self, roles=None):
        self.roles = roles or {}

    def role(self, sender, thread):
        return self.roles.get(sender.split("@")[1])


@pytest.fixture
def db():
    d = FakeDB()
    return {k: d[k] for k in ("outreach_sends", "vendor_bids", "threads", "opportunities", "leads", "contacts", "accounts")}


def msg(**kw):
    base = {"_id": "m1", "subject": "Re: Fieldwork in India", "body_plain": "", "from_email": "raj@acme.com",
            "to_emails": ["in@surveyfieldwork.com"], "gmail_thread_id": "t1", "timestamp": NOW}
    base.update(kw)
    return base


def no_model(**kw):
    raise AssertionError("model must not be called when a rule decides")


# -------------------------------------------------------------------- link
def test_link_by_reference_id_then_thread(db):
    db["outreach_sends"].insert_one({"ref_id": "L-3D1352", "outreach_lead_id": "ol1", "gmail_thread_id": "t9"})
    assert p.link(msg(subject="Re: Hello [L-3D1352]", gmail_thread_id="zz"), db)["outreach_lead_id"] == "ol1"
    assert p.link(msg(subject="Re: Hello", gmail_thread_id="t9"), db)["how"] == "thread"
    assert p.link(msg(subject="Re: Hello", gmail_thread_id="none"), db)["type"] is None


# ------------------------------------------------------------------ sender
def test_internal_when_own_domain_and_all_recipients_internal(db):
    s = p.sender_type(msg(from_email="a@cogentixresearch.com", to_emails=["b@surveyfieldwork.com"]), {}, Ctx(), db)
    assert s["type"] == "internal"


def test_vendor_rfq_is_not_a_client(db):
    s = p.sender_type(msg(from_email="bids@cint.com"), {"type": None}, Ctx({"cint.com": "vendor"}), db)
    assert s["type"] == "vendor"
    cat = p.categorize(msg(body_plain="Please quote: n=500, LOI 15, IR 40%", from_email="bids@cint.com"), s, no_model, PATTERNS)
    assert cat["category"] != "rfq"       # only client mail can create a client RFQ


def test_client_by_account_domain(db):
    db["accounts"].insert_one({"domain": "acme.com", "status": None})
    assert p.sender_type(msg(), {"type": None}, Ctx(), db)["type"] == "client"


def test_unknown_sender_goes_to_model_and_review_when_not_ok(db):
    s = p.sender_type(msg(from_email="x@unknown.io"), {"type": None}, Ctx(), db,
                      model=lambda **k: {"status": "review", "review_item": "r1"})
    assert s["type"] == "unknown" and s["review_item"] == "r1"


# ---------------------------------------------------------------- category
CLIENT = {"type": "client", "how": "t"}


def test_hard_bounce_suppresses_and_queues_skrapp():
    m = msg(from_email="mailer-daemon@google.com", subject="Delivery Status Notification (Failure)",
            body_plain="Final-Recipient: rfc822; jane@acme.com\nStatus: 5.1.1")
    cat = p.categorize(m, CLIENT, no_model, PATTERNS)
    acts = {a["type"] for a in p.plan_actions(m, {}, CLIENT, cat)}
    assert cat["bounce"]["kind"] == "hard" and {"skrapp_refind", "suppress"} <= acts


def test_ooo_pauses_until_return_plus_one_working_day():
    m = msg(subject="Automatic reply: Fieldwork", body_plain="I am out of the office until 30 October.")
    cat = p.categorize(m, CLIENT, no_model, PATTERNS)
    acts = p.plan_actions(m, {"outreach_lead_id": "ol1"}, CLIENT, cat)
    assert cat["return_date"] == "2026-10-30"
    assert acts[0]["type"] == "pause_sequence" and acts[0]["until"] == "2026-11-02"     # Fri -> Mon


def test_negative_dnd_and_company_wide():
    m = msg(body_plain="We are not interested, please remove me from your list.")
    cat = p.categorize(m, CLIENT, no_model, PATTERNS)
    acts = {a["type"] for a in p.plan_actions(m, {"outreach_lead_id": "ol1"}, CLIENT, cat)}
    assert cat["category"] == "negative" and {"stop_sequence", "suppress", "account_dnd"} <= acts


def test_transfer_and_reconnect():
    t = p.categorize(msg(body_plain="I'm not the right person, please contact priya@acme.com"), CLIENT, no_model, PATTERNS)
    assert t["neutral_subtype"] == "transferred" and t["transfer_to"] == "priya@acme.com"
    r = p.categorize(msg(body_plain="Busy now. Please reach out in 2 weeks."), CLIENT, no_model, PATTERNS)
    assert r["neutral_subtype"] == "reconnect_later" and r["follow_up_on"] == "2026-11-07"


def test_rfq_confirmation_redirect_events_for_clients():
    for body, cat_name, event in (("Please quote: India n=400, LOI 20, IR 25%", "rfq", "rfq_received"),
                                  ("Please go ahead, PO attached.", "confirmation", "rfq_confirmed"),
                                  ("Kindly share the redirect links.", "redirect_request", "redirect_requested")):
        m = msg(body_plain=body)
        cat = p.categorize(m, CLIENT, no_model, PATTERNS)
        assert cat["category"] == cat_name
        assert any(a.get("event") == event for a in p.plan_actions(m, {}, CLIENT, cat))


def test_model_rfq_without_spec_is_checked_and_not_acted_on():
    seen = {}

    def model(**kw):
        seen["problems"] = kw["code_check"]({"category": "rfq"}, "")
        return {"status": "review", "review_item": "r9"}
    cat = p.categorize(msg(body_plain="Hmm, interesting idea, tell me more about yourselves"), CLIENT, model, PATTERNS)
    assert "no spec" in seen["problems"][0] and cat["category"] == "other" and cat["review_item"] == "r9"


def test_positive_goes_to_review_with_a_draft_not_sent():
    m = msg(body_plain="Yes, please send your panel book and pricing.")
    cat = p.categorize(m, CLIENT, no_model, PATTERNS)
    acts = p.plan_actions(m, {}, CLIENT, cat)
    assert cat["category"] == "positive" and acts[-1]["review_type"] == "positive_reply_draft"


def test_runner_shadow_records_decisions_and_applies_nothing(monkeypatch):
    from mail_pipeline import runner
    dbs = {n: FakeDB() for n in ("torpedo_settings", "email_automation", "torpedo_gmail", "torpedo", "crm_db")}
    dbs["torpedo_gmail"]["email_metadata"].insert_one(
        {"_id": "m7", "direction": "inbound", "timestamp": NOW, "subject": "Re: hi", "from_email": "raj@acme.com",
         "to_emails": ["in@surveyfieldwork.com"], "body_plain": "We are not interested, please remove me."})
    monkeypatch.setattr(runner, "_client", lambda: (lambda name: dbs[name]))
    monkeypatch.setattr(runner, "_context", lambda: Ctx())
    monkeypatch.setattr(runner, "_bounce_patterns", lambda: PATTERNS)
    class _NoModel:
        used = 0

        def __init__(self, cap):
            pass

        def __call__(self, **kw):
            return {"status": "deferred"}
    monkeypatch.setattr(runner, "_CappedModel", _NoModel)
    applied = []
    monkeypatch.setattr(runner, "apply_actions", lambda d, gd: applied.append(d) or [])
    stats = runner.run_batch(now=NOW)
    assert stats["decided"] == 1 and stats["mode"] == "shadow" and applied == []
    d = dbs["email_automation"]["mail_decisions"].find_one({"message_id": "m7"})
    assert d["category"]["category"] == "negative" and any(a["type"] == "suppress" for a in d["actions"])
    assert runner.run_batch(now=NOW)["decided"] == 0          # never decided twice
