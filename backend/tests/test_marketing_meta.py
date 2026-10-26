"""Meta integration (MARKETING_PLAN 3.4, 3.5.2) -- offline with a fake Graph API."""
import copy
import json
from datetime import datetime, timedelta

import pytest
from bson import ObjectId

from marketing import config as mcfg, inbox as I, meta as M
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 26, 1, 0)


def world(monkeypatch=None):
    d = {n: FakeDB() for n in ("email_automation", "crm_db", "finance_db")}
    col = d["email_automation"]["ad_metrics_daily"]
    col.bulk_write = lambda ops, ordered=False: [col.update_one(o._filter, o._doc, upsert=o._upsert) for o in ops]
    d["finance_db"]["invoice_fx"].insert_one({"currency": "USD", "rate": 84.0, "rate_date": NOW})
    return d, (lambda n: d[n])


class R:
    def __init__(self, data, status=200):
        self.status_code, self._d, self.text = status, data, str(data)

    def json(self):
        return self._d


class Graph:
    def __init__(self):
        self.posts = []

    def get(self, url, params=None, timeout=None):
        p = url.split(M.VERSION + "/", 1)[1]
        if p == "act_55":
            return R({"name": "SFW Ads", "currency": "USD", "account_status": 3})
        if p == "act_55/campaigns":
            return R({"data": [{"id": "c1", "name": "SFW Panel India", "effective_status": "ACTIVE", "daily_budget": "50000"}]})
        if p == "act_55/ads":
            return R({"data": [{"id": "a1", "name": "A", "adset_id": "s1", "campaign_id": "c1", "effective_status": "DISAPPROVED"}]})
        if p == "act_55/insights":
            lvl = params["level"]
            row = {"campaign_id": "c1", "campaign_name": "SFW Panel India", "adset_id": "s1", "ad_id": "a1", "date_start": "2026-10-24",
                   "spend": "10.00", "impressions": "1000", "clicks": "20", "reach": "800", "frequency": "1.25",
                   "actions": [{"action_type": "lead", "value": "2"}, {"action_type": "link_click", "value": "20"}]}
            return R({"data": [row], "paging": {}}) if lvl in ("campaign", "adset", "ad") else R({"data": []})
        if p == "111":
            return R({"access_token": "PAGE_TOKEN"})
        if p == "L77":
            return R({"created_time": "2026-10-26T00:30:00+0000", "form_id": "F1", "ad_id": "a1", "campaign_id": "c1",
                      "field_data": [{"name": "email", "values": ["Meera@Brand.in"]}, {"name": "full_name", "values": ["Meera Shah"]},
                                     {"name": "phone_number", "values": ["+919876543210"]}, {"name": "what_do_you_need", "values": ["CATI in 5 cities"]}]})
        raise AssertionError(p)

    def post(self, url, data=None, timeout=None):
        self.posts.append((url.split(M.VERSION + "/", 1)[1], data))
        return R({"id": "new_1", "events_received": 1})


CRED = {"system_user_token": "EAAG", "settings": {"ad_account_ids": {"SFW": "55"}, "page_ids": {"SFW": "111"},
                                                  "instagram_ids": {"SFW": "222"}, "pixel_ids": {"SFW": "999"}}}


def test_import_daily(monkeypatch):
    d, gd = world()
    monkeypatch.setattr(M.credentials, "mark", lambda *a, **k: None)
    rep = M.import_daily(gd, now=NOW, cl=M.Client(CRED, Graph()))
    assert not rep["errors"] and rep["accounts"]["act_55"]["status"] == "UNSETTLED"
    ea = d["email_automation"]
    camp = ea["ad_metrics_daily"].find_one({"level": "campaign"})
    assert camp["spend_inr"] == 840.0 and camp["conversions"] == 2 and camp["frequency"] == 1.25
    assert ea["ad_metrics_daily"].find_one({"level": "ad_group"})["entity_id"] == "s1"
    assert ea["ads"].find_one({"ad_id": "a1"})["review_status"] == "DISAPPROVED"
    assert ea["ad_accounts"].find_one({})["billing_problem"] is True


def test_capi_shadow_then_live(monkeypatch):
    d, gd = world()
    lid = ObjectId()
    d["crm_db"]["leads"].insert_one({"_id": lid, "email": "meera@brand.in", "phone": "9876543210", "created_at": NOW - timedelta(days=2),
                                     "bu": "SFW", "source": "csv_import"})
    d["email_automation"]["touchpoints"].insert_one({"lead_id": str(lid), "kind": "visit", "at": NOW - timedelta(days=3),
                                                     "click_ids": {"fbclid": "IwAR1"}})
    cfg = copy.deepcopy(mcfg.DEFAULTS)
    assert M.upload_conversions(gd, cfg=cfg, now=NOW)["shadow"] == 1
    cfg.update(mode="live", action_modes={"conversions:meta": "live"})
    g = Graph()
    rep = M.upload_conversions(gd, cfg=cfg, now=NOW, cl=M.Client(CRED, g))
    assert rep["sent"] == 1
    path, data = g.posts[0]
    ev = json.loads(data["data"])[0]
    assert path == "999/events" and ev["event_name"] == "Lead" and ev["action_source"] == "system_generated"
    assert ev["user_data"]["fbc"].endswith(".IwAR1") and len(ev["user_data"]["em"][0]) == 64 and ev["event_id"] == f"{lid}:lead"


def test_lead_ads_become_lead_inbox_item_and_touchpoint(monkeypatch):
    d, gd = world()
    from platform_core import review_queue
    monkeypatch.setattr(review_queue, "_col", lambda db=None: d["email_automation"]["review_queue_items"])
    d["email_automation"]["lead_form_pending"].insert_one({"leadgen_id": "L77", "page_id": "111", "bu": "SFW", "status": "pending"})
    rep = M.fetch_lead_ads(gd, now=NOW, cl=M.Client(CRED, Graph()))
    assert rep["fetched"] == 1
    lead = d["crm_db"]["leads"].find_one({"email": "meera@brand.in"})
    assert lead["source"] == "facebook_lead_ad" and lead["metadata"]["campaign_id"] == "c1"
    it = d["email_automation"]["inbox_items"].find_one({"channel": "facebook_lead_ad"})
    assert it["sla_hours"] == 1 and "CATI in 5 cities" in it["text"]
    assert d["email_automation"]["touchpoints"].find_one({"kind": "lead_form"})["channel"] == "paid_social"
    assert d["email_automation"]["lead_form_pending"].find_one({})["status"] == "fetched"


def test_dm_reply_respects_24h_window(monkeypatch):
    g = Graph()
    monkeypatch.setattr(M, "client", lambda gd=None, http=None: M.Client(CRED, g))
    item = {"channel": "messenger", "bu": "SFW", "thread_id": "u9", "external_id": "m1", "at": datetime.utcnow() - timedelta(hours=2)}
    M._reply(item, "Thanks!")
    path, data = g.posts[-1]
    assert path == "111/messages" and json.loads(data["recipient"]) == {"id": "u9"} and data["access_token"] == "PAGE_TOKEN"
    with pytest.raises(RuntimeError):
        M._reply(dict(item, at=datetime.utcnow() - timedelta(hours=30)), "late")


def test_inbox_send_approved_is_shadow_until_live(monkeypatch):
    d, gd = world()
    it_id = d["email_automation"]["inbox_items"].insert_one({"channel": "facebook_comment", "bu": "SFW", "external_id": "c1",
                                                             "at": NOW}).inserted_id
    sent = []
    I.register_sender("facebook_comment", lambda it, text: (sent.append(text), {"id": "r1"})[1])
    try:
        cfg = copy.deepcopy(mcfg.DEFAULTS)
        assert I.send_approved(gd, str(it_id), "Thanks!", by="owner", cfg=cfg)["sent"] is False and not sent
        cfg.update(mode="live", action_modes={"reply:facebook_comment": "live"})
        assert I.send_approved(gd, str(it_id), "Thanks!", by="owner", cfg=cfg)["sent"] is True and sent == ["Thanks!"]
        assert d["email_automation"]["inbox_items"].find_one({})["reply_status"] == "sent"
    finally:
        I._SENDERS.clear()
