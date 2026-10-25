"""SEO audit + PageSpeed (MARKETING_PLAN 3.3.2-3.3.3), offline."""
from datetime import datetime

from marketing import seo_audit as S
from tests._fakemongo import FakeDB

CFG = dict(S.DEFAULTS, delay_s=0)
GOOD = """<!doctype html><html><head><title>Online Survey Panel India | Survey Fieldwork</title>
<meta name="description" content="Survey Fieldwork runs online and offline fieldwork across India with a verified panel and fast turnaround.">
<meta name="viewport" content="width=device-width, initial-scale=1"><link rel="canonical" href="https://acme.com/">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Acme"}</script></head>
<body><h1>Online survey fieldwork</h1><p>""" + "We run quantitative research fieldwork for agencies and brands. " * 10 + """</p>
<a href="/services.html">Services</a><a href="/old.html">Old</a><a href="https://gone.example/x">partner</a>
<img src="/hero.jpg" alt="Team"></body></html>"""
JS_ONLY = """<html><head><title>Services</title><script src="/static/app.js"></script></head>
<body><div id="root"></div><img src="/a.png"><img src="/b.png"><img src="/c.png"></body></html>"""
SITE = {
    "https://acme.com/robots.txt": (200, "User-agent: *\nDisallow: /admin\n", []),
    "https://acme.com/sitemap.xml": (200, "<urlset><url><loc>https://acme.com/</loc></url>"
                                          "<url><loc>https://acme.com/orphan.html</loc></url></urlset>", []),
    "https://acme.com/": (200, GOOD, []),
    "https://acme.com/services.html": (200, JS_ONLY, []),
    "https://acme.com/old.html": (404, "", []),
    "https://acme.com/orphan.html": (200, GOOD.replace("<h1>Online survey fieldwork</h1>", ""), []),
}


def fetch(url):
    return SITE.get(url, (404, "", []))


def head(url):
    return {"https://gone.example/x": (404, None), "https://acme.com/hero.jpg": (200, 900 * 1024)}.get(url, (200, 1000))


def codes(res):
    return {i["code"] for i in res["issues"]}


def test_analyze_page_reads_seo_basics():
    p = S.analyze_page(GOOD, "https://acme.com/")
    assert p["title"].startswith("Online Survey") and p["h1"] == ["Online survey fieldwork"] and p["viewport"]
    assert p["schema_types"] == ["Organization"] and p["canonical"] == "https://acme.com/" and p["words"] > 60
    assert "https://acme.com/services.html" in p["links"]


def test_crawl_finds_page_and_site_issues():
    res = S.crawl("acme.com", fetch, CFG, head=head)
    c = codes(res)
    assert {"js_only_content", "title_length", "meta_missing", "viewport_missing", "img_alt_missing", "img_no_lazy",
            "broken_page", "orphan_page", "title_duplicate", "robots_no_sitemap", "broken_external", "img_heavy",
            "h1_missing", "sitemap_incomplete", "schema_service_missing"} <= c
    assert "sitemap_missing" not in c and "schema_org_missing" not in c
    assert res["issues"][0]["severity"] == "high"                       # sorted by severity
    broken = next(i for i in res["issues"] if i["code"] == "broken_page")
    assert "https://acme.com/" in broken["detail"]                      # where it is linked from


def test_robots_disallow_respected():
    site = dict(SITE)
    site["https://acme.com/"] = (200, GOOD.replace("/old.html", "/admin/secret"), [])
    seen = []
    res = S.crawl("acme.com", lambda u: (seen.append(u), site.get(u, (404, "", [])))[1], CFG)
    assert "https://acme.com/admin/secret" not in seen and res["pages"]


def test_run_writes_audit_and_closes_fixed_issues():
    d = {"email_automation": FakeDB()}
    gd = lambda n: d[n]
    sites = [{"domain": "acme.com", "bu": "SFW"}]
    S.run(gd, sites=sites, fetchers=(fetch, head), now=datetime(2026, 10, 25))
    ea = d["email_automation"]
    assert ea["seo_audits"].count_documents({}) == 1 and ea["seo_audits"].find_one({})["bu"] == "SFW"
    n_open = ea["seo_issues"].count_documents({"status": "open"})
    assert n_open > 10
    SITE_FIXED = dict(SITE)
    SITE_FIXED["https://acme.com/old.html"] = (200, GOOD, [])
    S.run(gd, sites=sites, fetchers=(lambda u: SITE_FIXED.get(u, (404, "", [])), head), now=datetime(2026, 11, 1))
    fixed = [i for i in ea["seo_issues"].docs if i["status"] == "fixed"]
    assert any(i["code"] == "broken_page" for i in fixed)


class _R:
    status_code = 200

    def json(self):
        return {"lighthouseResult": {"categories": {"performance": {"score": 0.42}},
                                     "audits": {"largest-contentful-paint": {"numericValue": 4100.0},
                                                "cumulative-layout-shift": {"numericValue": 0.12}}},
                "loadingExperience": {"overall_category": "SLOW",
                                      "metrics": {"INTERACTION_TO_NEXT_PAINT": {"percentile": 320, "category": "AVERAGE"}}}}


def test_pagespeed_parses_lab_and_field_metrics():
    got = {}
    r = S.pagespeed("https://acme.com/", "mobile", None, get=lambda url, params, timeout: (got.update(params), _R())[1])
    assert "key" not in got and r["score"] == 42 and r["lab"]["lcp_ms"] == 4100.0
    assert r["field"]["inp"] == {"p75": 320, "category": "AVERAGE"} and r["field"]["lcp"] is None
