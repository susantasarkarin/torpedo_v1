"""Follow-ups go out as real replies in the first mail's thread (2026-10-14:
none of 155 multi-send leads in October were threaded; every "Re:" was fake)."""
from unittest.mock import MagicMock

import routers.cold_outreach_router as cor


class _Sends:
    def __init__(self, doc):
        self.doc = doc
        self.q = None

    def find_one(self, q, proj=None, sort=None):
        self.q = q
        return self.doc


def _gmail_with_message_id(mid):
    svc = MagicMock()
    svc._get_service.return_value.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "payload": {"headers": [{"name": "Message-ID", "value": mid}]}}
    return svc


def test_followup_finds_first_send_thread(monkeypatch):
    sends = _Sends({"gmail_message_id": "g1", "gmail_thread_id": "t1",
                    "subject": "Quick way to de-risk your next fieldwork study"})
    monkeypatch.setattr(cor, "_get_gmail_workspace_service", lambda: _gmail_with_message_id("<abc@mail.gmail.com>"))
    th = cor._followup_thread({"outreach_sends_v2": sends}, {"_id": "L1", "email": "x@y.com"}, "indira@surveyfieldwork.com")
    assert th == {"thread_id": "t1", "message_id": "<abc@mail.gmail.com>",
                  "subject": "Quick way to de-risk your next fieldwork study"}
    assert sends.q["outreach_lead_id"] == "L1" and sends.q["from_email"] == "indira@surveyfieldwork.com"


def test_no_first_send_means_no_thread(monkeypatch):
    th = cor._followup_thread({"outreach_sends_v2": _Sends(None)}, {"_id": "L1"}, "a@b.com")
    assert th is None


def test_re_prefix_detection():
    assert cor._RE_PREFIX.match("Re: fieldwork support")
    assert cor._RE_PREFIX.sub("", "RE:  fieldwork support") == "fieldwork support"
    assert not cor._RE_PREFIX.match("Report for you")
