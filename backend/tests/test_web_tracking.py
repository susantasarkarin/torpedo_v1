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
    e = rules.clean_event({"type": "page_view", "url": "https://www.surveyfieldwork.com/pricing?utm_source=li&x=1"},
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
