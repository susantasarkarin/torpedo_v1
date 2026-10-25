"""Company websites -> Torpedo: page converter, enquiry capture, site check."""
import importlib.util
import os
from datetime import datetime, timedelta

from tests._fakemongo import FakeDB
from web_tracking import leads, rules

_spec = importlib.util.spec_from_file_location(
    "site_connect", os.path.join(os.path.dirname(__file__), "..", "scripts", "site_connect.py"))
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>x</title>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-TEST"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-TEST');</script>
<script>!function(f,b,e,v){}(window,document,'script','x');fbq('init','123');fbq('track','PageView');</script>
<noscript><img src="https://www.facebook.com/tr?id=123&ev=PageView"></noscript>
<script src="js/main.js"></script></head><body>
<form id="contact-form"><input name="name"><input type="email" name="email"><textarea name="message"></textarea><button type="submit">Send</button></form>
<form class="newsletter"><input type="email" name="email"></form>
</body></html>"""


def test_converter_gates_tags_wires_contact_form_only_and_is_idempotent():
    out, rep = sc.convert_page(PAGE, origin="https://t.acme.com", bu="BIM", thanks='Thank you! "Quoted"', mode="alert")
    head = out.split("<head>")[1]
    assert head.index('<meta charset="utf-8">') < head.index("gtag('consent','default'") < head.index("t.acme.com/api/track/t.js")
    assert 'data-bu="BIM"' in out
    assert out.count('type="text/plain" data-cgx-consent') == 3 and "facebook.com/tr" not in out
    assert '<script src="js/main.js"></script>' in out
    assert rep["forms_wired"] == ["contact-form [intercept]"] and rep["forms_skipped"] == ["newsletter"]
    assert 'data-cgx-mode="intercept"' in out
    observed, rep3 = sc.convert_page(PAGE, origin="https://t.acme.com", bu="BIM", thanks="x", mode="alert", handled={"contact-form"})
    assert rep3["forms_wired"] == ["contact-form [observe]"] and 'data-cgx-mode="observe"' in observed
    assert 'name="website_url"' in out and 'data-cgx-success="Thank you! &quot;Quoted&quot;"' in out
    again, rep2 = sc.convert_page(out, origin="https://t.acme.com", bu="BIM", thanks="x", mode="alert")
    assert again == out and not rep2["tracker_added"]


def test_run_writes_only_changed_files_and_never_touches_the_source(tmp_path):
    src = tmp_path / "src"
    (src / "js").mkdir(parents=True)
    (src / "index.html").write_text(PAGE, encoding="utf-8")
    (src / "style.css").write_text("body{}", encoding="utf-8")
    (src / "js" / "main.js").write_text("alert('Thank you! Your inquiry has been received.');", encoding="utf-8")
    before = (src / "index.html").read_text(encoding="utf-8")
    rep = sc.run(str(src), str(tmp_path / "out"), "cogentixresearch.com", "COGENTIX")
    assert (src / "index.html").read_text(encoding="utf-8") == before
    assert os.listdir(tmp_path / "out" / "changed") == ["index.html"]
    assert rep["thank_you"] == "Thank you! Your inquiry has been received." and rep["summary"]["forms_wired"] == 1
    assert "https://t.cogentixresearch.com/api/track/t.js" in (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")


def test_site_for_host_aliases_and_staging():
    cfg = {**rules.DEFAULTS, "staging_hosts": {"127.0.0.2": "bimwavesolutions.com"}}
    assert rules.site_for_host("www.cogentixresearch.com", cfg)["bu"] == "COGENTIX"
    assert rules.site_for_host("business.surveyfieldwork.com", cfg)["bu"] == "SFW"
    assert rules.site_for_host("127.0.0.2", cfg)["domain"] == "bimwavesolutions.com"
    assert rules.site_for_host("evil.com", cfg) is None


def _gd():
    d = {n: FakeDB() for n in ("crm_db", "email_automation")}
    return d, (lambda name: d[name])


SITE = {"domain": "bimwavesolutions.com", "bu": "BIM"}


def _body(**f):
    return {"fields": {"name": "Asha Rao", "email": "asha@builder.in", "company": "Builder", "message": "Need BIM for a mall",
                       "service": "Scan to BIM", **f}, "v": "vis1",
            "page": "https://bimwavesolutions.com/contact.html?utm_source=li", "utm": {"utm_source": "li"}, "elapsed_ms": 9000}


def test_enquiry_creates_lead_review_item_with_draft_then_dedupes(monkeypatch):
    d, gd = _gd()
    from platform_core import review_queue
    monkeypatch.setattr(review_queue, "_col", lambda db=None: d["email_automation"]["review_queue_items"])
    from platform_core import audit
    monkeypatch.setattr(audit, "log_action", lambda **k: None)
    r1 =leads.capture(gd, _body(), site=SITE, ip="1.2.3.4", ua="ua", contact_from_token=None, cfg=rules.DEFAULTS)
    assert r1["ok"] and r1["dedupe"] == "new"
    lead = d["crm_db"]["leads"].find_one({"email": "asha@builder.in"})
    assert lead["bu"] == "BIM" and lead["outreach_bucket"] == "BIM" and lead["web_submissions"][0]["utm"] == {"utm_source": "li"}
    item = d["email_automation"]["review_queue_items"].find_one({"type": "inbound_lead"})
    assert item["suggested"]["to"] == "asha@builder.in" and "Hi Asha" in item["suggested"]["body"] and item["bu"] == "BIM"
    assert d["email_automation"]["web_visitors"].find_one({"visitor_id": "vis1"})["lead_id"] == r1["lead_id"]
    retry = leads.capture(gd, _body(), site=SITE, ip="1.2.3.4", ua="ua", contact_from_token=None, cfg=rules.DEFAULTS,
                          now=datetime.utcnow())
    assert retry["dedupe"] == "repeat_merged"
    r2 = leads.capture(gd, _body(message="Second enquiry"), site=SITE, ip="1.2.3.4", ua="ua", contact_from_token=None,
                       cfg=rules.DEFAULTS, now=datetime.utcnow() + timedelta(hours=2))
    assert r2["dedupe"] == "existing_lead" and r2["lead_id"] == r1["lead_id"]
    assert len(d["crm_db"]["leads"].docs) == 1
    assert d["email_automation"]["review_queue_items"].count_documents({"type": "inbound_lead"}) == 2


def test_honeypot_and_too_fast_write_nothing_and_bad_email_rejected():
    d, gd = _gd()
    kw = dict(site=SITE, ip="", ua="", contact_from_token=None, cfg=rules.DEFAULTS)
    assert leads.capture(gd, _body(website_url="http://spam"), **kw) == {"ok": True}
    assert leads.capture(gd, {**_body(), "elapsed_ms": 300}, **kw) == {"ok": True}
    assert not d["crm_db"]["leads"].docs
    assert not leads.capture(gd, _body(email="nope"), **kw)["ok"]


def test_lead_route_rejects_other_origins_and_reflects_allowed_one(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import web_tracking as wt
    from web_tracking import leads as lmod
    monkeypatch.setattr(wt, "_cfg", lambda: rules.DEFAULTS)
    monkeypatch.setattr(lmod, "capture", lambda *a, **k: {"ok": True, "lead_id": "x"})
    app = FastAPI()
    app.include_router(wt.router)
    c = TestClient(app)
    bad = c.post("/api/track/lead", content='{"fields":{}}', headers={"Origin": "https://evil.com", "Content-Type": "text/plain"})
    assert bad.status_code == 403 and "access-control-allow-origin" not in bad.headers
    ok = c.post("/api/track/lead", content='{"fields":{}}',
                headers={"Origin": "https://www.cogentixresearch.com", "Content-Type": "text/plain"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "https://www.cogentixresearch.com"


def test_site_check_flags_silent_sites_only_after_install(monkeypatch):
    from platform_core import config_store
    from web_tracking import site_check
    monkeypatch.setattr(config_store, "get", lambda s, db=None: config_store.defaults(s))
    d, gd = _gd()
    now = datetime(2026, 10, 25, 3)
    d["email_automation"]["web_events"].insert_one({"host": "cogentixresearch.com", "type": "page_view", "at": now - timedelta(hours=2)})
    d["email_automation"]["web_events"].insert_one({"host": "bimwavesolutions.com", "type": "page_view", "at": now - timedelta(hours=40)})
    out = {s["domain"]: s["status"] for s in site_check.run(now=now, gd=gd)["sites"]}
    assert out == {"business.surveyfieldwork.com": "not_installed", "cogentixresearch.com": "ok", "bimwavesolutions.com": "silent"}


def test_enquiry_stores_attribution_optins_and_heard_from(monkeypatch):
    d, gd = _gd()
    from platform_core import review_queue
    monkeypatch.setattr(review_queue, "_col", lambda db=None: d["email_automation"]["review_queue_items"])
    from platform_core import audit
    monkeypatch.setattr(audit, "log_action", lambda **k: None)
    b = _body(phone="+91 98765 43210", optin_whatsapp="on", optin_email="true", heard_from="LinkedIn post")
    b.update(click_ids={"gclid": "G1", "bogus": "x"}, first_touch={"utm_source": "google", "landing": "https://bimwavesolutions.com/"},
             consent=True)
    r = leads.capture(gd, b, site=SITE, ip="1.2.3.4", ua="ua", contact_from_token=None, cfg=rules.DEFAULTS)
    sub = d["crm_db"]["leads"].find_one({"email": "asha@builder.in"})["web_submissions"][0]
    assert sub["click_ids"] == {"gclid": "G1"} and sub["first_touch"]["utm_source"] == "google"
    assert sub["heard_from"] == "LinkedIn post" and sub["optin"] == {"email": True, "whatsapp": True}
    opt = d["email_automation"]["whatsapp_optins"].find_one({"lead_id": r["lead_id"]})
    assert opt["granted"] and opt["phone_last4"] == "3210" and "98765" not in str(opt)
    assert d["crm_db"]["leads"].find_one({"email": "asha@builder.in"})["email_optin"]["granted"]


def test_no_optin_ticked_records_no_optin(monkeypatch):
    d, gd = _gd()
    from platform_core import review_queue
    monkeypatch.setattr(review_queue, "_col", lambda db=None: d["email_automation"]["review_queue_items"])
    from platform_core import audit
    monkeypatch.setattr(audit, "log_action", lambda **k: None)
    leads.capture(gd, _body(phone="9876543210"), site=SITE, ip="", ua="", contact_from_token=None, cfg=rules.DEFAULTS)
    assert d["email_automation"]["whatsapp_optins"].count_documents({}) == 0
