"""
CONFIG PROBLEMS HOLD LEADS; THEY NEVER RETIRE THEM
==================================================

2026-09-04: the first send cycle after the kill switch was cleared found
OUTREACH_SENDER_POSTAL_ADDRESS unset. The gate's "compliance" refusal was mapped
to workflow_status="skipped_gate" -- a status the send query never selects --
so 338 good leads were permanently retired for a deployment problem that said
nothing about them. These tests pin the corrected behaviour:

  * a config problem is its own gate category ("config"), distinct from a
    lead-level "compliance" problem (bad / placeholder / free-webmail address);
  * the send loop's preflight returns before selecting or touching any lead;
  * the per-lead backstop leaves workflow_status alone;
  * a real lead-level problem still retires the lead (skipped_gate);
  * the hold is loud (an ERROR log and a queryable outreach_health doc) and
    clears itself once the setting is fixed.
"""
import importlib
import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def router(monkeypatch):
    monkeypatch.setenv("OUTREACH_UNSUBSCRIBE_URL", "https://example.test/unsub")
    import routers.cold_outreach_router as mod
    mod = importlib.reload(mod)
    mod._config_hold_last_alert = None
    mod._config_hold_active = False
    return mod


@pytest.fixture
def facade():
    from messaging import facade as f
    return f


# ------------------------------------------------------------- gate category

def test_missing_postal_address_is_config_not_compliance(facade, monkeypatch):
    monkeypatch.delenv("OUTREACH_SENDER_POSTAL_ADDRESS", raising=False)
    monkeypatch.setenv("OUTREACH_UNSUBSCRIBE_URL", "https://example.test/unsub")
    with patch.object(facade, "sending_enabled", return_value=True):
        blocked = facade.gate("ceo@bigcorp.com", identity="a@b.com", channel="outreach")
    assert blocked is not None and blocked[1] == "config"


def test_missing_unsubscribe_url_is_config(facade, monkeypatch):
    monkeypatch.setenv("OUTREACH_SENDER_POSTAL_ADDRESS", "1 Test Street, Kolkata")
    monkeypatch.delenv("OUTREACH_UNSUBSCRIBE_URL", raising=False)
    with patch.object(facade, "sending_enabled", return_value=True):
        blocked = facade.gate("ceo@bigcorp.com", identity="a@b.com", channel="outreach")
    assert blocked[1] == "config"


@pytest.mark.parametrize("addr", ["not-an-address", "someone@gmail.com", "x@linkedin.com"])
def test_lead_level_problems_stay_compliance(facade, addr):
    blocked = facade.gate(addr, identity="a@b.com", channel="outreach")
    assert blocked is not None and blocked[1] == "compliance"


# ------------------------------------------------------------- send loop

def _db_with(leads):
    """A fake db whose collections are stable mocks, so tests can inspect writes."""
    def _empty_coll():
        # Any collection the code probes (suppression, bounce lists, ...) must
        # say "not found" -- a bare MagicMock's find_one() is truthy and would
        # make every lead look suppressed before it ever reaches the gate.
        c = MagicMock()
        c.find_one.return_value = None
        c.count_documents.return_value = 0
        return c

    colls = {name: _empty_coll() for name in (
        "outreach_campaigns_v2", "outreach_leads_v2", "outreach_health",
        "outreach_kill_switch", "outreach_mailboxes")}
    colls["outreach_campaigns_v2"].find.return_value = [
        {"campaign_id": "c1", "business": "sfw", "mailbox_ids": []}]
    colls["outreach_leads_v2"].find.return_value.limit.return_value = leads
    db = MagicMock()
    db.__getitem__.side_effect = lambda name: colls.setdefault(name, _empty_coll())
    db.colls = colls
    return db


def test_preflight_holds_without_touching_any_lead(router, monkeypatch, caplog):
    monkeypatch.delenv("OUTREACH_SENDER_POSTAL_ADDRESS", raising=False)
    db = _db_with([{"_id": 1, "campaign_id": "c1", "email": "a@corp.com"}])
    with patch.object(router, "get_db", return_value=db), caplog.at_level(logging.ERROR):
        result = router.process_due_outreach_sends()

    leads = db.colls["outreach_leads_v2"]
    assert "OUTREACH_SENDER_POSTAL_ADDRESS" in result["held"]
    assert result["sent"] == 0
    leads.find.assert_not_called()          # no lead was even selected
    leads.update_one.assert_not_called()    # ...so none can be retired
    leads.update_many.assert_not_called()
    assert "HOLDING ALL SENDS" in caplog.text
    health = db.colls["outreach_health"]
    health.update_one.assert_called_once()  # queryable evidence of the hold
    assert health.update_one.call_args.args[0] == {"_id": "config_hold"}


def test_hold_alert_is_rate_limited(router, monkeypatch, caplog):
    monkeypatch.delenv("OUTREACH_SENDER_POSTAL_ADDRESS", raising=False)
    db = _db_with([])
    with patch.object(router, "get_db", return_value=db), caplog.at_level(logging.ERROR):
        for _ in range(5):
            router.process_due_outreach_sends()
    assert caplog.text.count("HOLDING ALL SENDS") == 1   # not one per 60s cycle


def test_hold_clears_when_the_setting_is_fixed(router, monkeypatch):
    monkeypatch.delenv("OUTREACH_SENDER_POSTAL_ADDRESS", raising=False)
    db = _db_with([])
    with patch.object(router, "get_db", return_value=db):
        router.process_due_outreach_sends()
        assert router._config_hold_active is True
        monkeypatch.setenv("OUTREACH_SENDER_POSTAL_ADDRESS", "1 Test Street, Kolkata")
        router.process_due_outreach_sends()
    assert router._config_hold_active is False
    db.colls["outreach_health"].delete_one.assert_called_once_with({"_id": "config_hold"})


def test_bookkeeping_failure_never_breaks_the_cycle(router, monkeypatch):
    monkeypatch.delenv("OUTREACH_SENDER_POSTAL_ADDRESS", raising=False)
    db = _db_with([])
    db.colls["outreach_health"].update_one.side_effect = RuntimeError("mongo down")
    with patch.object(router, "get_db", return_value=db):
        result = router.process_due_outreach_sends()
    assert "held" in result


# ------------------------------------------------------------- per-lead backstop

def _one_lead_send(router, gate_result):
    lead = {"_id": "L1", "campaign_id": "c1", "email": "a@corp.com", "current_step": 3,
            "workflow_status": "in_sequence", "lead_id": "x"}
    db = _db_with([lead])
    db.colls["outreach_kill_switch"].find_one.return_value = {"_id": "global", "paused": False}
    db.colls["outreach_campaigns_v2"].find_one.return_value = {
        "campaign_id": "c1", "is_active": True, "business": "sfw", "steps": [{}] * 5}
    fake_facade = MagicMock()
    fake_facade.gate.return_value = gate_result
    fake_messaging = MagicMock(facade=fake_facade)
    with patch.object(router, "_resolve_sender_for_campaign",
                      return_value={"from_email": "s@corp.com", "display_name": "Sam",
                                    "transport": "gmail_api"}), \
         patch.dict(sys.modules, {"messaging": fake_messaging, "messaging.facade": fake_facade}):
        router._process_one_outreach_lead(db, lead)
    return db.colls["outreach_leads_v2"]


def test_backstop_config_block_leaves_status_alone(router):
    leads = _one_lead_send(router, ("OUTREACH_SENDER_POSTAL_ADDRESS is not set", "config"))
    sets = [c.args[1]["$set"] for c in leads.update_one.call_args_list]
    assert sets, "expected the lead to be stamped with the error"
    assert all("workflow_status" not in s for s in sets)
    assert any(s.get("last_send_error", "").startswith("config:") for s in sets)


def test_backstop_lead_level_block_still_retires_the_lead(router):
    leads = _one_lead_send(router, ("unsendable domain: gmail.com", "compliance"))
    sets = [c.args[1]["$set"] for c in leads.update_one.call_args_list]
    assert any(s.get("workflow_status") == "skipped_gate" for s in sets)
