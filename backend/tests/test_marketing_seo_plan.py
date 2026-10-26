"""SEO planning (MARKETING_PLAN 3.3.4-3.3.6)."""
import zipfile
from datetime import datetime, timedelta

from marketing import seo_plan as P
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 26, 2, 0)


def world():
    d = {"email_automation": FakeDB()}
    return d, (lambda n: d[n])


def gsc(ea, q, page, impr, clicks, pos, bu="BIM", days=3):
    for i in range(1, days + 1):
        ea["gsc_queries_daily"].insert_one({"bu": bu, "query": q, "page": page, "date": (NOW - timedelta(days=i)).strftime("%Y-%m-%d"),
                                            "impressions": impr, "clicks": clicks, "position": pos})


def test_keywords_seeded_and_positions_tracked():
    d, gd = world()
    ea = d["email_automation"]
    gsc(ea, "scan to bim services", "https://bimwavesolutions.com/scan-to-bim.html", 100, 3, 11.0)
    gsc(ea, "bim company pune", "https://bimwavesolutions.com/", 300, 1, 6.0)
    rep = P.track_positions(gd, now=NOW)
    kws = {k["keyword"]: k for k in ea["keywords"].docs if k["bu"] == "BIM"}
    assert "scan to bim services" in kws and kws["bim company pune"]["origin"] == "gsc_top_query"
    pos = {p["keyword"]: p for p in ea["keyword_positions"].docs}
    assert pos["scan to bim services"]["position"] == 11.0 and pos["scan to bim services"]["impressions"] == 300
    assert pos["bim services india"]["position"] is None and rep["positions"] >= 13


def test_opportunities():
    d, gd = world()
    gsc(d["email_automation"], "scan to bim services", "x", 100, 3, 11.0)
    gsc(d["email_automation"], "bim company pune", "y", 300, 1, 6.0)
    ops = P.opportunities(gd, now=NOW)
    assert [o["query"] for o in ops] == ["bim company pune", "scan to bim services"]
    assert "rewrite title" in ops[0]["why"] and "page 2" in ops[1]["why"]


def test_content_gaps_services_queries_questions():
    d, gd = world()
    ea = d["email_automation"]
    ea["seo_audits"].insert_one({"bu": "BIM", "site": "bimwavesolutions.com", "started_at": NOW, "page_rows": [
        {"url": "https://bimwavesolutions.com/scan-to-bim.html", "title": "Scan to BIM", "h1": ["Scan to BIM services"]}]})
    gsc(ea, "revit family creation", "https://bimwavesolutions.com/", 60, 0, 14.0)
    ea["inbox_items"].insert_one({"category": "rfq", "bu": "BIM", "at": NOW - timedelta(days=3),
                                  "text": "Hi, can you do LOD 400 for a 3 floor hospital? Reach me at ravi@studio.in or +91 98765 43210?"})
    rep = P.content_gaps(gd, now=NOW, cfg={"competitors": {"BIM": ["Tesla Outsourcing"]}})
    kinds = {(g["kind"], g["topic"]) for g in ea["content_gaps"].docs}
    assert ("service_without_page", "revit") in kinds and ("service_without_page", "scan to bim") not in kinds
    assert ("query_without_matching_page", "revit family creation") in kinds
    q = [g["topic"] for g in ea["content_gaps"].docs if g["kind"] == "client_question"]
    assert any("LOD 400" in t for t in q) and not any("ravi@" in t or "98765" in t for t in q)
    assert ("competitor", "Tesla Outsourcing") in kinds
    assert P.content_gaps(gd, now=NOW, cfg={})["new_gaps"] == 0                      # idempotent


def test_fix_plan_and_package(tmp_path):
    d, gd = world()
    ea = d["email_automation"]
    ea["seo_audits"].insert_one({"bu": "BIM", "site": "bimwavesolutions.com", "started_at": NOW, "page_rows": [
        {"url": "https://bimwavesolutions.com/", "status": 200, "title": "Home", "h1": ["BIM modelling services for AEC teams"]},
        {"url": "https://bimwavesolutions.com/about.html", "status": 200, "title": "About", "h1": ["About us"]}]})
    for code, url in (("title_length", "https://bimwavesolutions.com/"), ("canonical_missing", "https://bimwavesolutions.com/about.html"),
                      ("schema_org_missing", "https://bimwavesolutions.com/"), ("robots_no_sitemap", "/robots.txt"),
                      ("meta_missing", "https://bimwavesolutions.com/about.html")):
        ea["seo_issues"].insert_one({"site": "bimwavesolutions.com", "status": "open", "code": code, "url": url, "detail": "x"})
    plan = P.fix_plan(gd, "bimwavesolutions.com", now=NOW)
    t = next(c for c in plan["changes"] if c["type"] == "title")
    assert t["value"] == "BIM modelling services for AEC teams | BIM Wave Solutions"
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<html><head><title>Home</title></head><body></body></html>", encoding="utf-8")
    (site / "about.html").write_text("<html><head><title>About</title></head><body></body></html>", encoding="utf-8")
    (site / "untouched.html").write_text("<html></html>", encoding="utf-8")
    out = P.apply_package(plan, str(site), str(tmp_path / "out"))
    assert set(out["files_changed"]) == {"index.html", "about.html", "robots.txt"}
    z = zipfile.ZipFile(out["zip"])
    names = set(z.namelist())
    assert {"CHANGES.md", "ROLLBACK.md", "index.html", "about.html", "robots.txt"} <= names and "untouched.html" not in names
    idx = z.read("index.html").decode()
    assert "<title>BIM modelling services" in idx and '"Organization"' in idx
    assert '<link rel="canonical" href="https://bimwavesolutions.com/about.html">' in z.read("about.html").decode()
    assert "needs written copy" in z.read("CHANGES.md").decode()                   # meta description: listed, not invented
    assert (site / "index.html").read_text(encoding="utf-8").count("Organization") == 0   # the owner's copy is untouched
