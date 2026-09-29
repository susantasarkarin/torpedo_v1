"""
The campaign editor's Test button (POST /campaigns/{id}/steps/{n}/test).

It referenced gmail_mailbox / smtp_mailbox, never defined in the function, so
every click failed with a NameError; and it skipped the opt-out footer the
real send adds. It now goes through the real sender resolution, footer and
transport.
"""
import importlib

import pytest

import routers.cold_outreach_router as cor


class _Col:
    def __init__(self, doc):
        self.doc = doc

    def find_one(self, *a, **k):
        return self.doc


class _Req:
    recipient_email = "susanta+outreach-test@surveyfieldwork.com"


CAMPAIGN = {"campaign_id": "c1", "business": "sfw", "steps": [
    {"step_number": 1, "subject": "Fieldwork for {{company}}", "body_html": "<p>Hi {{first_name}},</p>"}]}


@pytest.fixture
def wired(monkeypatch):
    monkeypatch.setenv("TRACKING_BASE_URL", "https://crm.example.com")
    monkeypatch.setenv("OUTREACH_SHOW_UNSUBSCRIBE_LINK", "true")
    import services.outreach_unsubscribe as unsub
    importlib.reload(unsub)
    monkeypatch.setattr(cor, "get_db", lambda: {"outreach_campaigns_v2": _Col(CAMPAIGN)})
    monkeypatch.setattr(cor, "_resolve_sender_for_campaign", lambda db, c: {
        "from_email": "susanta@surveyfieldwork.com", "display_name": "Susanta", "transport": "gmail"})
    sent = []
    monkeypatch.setattr(cor, "_send_via_gmail_api",
                        lambda frm, to, subj, body, name, attachments=None:
                        sent.append((frm, to, subj, body)) or {"message_id": "m1", "thread_id": "t1"})
    return sent


def test_test_send_goes_through_the_real_transport_with_the_optout(wired):
    out = cor.send_test_email("c1", 1, _Req())
    assert out["ok"] and out["message_id"] == "m1" and out["transport"] == "gmail"
    frm, to, subject, body = wired[0]
    assert to == _Req.recipient_email and subject == "[TEST] Fieldwork for Acme Corp"
    assert "Hi Alex" in body and "/api/cold-outreach/unsubscribe/" in body


def test_test_send_refuses_when_no_optout_can_be_built(wired, monkeypatch):
    import services.outreach_unsubscribe as unsub
    monkeypatch.setattr(unsub, "footer_blocker", lambda: "no base URL")
    with pytest.raises(cor.HTTPException) as e:
        cor.send_test_email("c1", 1, _Req())
    assert e.value.status_code == 400 and not wired
