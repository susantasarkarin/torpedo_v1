"""Landing tracking (CRM plan 3.12)."""
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web_tracking import rules

NOW = datetime(2026, 10, 24, 12, 0)


def test_token_round_trip_and_tamper():
    t = rules.make_token("6adb49f57e9ca4b06a1e8c37", "s3cret")
    assert rules.read_token(t, "s3cret") == "6adb49f57e9ca4b06a1e8c37"
    assert rules.read_token(t, "other") is None
    assert rules.read_token(t[:-2] + "xx", "s3cret") is None
    assert rules.read_token("garbage", "s3cret") is None


def test_ip_is_truncated_and_redirects_are_allow_listed():
    assert rules.ip_prefix("203.0.113.77") == "203.0.113.0/24"
    assert rules.safe_redirect("https://www.surveyfieldwork.com/x") and not rules.safe_redirect("https://evil.com/")


def test_clean_event_keeps_utm_bu_and_drops_unknown_types():
    e = rules.clean_event({"type": "page_view", "url": "https://www.surveyfieldwork.com/pricing?utm_source=li&x=1", "consent": True},
                          visitor="v1", ip="1.2.3.4", ua="ua", now=NOW)
    assert e["bu"] == "SFW" and e["utm"] == {"utm_source": "li"} and e["path"] == "/pricing" and e["ip_prefix"] == "1.2.3.0/24"
    assert rules.clean_event({"type": "keylog"}, visitor="v1", ip="", ua="", now=NOW) is None


def _ev(t, path="/", at=NOW, **kw):
    return {"type": t, "path": path, "at": at, **kw}


def test_scoring_weights():
    hi = rules.score([_ev("page_view", "/pricing"), _ev("page_view", at=NOW - timedelta(days=2)),
                      _ev("time_on_page", value=90)], NOW)
    assert hi["score"] == 110 and hi["level"] == "high"
    assert rules.score([_ev("page_view")], NOW)["why"] == ["bounce"]


def test_follow_up_rules():
    form = [_ev("form_start", at=NOW - timedelta(hours=3), form_email="a@b.com")]
    assert rules.follow_up({}, form, NOW) == {"action": "form_reminder", "email": "a@b.com"}
    assert rules.follow_up({}, form + [_ev("form_submit")], NOW) is None
    seq = rules.follow_up({"contact_id": "c", "in_active_sequence": True}, [_ev("page_view", "/panel")], NOW)
    assert seq["action"] == "pull_next_follow_up_forward"
    hot = [_ev("page_view", "/pricing"), _ev("page_view", at=NOW - timedelta(days=1))]
    assert rules.follow_up({"company_match": "Acme"}, hot, NOW)["action"] == "create_lead_and_outreach"
    assert rules.follow_up({"contact_id": "c", "dnd": True}, hot, NOW) is None


def test_audiences_exclude_clients_dnd_and_no_consent():
    vs = [{"visitor_id": "a", "bus": ["SFW"], "consent": True, "last_seen": NOW, "high_intent": True},
          {"visitor_id": "b", "bus": ["SFW"], "consent": False, "last_seen": NOW},
          {"visitor_id": "c", "bus": ["SFW"], "consent": True, "last_seen": NOW, "is_client": True},
          {"visitor_id": "d", "bus": ["BIM"], "consent": True, "last_seen": NOW - timedelta(days=40)}]
    assert rules.audiences(vs, NOW) == {"SFW": {"all_30d": ["a"], "high_intent": ["a"], "form_abandoners": []}}


def test_tracker_script_gates_tags_on_consent():
    from routers import web_tracking
    app = FastAPI()
    app.include_router(web_tracking.router)
    js = TestClient(app).get("/api/track/t.js").text
    assert "gtag('consent','default'" in js and "ad_storage:'denied'" in js and "if(consent)tags()" in js
    assert "sendBeacon" in js and "%CFG%" not in js


def test_no_consent_keeps_only_anonymous_page_views():
    url = "https://cogentixresearch.com/services?utm_source=li&gclid=abc&email=x@y.com"
    e = rules.clean_event({"type": "page_view", "url": url, "referrer": "https://www.google.com/search?q=me"},
                          visitor="v1", ip="1.2.3.4", ua="ua", now=NOW)
    assert e["visitor_id"] is None and e["ip_prefix"] is None and e["ua"] is None and e["click_ids"] == {}
    assert e["url"] == "https://cogentixresearch.com/services" and e["referrer"] == "www.google.com"
    assert e["utm"] == {"utm_source": "li"} and e["bu"] == "COGENTIX"          # campaign counts stay aggregate
    for t in ("scroll", "cta_click", "form_start", "form_submit", "form_abandon", "outbound_click"):
        assert rules.clean_event({"type": t, "url": url, "value": 50}, visitor="v1", ip="", ua="", now=NOW) is None
    assert rules.clean_event({"type": "consent", "value": 0, "url": url}, visitor="", ip="", ua="", now=NOW)


def test_consented_events_carry_click_ids_session_and_scroll_marks():
    url = "https://bimwavesolutions.com/?gclid=G1&fbclid=F1&li_fat_id=L1&wbraid=W1"
    e = rules.clean_event({"type": "page_view", "url": url, "consent": True, "session": "s1"},
                          visitor="v1", ip="1.2.3.4", ua="ua", now=NOW)
    assert e["click_ids"] == {"gclid": "G1", "fbclid": "F1", "li_fat_id": "L1", "wbraid": "W1"} and e["session_id"] == "s1"
    ok = rules.clean_event({"type": "scroll", "value": 75, "url": url, "consent": True}, visitor="v1", ip="", ua="", now=NOW)
    assert ok["value"] == 75
    assert rules.clean_event({"type": "scroll", "value": 63, "url": url, "consent": True}, visitor="v1", ip="", ua="", now=NOW) is None
    d = rules.clean_event({"type": "file_download", "url": url, "consent": True, "target": "https://bimwavesolutions.com/b.pdf",
                           "label": "Brochure"}, visitor="v1", ip="", ua="", now=NOW)
    assert d["target"].endswith("b.pdf") and d["label"] == "Brochure"
    assert rules.clean_event({"type": "page_view", "url": url, "consent": True}, visitor="", ip="", ua="", now=NOW) is None


def test_first_touch_attribution_is_cleaned():
    a = rules.attribution({"utm_source": "linkedin", "gclid": "G", "landing": "https://x/", "referrer": "https://g/",
                           "r": "tok", "ts": "2026-10-25T00:00:00Z", "evil": "drop", "utm_campaign": ""})
    assert a == {"utm_source": "linkedin", "gclid": "G", "landing": "https://x/", "referrer": "https://g/",
                 "ts": "2026-10-25T00:00:00Z", "mail_token": True}
    assert rules.attribution("nope") == {}


def test_tracker_script_identifies_only_after_consent():
    from routers import web_tracking
    js = web_tracking._JS
    assert "if(consent)identify();" in js and "identify();" in js.split("function grant(){", 1)[1].split("}", 1)[0]
    assert "if(!consent&&t!=='page_view'&&t!=='consent')return;" in js
    for t in ("outbound_click", "file_download", "tel_click", "whatsapp_click", "email_click", "form_abandon"):
        assert f"'{t}'" in js
    assert "[25,50,75,100]" in js and "if(!ck(AK))sc(AK" in js
