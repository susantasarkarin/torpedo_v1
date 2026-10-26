"""WhatsApp Cloud API (MARKETING_PLAN 3.5.3): never cold, opt-in + approved template, 24 h window, cap, shadow."""
import copy
from datetime import datetime, timedelta

import pytest

from marketing import config as mcfg, inbox as I, whatsapp as W
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 26, 5, 0)


class R:
    def __init__(self, d, s=200):
        self._d, self.status_code = d, s

    def json(self):
        return self._d


class Http:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json))
        return R({"messages": [{"id": "wamid.X"}], "id": "tpl1"})

    def get(self, url, params=None, headers=None, timeout=None):
        return R({"data": [{"name": "sfw_rfq_follow_up", "language": "en", "status": "APPROVED"},
                           {"name": "sfw_re_engagement", "language": "en", "status": "REJECTED", "rejected_reason": "PROMOTIONAL"}]})


@pytest.fixture
def env(monkeypatch):
    d = {"email_automation": FakeDB()}
    monkeypatch.setattr(W.credentials, "secrets", lambda p, gd=None: {"access_token": "T", "settings": {"waba_id": "W1",
                                                                                                      "phone_number_ids": {"ALL": "PN1"}}})
    from messaging import facade
    monkeypatch.setattr(facade, "_throttle_block", lambda a, c: None)
    return d, (lambda n: d[n])


def test_seed_submit_sync_templates(env):
    d, gd = env
    assert W.seed_templates(gd, NOW) == 15 and W.seed_templates(gd, NOW) == 0
    col = d["email_automation"]["whatsapp_templates"]
    assert W.submit_templates(gd, http=Http())["submitted"] == 0          # nothing owner-approved yet
    for t in col.docs:
        if t["bu"] == "SFW" and t["name"] in ("rfq_follow_up", "re_engagement"):
            t["status"] = "owner_approved"
    h = Http()
    assert W.submit_templates(gd, http=h)["submitted"] == 2
    body = h.calls[0][1]
    assert body["name"].startswith("sfw_") and body["components"][0]["example"]["body_text"]
    W.sync_templates(gd, http=Http())
    st = {t["name"]: t["status"] for t in col.docs if t["bu"] == "SFW" and t["name"] in ("rfq_follow_up", "re_engagement")}
    assert st == {"rfq_follow_up": "approved", "re_engagement": "rejected"}
    assert "STOP" in next(t for t in col.docs if t["name"] == "re_engagement")["body"]


def test_template_send_needs_optin_approval_cap_and_live(env):
    d, gd = env
    ea = d["email_automation"]
    cfg = copy.deepcopy(mcfg.DEFAULTS)
    phone = "9876543210"
    assert W.send_template(gd, phone=phone, template="rfq_follow_up", bu="SFW", params=["Asha", "a CATI study"], cfg=cfg,
                           now=NOW)["why"].startswith("no recorded WhatsApp opt-in")
    ea["whatsapp_optins"].insert_one({"phone_hash": I.phone_hash(phone), "granted": True, "at": NOW - timedelta(days=1)})
    assert "not approved" in W.send_template(gd, phone=phone, template="rfq_follow_up", bu="SFW", params=[], cfg=cfg, now=NOW)["why"]
    ea["whatsapp_templates"].insert_one({"name": "rfq_follow_up", "bu": "SFW", "status": "approved"})
    r = W.send_template(gd, phone=phone, template="rfq_follow_up", bu="SFW", params=["Asha", "x"], lead_id="L1", cfg=cfg, now=NOW)
    assert r == {"sent": False, "why": "shadow", "would_send": "rfq_follow_up"}
    cfg.update(mode="live", action_modes={"whatsapp:template": "live"})
    h = Http()
    assert W.send_template(gd, phone=phone, template="rfq_follow_up", bu="SFW", params=["Asha", "x"], lead_id="L1", cfg=cfg,
                           now=NOW + timedelta(hours=1), http=h)["sent"] is True            # a shadow touch never reached anyone
    again = W.send_template(gd, phone=phone, template="rfq_follow_up", bu="SFW", params=["Asha", "x"], lead_id="L1", cfg=cfg,
                            now=NOW + timedelta(hours=2), http=h)
    assert again["sent"] is False and again["why"].startswith("1 automated touch")             # the real one does
    url, body = h.calls[0]
    assert url.endswith("PN1/messages") and body["template"]["name"] == "sfw_rfq_follow_up" and body["to"] == "919876543210"


def test_free_text_reply_only_inside_24h(env):
    d, gd = env
    ea = d["email_automation"]
    ea["inbox_items"].insert_one({"channel": "whatsapp", "phone_hash": I.phone_hash("9876543210"), "at": datetime.utcnow() - timedelta(hours=1)})
    h = Http()
    assert W.reply({"author": {"phone": "9876543210"}, "bu": "SFW"}, "Sure, sending it now", gd=gd, http=h)["id"] == "wamid.X"
    with pytest.raises(RuntimeError):
        W.reply({"author": {"phone": "5550001111"}, "bu": "SFW"}, "hi", gd=gd, http=h)
