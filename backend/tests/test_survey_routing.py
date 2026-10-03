"""
Survey qualification & routing engine (services/survey_routing.py) and its wiring:
landing config, /api/store (pid links, router links, country, Paid Ads PII) and
re-routing after client terminate / quota-full / security terminate.
"""
from datetime import date, datetime

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.traffic as traffic
from services import survey_routing as r
from session_state import verify_session
from tests.test_respondent_quality import FakeDatabase


def _project(survey_no, country="US", qualification=None, routing=False, priority=None, **extra):
    return {"_id": ObjectId(), "surveyNo": survey_no, "projectStatus": "live", "countryCode": country,
            "liveLink": f"https://client.example/{survey_no}?rid=", "qualification": qualification or {},
            "routingEnabled": routing, "routingPriority": priority, **extra}


UNIFORM = {"enabled": True, "ageMin": 18, "ageMax": 64, "employment": ["employed_full_time", "employed_part_time"],
           "custom": [{"id": "q_uniform01", "text": "Do you wear a uniform at work?",
                       "options": ["Yes", "No"], "qualifying": ["Yes"]}]}
PROFILE_40 = {"birthday_year": date.today().year - 40, "birthday_month": 1, "birthday_day": 1, "gender": "f"}


# --- qualification -------------------------------------------------------------

def test_evaluate():
    p = _project("1", qualification=UNIFORM)
    ok_answers = {"employment": "employed_full_time", "q_uniform01": "Yes"}
    assert r.evaluate(p, ok_answers, PROFILE_40) == (True, [])
    old = {**PROFILE_40, "birthday_year": date.today().year - 70}
    assert r.evaluate(p, ok_answers, old) == (False, ["age"])
    assert r.evaluate(p, {"employment": "retired", "q_uniform01": "No"}, PROFILE_40) == (False, ["employment", "q_uniform01"])
    assert r.evaluate(p, {}, PROFILE_40)[1] == ["employment_missing", "q_uniform01_missing"]
    assert r.evaluate(_project("2"), {}, {}) == (True, [])  # no criteria = qualifies
    assert r.evaluate(_project("3", qualification={"enabled": True, "genders": ["m"]}), {}, PROFILE_40) == (False, ["gender"])


def test_bad_criteria_are_ignored_not_trusted():
    q = r.project_qualification({"qualification": {"enabled": True, "employment": ["ceo", "retired"],
                                                   "custom": [{"id": "bad id", "text": "x", "options": ["a"], "qualifying": ["a"]}]}})
    assert q["employment"] == ["retired"] and q["custom"] == []


def test_questions_for_dedupes_across_projects():
    qs = r.questions_for([_project("1", qualification=UNIFORM), _project("2", qualification=UNIFORM),
                          _project("3", qualification={"enabled": False, "occupation": ["retail"]})])
    assert [q["id"] for q in qs] == ["employment", "q_uniform01"]


def test_clean_pii():
    assert r.clean_pii({"firstName": "A", "lastName": "B", "email": "a@b.co", "phone": "+91 98765 43210"})[1]
    pii, err = r.clean_pii({"firstName": "Asha", "lastName": "Rao", "email": "Asha@Example.com",
                            "phone": "+91 98765 43210", "consent": True})
    assert err == "" and pii["email"] == "asha@example.com" and pii["panelConsent"]["given"] is True
    assert pii["panelConsent"]["policyUrl"].startswith("https://")


# --- wiring ----------------------------------------------------------------------

@pytest.fixture
def env(monkeypatch):
    for var in ("SURVEY_ROUTING_ENABLED", "COUNTRY_ROUTING_ENABLED", "ROUTING_MAX_ATTEMPTS",
                "SFW_SCORE_ENABLED", "META_PIXEL_ID"):
        monkeypatch.delenv(var, raising=False)
    r._FULL_CACHE.clear()
    db = FakeDatabase()
    url_col, projects, vendors = db["url_parameters"], db["projects"], db["vendors"]
    vendors.docs.append({"vid": "5068", "vendorName": "Research Desk", "vendorType": "DIY Platform",
                         "vendorVariable": "id", "terminateRD": ["https://vendor.example/term?x=1"],
                         "completeRD": ["https://vendor.example/done?x=1"]})
    vendors.docs.append({"vid": "5725", "vendorName": "Facebook Ads", "vendorType": "Paid Ads", "adPlatform": "meta",
                         "vendorVariable": "rid", "completeRD": ["https://torpedo.example/adpixel?rid="]})

    async def resolve_live(pid):
        return next((p for p in projects.docs if p["surveyNo"] == str(pid) and p.get("projectStatus") == "live"), None)

    async def client_var(_doc):
        return ""

    monkeypatch.setattr(traffic, "get_async_url_parameters_collection", lambda: url_col)
    monkeypatch.setattr(traffic, "get_async_vendors_collection", lambda: vendors)
    monkeypatch.setattr(traffic, "get_async_collection", lambda _db, _col: projects)
    monkeypatch.setattr(traffic, "url_parameters_collection", object())
    monkeypatch.setattr(traffic, "traffic_service", None)
    monkeypatch.setattr(traffic, "_resolve_live_project_async", resolve_live)
    monkeypatch.setattr(traffic, "_resolve_project_client_variable_async", client_var)

    app = FastAPI()
    app.include_router(traffic.router)
    app.dependency_overrides[verify_session] = lambda: "test-user"
    return TestClient(app), url_col, projects, db


def _store(client, pid="80419", vid="5068", rid="v-1", country="US", answers=None, pii=None, route=False, visitor="visitor-0001", **params):
    p = {"api": "false", "vid": vid, "cc": "US", "rid": rid, **params}
    if route:
        p["route"] = "1"
    else:
        p["pid"] = pid
    body = {"params": p, "clientIp": "1.2.3.4", "sfwVisitorId": visitor, "qualification": answers or {},
            "birthday_day": 1, "birthday_month": 1, "birthday_year": date.today().year - 40, "gender": "f"}
    if pii:
        body["pii"] = pii
    return client.post("/api/store", json=body, headers={"CF-IPCountry": country})


def test_pid_link_without_criteria_is_unchanged(env):
    client, url_col, projects, _ = env
    projects.docs.append(_project("80419"))
    out = _store(client).json()
    assert out["allocation_success"] and out["survey_id"] == "80419"
    rec = url_col.docs[0]
    assert rec["assignedSurveyId"] == "80419" and "prescreen" not in rec and "routingSessionId" not in rec


def test_pid_link_prescreen_pass(env):
    client, url_col, projects, _ = env
    projects.docs.append(_project("80419", qualification=UNIFORM))
    out = _store(client, answers={"employment": "employed_full_time", "q_uniform01": "Yes"}).json()
    assert out["allocation_success"]
    assert url_col.docs[0]["prescreen"]["passed"] is True


def test_pid_link_prescreen_fail_without_routing_terminates(env):
    client, url_col, projects, _ = env
    projects.docs.append(_project("80419", qualification=UNIFORM))
    out = _store(client, answers={"employment": "retired", "q_uniform01": "No"}).json()
    assert out["allocation_success"] is False
    assert out["redirect_url"].startswith("https://vendor.example/term")  # vendor terminate
    rec = url_col.docs[0]
    assert rec["status"] == "NOT_ROUTED" and rec["prescreen"]["reasons"] == ["employment", "q_uniform01"]


def test_pid_link_prescreen_fail_routes_to_next_eligible(env, monkeypatch):
    client, url_col, projects, db = env
    monkeypatch.setenv("SURVEY_ROUTING_ENABLED", "true")
    projects.docs += [_project("80419", qualification=UNIFORM),
                      _project("70001", routing=True, priority=2),
                      _project("70002", routing=True, priority=1, qualification={"enabled": True, "ageMax": 30}),
                      _project("70003", routing=True, priority=3)]
    out = _store(client, answers={"employment": "retired", "q_uniform01": "No"}).json()
    # 70002 has priority 1 but she's 40 -> 70001 (priority 2)
    assert out["allocation_success"] and out["survey_id"] == "70001"
    rec = url_col.docs[0]
    assert (rec["assignedSurveyId"], rec["params"]["pid"], rec["routedFrom"], rec["entryPid"]) == ("70001", "70001", "80419", "80419")
    session = db["routing_sessions"].docs[0]
    assert session["tried"] == ["70001"] and session["attempts"][0]["reason"] == "prescreen_fail"


def test_country_mismatch_routes_to_respondents_country(env, monkeypatch):
    client, url_col, projects, _ = env
    monkeypatch.setenv("SURVEY_ROUTING_ENABLED", "true")
    monkeypatch.setenv("COUNTRY_ROUTING_ENABLED", "true")
    projects.docs += [_project("80419", country="US"), _project("90001", country="IN", routing=True),
                      _project("90002", country="US", routing=True)]
    out = _store(client, country="IN").json()
    assert out["survey_id"] == "90001"
    assert url_col.docs[0]["prescreen"]["reasons"] == ["country"]


def test_country_mismatch_without_routing_terminates(env, monkeypatch):
    client, _, projects, _ = env
    monkeypatch.setenv("COUNTRY_ROUTING_ENABLED", "true")
    projects.docs.append(_project("80419", country="US"))
    assert _store(client, country="GB").json()["allocation_success"] is False


def test_router_link_priority_full_and_already_entered(env, monkeypatch):
    client, url_col, projects, _ = env
    monkeypatch.setenv("SURVEY_ROUTING_ENABLED", "true")
    projects.docs += [_project("1", routing=True, priority=1, totalCompletesRequired="1"),
                      _project("2", routing=True, priority=2),
                      _project("3", routing=True, priority=3)]
    url_col.docs.append({"_id": ObjectId(), "params": {"pid": "1", "api": "false"}, "status": "COMPLETE"})  # 1 is full
    url_col.docs.append({"_id": ObjectId(), "assignedSurveyId": "2", "sfwVisitorId": "visitor-0001", "status": "TERMINATED"})
    out = _store(client, route=True).json()
    assert out["survey_id"] == "3"


def test_router_link_off_without_switch(env):
    client, _, projects, _ = env
    projects.docs.append(_project("1", routing=True))
    assert _store(client, route=True).json()["allocation_success"] is False


def test_paid_ads_requires_pii_and_consent(env):
    client, url_col, projects, _ = env
    projects.docs.append(_project("65806", country="US"))
    resp = _store(client, pid="65806", vid="5725", rid="", utm_source="meta")
    assert resp.status_code == 400 and "name" in resp.json()["detail"]
    no_consent = {"firstName": "Asha", "lastName": "Rao", "email": "asha@example.com", "phone": "+15551234567"}
    assert _store(client, pid="65806", vid="5725", rid="ad-1", pii=no_consent).status_code == 400
    ok = _store(client, pid="65806", vid="5725", rid="ad-1", pii={**no_consent, "consent": True})
    assert ok.json()["allocation_success"]
    rec = url_col.docs[-1]
    assert (rec["email"], rec["firstName"], rec["phone"], rec["paidAds"]) == ("asha@example.com", "Asha", "+15551234567", True)
    assert rec["panelConsent"]["given"] is True


def test_non_paid_traffic_never_asked_for_pii(env):
    client, url_col, projects, _ = env
    projects.docs.append(_project("80419"))
    assert _store(client).json()["allocation_success"]
    assert "firstName" not in url_col.docs[0]


# --- re-routing after the client's redirect ---------------------------------------

def _routed_start(env, monkeypatch, n_projects=4):
    client, url_col, projects, db = env
    monkeypatch.setenv("SURVEY_ROUTING_ENABLED", "true")
    projects.docs += [_project(str(100 + i), routing=True, priority=i) for i in range(1, n_projects + 1)]
    out = _store(client, route=True).json()
    return client, url_col, db, out["id"]


def test_terminate_routes_to_next_then_stops_after_three(env, monkeypatch):
    client, url_col, db, rid1 = _routed_start(env, monkeypatch)
    resp = client.get("/surveyterminate", params={"rid": rid1}, follow_redirects=False)
    assert resp.headers["location"].startswith("https://client.example/102?rid=")
    rid2 = resp.headers["location"].split("rid=")[1]
    attempt2 = next(d for d in url_col.docs if str(d["_id"]) == rid2)
    assert (attempt2["routingAttempt"], attempt2["routedFrom"], attempt2["respondentId"]) == (2, "101", "v-1")

    resp = client.get("/surveyquotafull", params={"rid": rid2}, follow_redirects=False)
    assert resp.headers["location"].startswith("https://client.example/103?rid=")
    rid3 = resp.headers["location"].split("rid=")[1]

    resp = client.get("/surveyterminate", params={"rid": rid3}, follow_redirects=False)
    assert resp.headers["location"].startswith("https://vendor.example/term")  # 3 attempts used: final
    session = db["routing_sessions"].docs[0]
    assert [a["outcome"] for a in session["attempts"]] == ["TERMINATED", "OVERQUOTA", "TERMINATED"]
    assert session["final"]["outcome"] == "TERMINATED"


def test_complete_stops_routing(env, monkeypatch):
    client, _, db, rid1 = _routed_start(env, monkeypatch)
    resp = client.get("/surveycomplete", params={"rid": rid1}, follow_redirects=False)
    assert resp.headers["location"].startswith("https://vendor.example/done")
    assert db["routing_sessions"].docs[0]["final"]["outcome"] == "COMPLETE"


def test_security_terminate_is_final(env, monkeypatch):
    client, url_col, db, rid1 = _routed_start(env, monkeypatch)
    resp = client.get("/surveysecurity", params={"rid": rid1}, follow_redirects=False)
    assert resp.headers["location"].startswith("https://vendor.example/term")
    assert url_col.docs[0]["status"] == "SECURITY_TERMINATED"
    assert db["routing_sessions"].docs[0]["final"]["outcome"] == "SECURITY_TERMINATED"
    assert len([d for d in url_col.docs if d.get("routingAttempt")]) == 1  # no new attempt


def test_security_via_terminate_type_param(env, monkeypatch):
    """The URL clients get: /surveyterminate?rid=..&type=security (nginx already proxies it)."""
    client, url_col, db, rid1 = _routed_start(env, monkeypatch)
    resp = client.get("/surveyterminate", params={"rid": rid1, "type": "security"}, follow_redirects=False)
    assert resp.headers["location"].startswith("https://vendor.example/term")
    assert url_col.docs[0]["status"] == "SECURITY_TERMINATED"
    assert len([d for d in url_col.docs if d.get("routingAttempt")]) == 1


def test_no_more_eligible_surveys_ends_at_vendor(env, monkeypatch):
    client, _, _, rid1 = _routed_start(env, monkeypatch, n_projects=1)
    resp = client.get("/surveyterminate", params={"rid": rid1}, follow_redirects=False)
    assert resp.headers["location"].startswith("https://vendor.example/term")


# --- landing config --------------------------------------------------------------

def test_landing_config(env, monkeypatch):
    client, _, projects, _ = env
    projects.docs.append(_project("80419", qualification=UNIFORM))
    cfg = client.get("/api/routing/landing", params={"pid": "80419", "vid": "5068"}, headers={"CF-IPCountry": "US"}).json()
    assert cfg["country"] == "US" and [q["id"] for q in cfg["questions"]] == ["employment", "q_uniform01"]
    assert cfg["pii"] == {"required": False}
    paid = client.get("/api/routing/landing", params={"pid": "80419", "vid": "5725"}).json()
    assert paid["pii"]["required"] is True and "panel" in paid["pii"]["consentText"]
