"""Search Console + GA4 import (MARKETING_PLAN 3.3.1, 3.2.2), offline with a fake HTTP session."""
from datetime import datetime

from marketing import google_data as G
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 25, 2, 0)


class R:
    def __init__(self, data, status=200):
        self.status_code, self._d, self.text = status, data, str(data)

    def json(self):
        return self._d


class Http:
    def __init__(self, fail_ga4=False):
        self.calls, self.fail_ga4 = [], fail_ga4

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        if "searchAnalytics" in url:
            dims = json["dimensions"]
            if json["startRow"] > 0:
                return R({"rows": []})
            keys = {"date": "2026-10-22", "query": "survey panel india", "page": "https://cogentixresearch.com/",
                    "country": "ind", "device": "MOBILE"}
            return R({"rows": [{"keys": [keys[d] for d in dims], "clicks": 3, "impressions": 120, "ctr": 0.025, "position": 11.4}]})
        if ":runReport" in url:
            if self.fail_ga4:
                return R({"error": {"message": "User does not have sufficient permissions"}}, 403)
            return R({"rowCount": 1, "rows": [{
                "dimensionValues": [{"value": v} for v in ("20261022", "Organic Search", "google", "organic", "mobile", "India")],
                "metricValues": [{"value": v} for v in ("10", "8", "6", "7", "95.5", "22", "1")]}]})
        raise AssertionError(url)

    def get(self, url, timeout=None):
        self.calls.append((url, None))
        return R({"sitemap": [{"path": "https://cogentixresearch.com/sitemap.xml", "errors": "2", "warnings": "0"}]})


SETTINGS = {"gsc_sites": {"COGENTIX": "sc-domain:cogentixresearch.com"}, "ga4_property_ids": {"COGENTIX": ["111", "222"]}}


def test_not_configured_is_a_clean_skip(monkeypatch):
    d = {"email_automation": FakeDB()}
    monkeypatch.setattr(G.credentials, "secrets", lambda p, gd=None: {"settings": {}})
    assert "skipped" in G.run(lambda n: d[n], now=NOW)


def test_dry_run_reads_gsc_and_both_ga4_properties():
    d = {"email_automation": FakeDB()}
    http = Http()
    rep = G.run(lambda n: d[n], apply=False, now=NOW, http=http, settings=SETTINGS)
    assert rep["window"] == ["2026-10-20", "2026-10-24"]
    assert rep["gsc"]["sc-domain:cogentixresearch.com"] == {"query_rows": 1, "page_rows": 1, "sitemaps": 1, "sitemap_errors": 2}
    assert set(rep["ga4"]) == {"111", "222"} and rep["ga4"]["111"] == {"rows": 1, "sessions": 10}
    assert not rep["errors"]
    q = next(b for u, b in http.calls if b and "searchAnalytics" in u)
    assert q["dataState"] == "all" and "sc-domain%3Acogentixresearch.com" in next(u for u, b in http.calls if "searchAnalytics" in u)


def test_one_failing_property_does_not_stop_the_rest():
    d = {"email_automation": FakeDB()}
    rep = G.run(lambda n: d[n], apply=False, now=NOW, http=Http(fail_ga4=True), settings=SETTINGS)
    assert rep["gsc"] and len(rep["errors"]) == 2 and "403" in rep["errors"][0]


def test_per_bu_settings_shapes():
    assert G._per_bu({"SFW": "a", "BIM": ["b", "c"]}) == [("SFW", "a"), ("BIM", "b"), ("BIM", "c")]
    assert G._per_bu(["x"]) == [(None, "x")] and G._per_bu("y") == [(None, "y")] and G._per_bu(None) == []


def test_tracker_vs_ga4_flags_gaps_over_20pct():
    d = {"email_automation": FakeDB()}
    ea = d["email_automation"]
    for i in range(10):
        ea["web_sessions"].insert_one({"bu": "BIM", "started_at": NOW})
    ea["ga4_daily"].insert_one({"bu": "BIM", "date": "2026-10-24", "sessions": 20})
    ea["ga4_daily"].insert_one({"bu": "SFW", "date": "2026-10-24", "sessions": 0})
    ea["ga4_daily"].aggregate = lambda p: [{"_id": "BIM", "s": 20}]
    ea["web_sessions"].aggregate = lambda p: [{"_id": "BIM", "s": 10}]
    out = G.tracker_vs_ga4(lambda n: d[n], now=NOW)
    assert out == [{"bu": "BIM", "ga4_sessions": 20, "tracker_sessions": 10, "gap": 0.5, "flag": True,
                    "note": "tracker counts consented visits only; GA4 also models unconsented ones"}]
