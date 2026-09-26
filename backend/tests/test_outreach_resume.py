"""
A PAUSE HOLDS LEADS AND A RESUME RESTORES THEM
==============================================

Before 2026-09-20 the send loop wrote workflow_status="paused" onto every lead it
touched while the kill switch was on (or the campaign inactive). The send query
selects only not_started / pending_scheduled / in_sequence, so those leads were
never looked at again, and neither "resume campaign" nor
`outreach_kill_switch.py resume` moved them back: resuming silently did nothing
for exactly the leads that had been touched.

Pinned here:
  * the send loop's preflight returns before selecting any lead while paused;
  * the per-lead backstops leave workflow_status alone;
  * restore_paused_leads brings back ONLY exact "paused" leads, and never the
    deliberate lead-specific outcomes (suppressed, bounced, skipped_*, ...);
  * campaign resume and the kill-switch script's resume both call it.
"""
import importlib
import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.outreach_resume import restore_paused_leads


# ---------------------------------------------------------------- fake collection

def _matches(doc, flt):
    for k, cond in flt.items():
        val = doc.get(k)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$in":
                    if val not in arg and not (None in arg and k not in doc):
                        return False
                elif op == "$exists":
                    if (k in doc) != arg:
                        return False
                else:
                    raise NotImplementedError(op)
        elif val != cond:
            return False
    return True


class FakeLeads:
    def __init__(self, docs):
        self.docs = docs

    def update_many(self, flt, update):
        n = 0
        for d in self.docs:
            if _matches(d, flt):
                d.update(update["$set"])
                n += 1
        return MagicMock(modified_count=n)


def _db(docs):
    leads = FakeLeads(docs)
    db = MagicMock()
    db.__getitem__.side_effect = lambda name: leads if name == "outreach_leads_v2" else MagicMock()
    return db


# ---------------------------------------------------------------- restore

def test_restore_brings_back_paused_leads_by_whether_they_were_mailed():
    docs = [
        {"_id": 1, "workflow_status": "paused", "campaign_id": "c1", "current_step": 0},
        {"_id": 2, "workflow_status": "paused", "campaign_id": "c1", "current_step": 3,
         "last_sent_at": "2026-08-21"},
        {"_id": 3, "workflow_status": "paused", "campaign_id": "c1"},   # no current_step at all
    ]
    assert restore_paused_leads(_db(docs)) == 3
    assert docs[0]["workflow_status"] == "not_started"
    assert docs[1]["workflow_status"] == "in_sequence"
    assert docs[2]["workflow_status"] == "not_started"


@pytest.mark.parametrize("status", [
    "paused_duplicate_brand", "suppressed", "bounced", "skipped_gate",
    "skipped_high_bounce_risk", "needs_human_intervention", "completed", "replied",
    "in_sequence", "not_started", "error",
])
def test_restore_never_touches_deliberate_outcomes(status):
    docs = [{"_id": 1, "workflow_status": status, "campaign_id": "c1", "current_step": 2}]
    assert restore_paused_leads(_db(docs)) == 0
    assert docs[0]["workflow_status"] == status


def test_restore_is_scoped_to_one_campaign_when_asked():
    docs = [
        {"_id": 1, "workflow_status": "paused", "campaign_id": "c1", "current_step": 1},
        {"_id": 2, "workflow_status": "paused", "campaign_id": "c2", "current_step": 1},
    ]
    assert restore_paused_leads(_db(docs), campaign_id="c1") == 1
    assert docs[0]["workflow_status"] == "in_sequence"
    assert docs[1]["workflow_status"] == "paused"


def test_restore_failure_never_raises():
    db = MagicMock()
    db.__getitem__.side_effect = RuntimeError("mongo down")
    assert restore_paused_leads(db) == 0


# ---------------------------------------------------------------- send loop

@pytest.fixture
def router(monkeypatch):
    monkeypatch.setenv("OUTREACH_UNSUBSCRIBE_URL", "https://example.test/unsub")
    monkeypatch.setenv("OUTREACH_SENDER_POSTAL_ADDRESS", "1 Test Street, Kolkata")
    import routers.cold_outreach_router as mod
    return importlib.reload(mod)


def _loop_db(kill_doc):
    def _c():
        c = MagicMock()
        c.find_one.return_value = None
        c.count_documents.return_value = 0
        return c
    colls = {n: _c() for n in ("outreach_campaigns_v2", "outreach_leads_v2",
                               "outreach_kill_switch", "outreach_health")}
    colls["outreach_kill_switch"].find_one.return_value = kill_doc
    colls["outreach_campaigns_v2"].find.return_value = [
        {"campaign_id": "c1", "business": "sfw", "mailbox_ids": []}]
    db = MagicMock()
    db.__getitem__.side_effect = lambda n: colls.setdefault(n, _c())
    db.colls = colls
    return db


@pytest.mark.parametrize("kill_doc", [{"_id": "global", "paused": True}, None],
                         ids=["paused", "missing-doc-fails-safe"])
def test_paused_loop_touches_no_lead(router, kill_doc):
    db = _loop_db(kill_doc)
    with patch.object(router, "get_db", return_value=db):
        result = router.process_due_outreach_sends()
    assert result["held"] == "kill switch active"
    leads = db.colls["outreach_leads_v2"]
    leads.find.assert_not_called()
    leads.update_one.assert_not_called()
    leads.update_many.assert_not_called()


def _one_lead(router, kill_doc, campaign):
    lead = {"_id": "L1", "campaign_id": "c1", "email": "a@corp.com", "current_step": 2,
            "workflow_status": "in_sequence"}
    db = _loop_db(kill_doc)
    db.colls["outreach_campaigns_v2"].find_one.return_value = campaign
    router._process_one_outreach_lead(db, lead)
    return [c.args[1]["$set"] for c in db.colls["outreach_leads_v2"].update_one.call_args_list]


def test_per_lead_backstop_kill_switch_leaves_status_alone(router):
    sets = _one_lead(router, {"_id": "global", "paused": True}, {"campaign_id": "c1", "is_active": True})
    assert sets and all("workflow_status" not in s for s in sets)
    assert any("kill switch" in s["last_send_error"] for s in sets)


def test_per_lead_backstop_inactive_campaign_leaves_status_alone(router):
    sets = _one_lead(router, {"_id": "global", "paused": False}, {"campaign_id": "c1", "is_active": False})
    assert sets and all("workflow_status" not in s for s in sets)


def test_sending_disabled_gate_holds_instead_of_parking(router):
    lead = {"_id": "L1", "campaign_id": "c1", "email": "a@corp.com", "current_step": 2}
    db = _loop_db({"_id": "global", "paused": False})
    db.colls["outreach_campaigns_v2"].find_one.return_value = {
        "campaign_id": "c1", "is_active": True, "business": "sfw", "steps": [{}] * 5}
    fake_facade = MagicMock()
    fake_facade.gate.return_value = ("SENDING_ENABLED=false (kill switch active)", "disabled")
    with patch.object(router, "_resolve_sender_for_campaign",
                      return_value={"from_email": "s@corp.com", "display_name": "S", "transport": "gmail_api"}), \
         patch.dict(sys.modules, {"messaging": MagicMock(facade=fake_facade), "messaging.facade": fake_facade}):
        router._process_one_outreach_lead(db, lead)
    sets = [c.args[1]["$set"] for c in db.colls["outreach_leads_v2"].update_one.call_args_list]
    assert sets and all("workflow_status" not in s for s in sets)


# ---------------------------------------------------------------- resume paths

def test_campaign_resume_restores_that_campaigns_paused_leads(router):
    docs = [{"_id": 1, "workflow_status": "paused", "campaign_id": "c1", "current_step": 1},
            {"_id": 2, "workflow_status": "paused", "campaign_id": "c2", "current_step": 1}]
    db = _db(docs)
    db.__getitem__.side_effect = lambda n: FakeLeads(docs) if n == "outreach_leads_v2" else \
        MagicMock(update_one=MagicMock(return_value=MagicMock(matched_count=1)))
    with patch.object(router, "get_db", return_value=db):
        out = router.resume_campaign("c1")
    assert out == {"ok": True, "restored_leads": 1}
    assert docs[0]["workflow_status"] == "in_sequence" and docs[1]["workflow_status"] == "paused"


def _load_script():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "outreach_kill_switch.py")
    spec = importlib.util.spec_from_file_location("outreach_kill_switch_script", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_kill_switch_script_resume_restores_paused_leads(monkeypatch):
    script = _load_script()
    docs = [{"_id": 1, "workflow_status": "paused", "campaign_id": "c1", "current_step": 0}]
    client = MagicMock()
    client.__getitem__.return_value = _db(docs)
    monkeypatch.setattr(script, "MongoClient", lambda *a, **k: client)
    monkeypatch.setattr(sys, "argv", ["outreach_kill_switch.py", "resume", "--reason", "test"])
    assert script.main() == 0
    assert docs[0]["workflow_status"] == "not_started"


def test_kill_switch_script_pause_restores_nothing(monkeypatch):
    script = _load_script()
    docs = [{"_id": 1, "workflow_status": "paused", "campaign_id": "c1", "current_step": 0}]
    client = MagicMock()
    client.__getitem__.return_value = _db(docs)
    monkeypatch.setattr(script, "MongoClient", lambda *a, **k: client)
    monkeypatch.setattr(sys, "argv", ["outreach_kill_switch.py", "pause", "--reason", "test"])
    assert script.main() == 0
    assert docs[0]["workflow_status"] == "paused"
