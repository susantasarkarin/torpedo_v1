"""LinkedIn integration (MARKETING_PLAN 3.4, 3.5.1) -- fake REST."""
import copy
from datetime import datetime, timedelta

from bson import ObjectId

from marketing import config as mcfg, linkedin as L
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 26, 1, 0)


class R:
    def __init__(self, d, s=200, headers=None):
        self._d, self.status_code, self.text, self.headers = d, s, str(d), headers or {}

    def json(self):
        return self._d


class Http:
    def __init__(self, expire_first=False):
        self.calls, self.expire = [], expire_first

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, None, headers))
        if self.expire:
            self.expire = False
            return R({}, 401)
        if url.endswith("adAccounts/510"):
            return R({"name": "BIM Ads", "currency": "USD", "status": "ACTIVE"})
        if "adCampaigns?q=search" in url:
            return R({"elements": [{"id": 9001, "name": "BIM Scan-to-BIM", "status": "ACTIVE", "dailyBudget": {"amount": "50"}}]})
        if "adAnalytics" in url:
            return R({"elements": [{"dateRange": {"start": {"year": 2026, "month": 10, "day": 24}}, "pivotValues": ["urn:li:sponsoredCampaign:9001"],
                                    "impressions": 3000, "clicks": 45, "costInLocalCurrency": "25.5", "oneClickLeads": 2, "externalWebsiteConversions": 1}]})
        if "organizationalEntityShareStatistics" in url:
            return R({"elements": [{"timeRange": {"start": int(datetime(2026, 10, 24).timestamp() * 1000)},
                                    "totalShareStatistics": {"uniqueImpressionsCount": 900, "impressionCount": 1500, "likeCount": 20,
                                                             "commentCount": 3, "shareCount": 2, "clickCount": 30}}]})
        if "leadFormResponses" in url:
            return R({"elements": [{"id": "resp-1", "campaign": "urn:li:sponsoredCampaign:9001", "formResponse": {"answers": [
                {"answerDetails": {"textQuestionAnswer": {"answer": "Ravi@Studio.in"}}}, {"answerDetails": {"textQuestionAnswer": {"answer": "LOD 400 model of a hospital"}}}]}}]})
        raise AssertionError(url)

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append(("POST", url, json or data, headers))
        if url == L.TOKEN_URL:
            return R({"access_token": "NEW"})
        return R({}, 201, headers={"x-restli-id": "urn:li:share:123"})


CRED = {"access_token": "OLD", "refresh_token": "RT", "client_secret": "CS",
        "settings": {"client_id": "CID", "ad_account_ids": {"BIM": "510"}, "organization_ids": {"BIM": "777"},
                     "conversion_ids": {"BIM": {"lead": "42"}}}}


def world():
    d = {n: FakeDB() for n in ("email_automation", "crm_db", "finance_db")}
    col = d["email_automation"]["ad_metrics_daily"]
    col.bulk_write = lambda ops, ordered=False: [col.update_one(o._filter, o._doc, upsert=o._upsert) for o in ops]
    d["finance_db"]["invoice_fx"].insert_one({"currency": "USD", "rate": 84.0, "rate_date": NOW})
    return d, (lambda n: d[n])


def test_import_analytics_and_page_stats(monkeypatch):
    d, gd = world()
    monkeypatch.setattr(L.credentials, "mark", lambda *a, **k: None)
    h = Http()
    rep = L.import_daily(gd, now=NOW, cl=L.Client(CRED, h))
    assert not rep["errors"] and rep["page_stats"] == 1
    m = d["email_automation"]["ad_metrics_daily"].find_one({"level": "campaign"})
    assert m["entity_id"] == "9001" and m["spend_inr"] == 2142.0 and m["conversions"] == 3 and m["date"] == "2026-10-24"
    s = d["email_automation"]["social_metrics_daily"].find_one({})
    assert s["reach"] == 900 and s["engagement"] == 55
    hdr = h.calls[0][3]
    assert hdr["LinkedIn-Version"] == L.VERSION and hdr["X-Restli-Protocol-Version"] == "2.0.0"
    assert any("accounts=List(urn%3Ali%3AsponsoredAccount%3A510)" in c[1] for c in h.calls)


def test_token_refresh_on_401(monkeypatch):
    monkeypatch.setattr(L.credentials, "save", lambda *a, **k: None)
    h = Http(expire_first=True)
    cl = L.Client(CRED, h)
    assert cl.get("adAccounts/510")["name"] == "BIM Ads" and cl.token == "NEW"


def test_conversions_and_lead_forms(monkeypatch):
    d, gd = world()
    lid = ObjectId()
    d["crm_db"]["leads"].insert_one({"_id": lid, "email": "ravi@studio.in", "created_at": NOW - timedelta(days=1), "bu": "BIM", "source": "x"})
    d["email_automation"]["touchpoints"].insert_one({"lead_id": str(lid), "kind": "visit", "at": NOW - timedelta(days=2),
                                                     "click_ids": {"li_fat_id": "abc-uuid"}})
    cfg = copy.deepcopy(mcfg.DEFAULTS)
    cfg.update(mode="live", action_modes={"conversions:linkedin": "live"})
    h = Http()
    rep = L.upload_conversions(gd, cfg=cfg, now=NOW, cl=L.Client(CRED, h))
    assert rep["sent"] == 1
    body = next(c[2] for c in h.calls if c[1].endswith("conversionEvents"))
    assert body["conversion"] == "urn:lla:llaPartnerConversion:42" and body["user"]["userIds"][0]["idValue"] == "abc-uuid"
    from platform_core import review_queue
    monkeypatch.setattr(review_queue, "_col", lambda db=None: d["email_automation"]["review_queue_items"])
    assert L.fetch_lead_forms(gd, now=NOW, cl=L.Client(CRED, Http()))["fetched"] == 1
    it = d["email_automation"]["inbox_items"].find_one({"channel": "linkedin_lead_form"})
    assert "LOD 400" in it["text"] and it["lead_id"] == str(lid)                      # matched the existing lead by email
    assert d["crm_db"]["leads"].count_documents({}) == 1


def test_publish_company_page_post(monkeypatch):
    h = Http()
    monkeypatch.setattr(L, "client", lambda gd=None, http=None: L.Client(CRED, h))
    out = L.publish({"bu": "BIM", "body": "Scan to BIM for hospitals", "hashtags": ["#BIM"]})
    body = next(c[2] for c in h.calls if c[1].endswith("/posts"))
    assert body["author"] == "urn:li:organization:777" and body["commentary"].endswith("#BIM") and out["post_id"] == "urn:li:share:123"
