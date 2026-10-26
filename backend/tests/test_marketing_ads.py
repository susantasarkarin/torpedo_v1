"""Quora CSV + Google Ads import, offline conversions, executors (MARKETING_PLAN 3.4) -- offline, fake HTTP."""
import copy
from datetime import datetime, timedelta

import pytest
from bson import ObjectId

from marketing import ads_common as A, config as mcfg, google_ads as G, quora as Q
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 26, 1, 0)


def world():
    d = {n: FakeDB() for n in ("email_automation", "crm_db", "finance_db")}
    for name in ("ad_metrics_daily",):
        col = d["email_automation"][name]
        col.bulk_write = lambda ops, ordered=False, col=col: [col.update_one(o._filter, o._doc, upsert=o._upsert) for o in ops]
    d["finance_db"]["invoice_fx"].insert_one({"currency": "USD", "rate": 84.0, "rate_date": NOW})
    return d, (lambda n: d[n])


def test_hashing_follows_platform_normalisation():
    assert A.sha256_email(" John.Smith+ads@Gmail.com ") == A.sha256_email("johnsmith@gmail.com")
    assert A.sha256_email("x") is None and A.sha256_phone("98765 43210") == A.sha256_phone("+91-9876543210")


QUORA_CSV = """Report generated 2026-10-26
Date,Campaign Name,Ad Set Name,Ad Name,Impressions,Clicks,Spend,Conversions,Currency
2026-10-24,SFW Panel Q4,India 25-44,Ad A,"1,200",34,$12.50,2,USD
2026-10-24,SFW Panel Q4,India 25-44,Ad B,800,10,$7.50,0,USD
Total,,,,2000,44,20.00,2,
"""


def test_quora_csv_parse_loose_headers_and_campaign_totals():
    rows = Q.parse(QUORA_CSV, bu="SFW", rates={"INR": 1.0, "USD": 84.0})
    ads = [r for r in rows if r["level"] == "ad"]
    camp = [r for r in rows if r["level"] == "campaign"]
    assert len(ads) == 2 and ads[0]["impressions"] == 1200 and ads[0]["spend_inr"] == 1050.0
    assert len(camp) == 1 and camp[0]["spend_inr"] == 1680.0 and camp[0]["clicks"] == 44
    with pytest.raises(ValueError):
        Q.parse("a,b\n1,2", bu="SFW", rates={})


def test_quora_run_moves_processed_files(tmp_path):
    d, gd = world()
    (tmp_path / "SFW").mkdir()
    (tmp_path / "SFW" / "oct.csv").write_text(QUORA_CSV, encoding="utf-8")
    rep = Q.run(gd, root=str(tmp_path), now=NOW)
    assert rep["files"] == 1 and rep["rows"] == 3 and not rep["errors"]
    assert not (tmp_path / "SFW" / "oct.csv").exists() and list((tmp_path / "SFW" / "done").iterdir())
    assert Q.run(gd, root=str(tmp_path / "missing"))["skipped"]


class R:
    def __init__(self, data, status=200):
        self.status_code, self._d, self.text = status, data, str(data)

    def json(self):
        return self._d


class Http:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.calls.append((url, json or data, headers))
        if url == G.TOKEN_URL:
            return R({"access_token": "ya29.x", "expires_in": 3600})
        q = (json or {}).get("query", "")
        if "FROM customer" in q:
            return R([{"results": [{"customer": {"currencyCode": "INR", "descriptiveName": "SFW Ads"}}]}])
        if "FROM campaign WHERE segments" in q:
            return R([{"results": [{"campaign": {"id": "11", "name": "SFW Search India", "status": "ENABLED", "primaryStatus": "ELIGIBLE"},
                                    "campaignBudget": {"resourceName": "customers/1/campaignBudgets/5", "amountMicros": "2000000000"},
                                    "segments": {"date": "2026-10-24"},
                                    "metrics": {"costMicros": "1500000000", "impressions": "900", "clicks": "40", "conversions": 1.0}}]}])
        if "FROM ad_group WHERE" in q:
            return R([{"results": []}])
        if "FROM ad_group_ad" in q:
            return R([{"results": [{"adGroupAd": {"ad": {"id": "77", "name": "A"}, "status": "ENABLED",
                                                  "policySummary": {"approvalStatus": "DISAPPROVED"}},
                                    "adGroup": {"id": "9"}, "campaign": {"id": "11"}, "segments": {"date": "2026-10-24"},
                                    "metrics": {"costMicros": "0", "impressions": "0", "clicks": "0", "conversions": 0}}]}])
        if "search_term_view" in q:
            return R([{"results": [{"searchTermView": {"searchTerm": "free survey jobs"}, "campaign": {"id": "11"},
                                    "segments": {"date": "2026-10-24"}, "metrics": {"costMicros": "600000000", "clicks": "5", "conversions": 0}}]}])
        if url.endswith(":uploadClickConversions"):
            return R({"results": [{}]})
        if url.endswith(":mutate"):
            return R({"results": [{"resourceName": "customers/1/campaignCriteria/11~99"}]})
        raise AssertionError((url, q))


CRED = {"developer_token": "dev", "refresh_token": "rt", "client_secret": "cs",
        "settings": {"client_id": "cid", "login_customer_id": "999-000-1111", "customer_ids": {"SFW": "123-456-7890"},
                     "conversion_ids": {"SFW": {"lead": "customers/1234567890/conversionActions/1", "rfq": "customers/1234567890/conversionActions/2"}}}}


def test_not_configured_skips(monkeypatch):
    d, gd = world()
    monkeypatch.setattr(G.credentials, "secrets", lambda p, gd=None: {"settings": {}})
    assert "Google Ads" in G.import_daily(gd, now=NOW)["skipped"]
    with pytest.raises(G.NotConfigured):
        G.Client({"settings": {}})


def test_import_daily_stores_inr_entities_and_terms(monkeypatch):
    d, gd = world()
    monkeypatch.setattr(G.credentials, "mark", lambda *a, **k: None)
    http = Http()
    rep = G.import_daily(gd, now=NOW, cl=G.Client(CRED, http))
    assert not rep["errors"] and rep["accounts"]["1234567890"]["campaigns"] == 1
    ea = d["email_automation"]
    m = ea["ad_metrics_daily"].find_one({"level": "campaign"})
    assert m["spend_inr"] == 1500.0 and m["clicks"] == 40 and m["bu"] == "SFW"
    assert ea["ads"].find_one({"ad_id": "77"})["review_status"] == "DISAPPROVED"
    assert ea["search_terms"].find_one({})["spend_inr"] == 600.0
    hdr = next(h for u, b, h in http.calls if h and "developer-token" in h)
    assert hdr["login-customer-id"] == "9990001111" and hdr["Authorization"] == "Bearer ya29.x"


def _lead_with_gclid(d):
    lid = ObjectId()
    d["crm_db"]["leads"].insert_one({"_id": lid, "email": "asha@builder.in", "created_at": NOW - timedelta(days=5), "bu": "SFW",
                                     "source": "website_form"})
    d["email_automation"]["touchpoints"].insert_one({"lead_id": str(lid), "kind": "visit", "at": NOW - timedelta(days=6),
                                                     "click_ids": {"gclid": "Cj0KCQ"}})
    return str(lid)


def test_offline_conversions_shadow_then_live_never_twice(monkeypatch):
    d, gd = world()
    lid = _lead_with_gclid(d)
    cfg = copy.deepcopy(mcfg.DEFAULTS)
    rep = G.upload_conversions(gd, cfg=cfg, now=NOW)
    assert rep["pending"] == 2 and rep["shadow"] == 2              # lead + qualified (business-domain form)
    ups = d["email_automation"]["offline_conversion_uploads"]
    assert {u["event"] for u in ups.docs} == {"lead", "qualified_lead"} and all(u["status"] == "shadow" for u in ups.docs)
    cfg.update(mode="live", action_modes={"conversions:google": "live"})
    http = Http()
    rep = G.upload_conversions(gd, cfg=cfg, now=NOW, cl=G.Client(CRED, http))
    assert rep["sent"] == 1 and len(rep["errors"]) == 1                    # qualified_lead has no conversion action configured
    body = next(b for u, b, h in http.calls if u.endswith(":uploadClickConversions"))
    cv = body["conversions"][0]
    assert cv["gclid"] == "Cj0KCQ" and cv["conversionDateTime"].endswith("+05:30") and cv["userIdentifiers"][0]["hashedEmail"]
    again = G.upload_conversions(gd, cfg=cfg, now=NOW, cl=G.Client(CRED, Http()))
    assert again["pending"] == 1                                            # the sent 'lead' is never offered again


def test_executors_pause_and_negatives_with_undo(monkeypatch):
    http = Http()
    monkeypatch.setattr(G, "client", lambda gd=None, http_=None: G.Client(CRED, http))
    G.register()
    from marketing import engine
    try:
        dec = {"entity_key": "google:campaign:11", "bu": "SFW"}
        undo = engine._EXECUTORS[("google", "add_negatives")]["do"]({"terms": ["free survey jobs"], "match_type": "phrase"}, dec)
        op = next(b for u, b, h in http.calls if u.endswith("campaignCriteria:mutate"))["operations"][0]["create"]
        assert op["negative"] is True and op["keyword"] == {"text": "free survey jobs", "matchType": "PHRASE"}
        assert undo == {"customer": "1234567890", "criteria": ["customers/1/campaignCriteria/11~99"]}
        engine._EXECUTORS[("google", "add_negatives")]["undo"](undo, dec)
        assert next(b for u, b, h in reversed(http.calls) if u.endswith("campaignCriteria:mutate"))["operations"] == [
            {"remove": "customers/1/campaignCriteria/11~99"}]
    finally:
        engine._EXECUTORS.clear()
