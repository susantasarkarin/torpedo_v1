"""Ops Project -> Survey -> Supplier API (routers/ops_surveys.py).

Runs against the in-memory fake (tests/_fakemongo.py). No network, no real DB.
"""
from datetime import datetime, timedelta

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.ops_surveys as ops
from session_state import verify_session
from tests._fakemongo import FakeCollection, FakeDB

SURVEY_BODY = {
    "surveyName": "Survey One",
    "surveyUrl": "https://example.com/survey",
    "targetN": 100,
    "loi": 10,
    "ir": 20,
    "countryCode": "IN",
    "languageCode": "en",
}
PROJECT_BODY = {
    "projectName": "Project A",
    "projectNumber": "P-001",
    "managerId": "manager1",
    "fieldworkDatetime": "2026-12-01T10:00:00+05:30",
    "timezone": "Asia/Kolkata",
}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("RBAC_ENABLED", "false")
    db = FakeDB()
    traffic = FakeCollection()
    admin = {"on": False}
    monkeypatch.setattr(ops, "_db", lambda: db)
    monkeypatch.setattr(ops, "_traffic_col", lambda: traffic)
    monkeypatch.setattr(ops, "_is_admin", lambda user: admin["on"])
    app = FastAPI()
    app.include_router(ops.router)
    app.dependency_overrides[verify_session] = lambda: "tester"
    return {"db": db, "traffic": traffic, "admin": admin, "client": TestClient(app)}


def _seed_vendor(db, vid, name, status="active"):
    db["vendors"].insert_one({"vid": vid, "vendorName": name, "vendorType": "panel", "status": status})


def _project(client, number="P-001"):
    r = client.post("/api/ops/projects", json={**PROJECT_BODY, "projectNumber": number})
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


def _survey(client, pid, **over):
    r = client.post(f"/api/ops/projects/{pid}/surveys", json={**SURVEY_BODY, **over})
    assert r.status_code == 200, r.text
    return r.json()["survey"]


def _rec(traffic, surveyNo, vendor, status, minutes=None, completed_ago_h=1):
    t0 = datetime.utcnow() - timedelta(hours=completed_ago_h + 1)
    doc = {"params": {"api": "false", "pid": surveyNo}, "vendorId": vendor,
           "status": status, "createdAt": t0, "respondentId": f"r{len(traffic.docs)}"}
    if minutes is not None:
        doc["completedAt"] = t0 + timedelta(minutes=minutes)
    traffic.insert_one(doc)


def test_duplicate_project_number_409(env):
    c = env["client"]
    _project(c, "P-DUP")
    r = c.post("/api/ops/projects", json={**PROJECT_BODY, "projectNumber": "P-DUP"})
    assert r.status_code == 409


def test_create_survey_validation_422(env):
    c = env["client"]
    pid = _project(c)
    bad_cases = [
        {"surveyUrl": "ftp://nope.example"},
        {"surveyUrl": "not a url"},
        {"targetN": 0},
        {"targetN": 2.5},
        {"ir": 150},
        {"loi": 0},
        {"countryCode": "IND"},
        {"languageCode": "english!"},
    ]
    for case in bad_cases:
        r = c.post(f"/api/ops/projects/{pid}/surveys", json={**SURVEY_BODY, **case})
        assert r.status_code == 422, (case, r.text)
    assert env["db"]["projects"].docs == []  # nothing written on failure


def test_add_supplier_requires_existing_vendor(env):
    c = env["client"]
    _seed_vendor(env["db"], "101", "Vendor One")
    pid = _project(c)
    sid = _survey(c, pid)["id"]

    ok = c.post(f"/api/ops/surveys/{sid}/suppliers", json={"vendorIds": ["101"]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["items"][0]["vendorName"] == "Vendor One"

    unknown = c.post(f"/api/ops/surveys/{sid}/suppliers", json={"vendorIds": ["999"]})
    assert unknown.status_code == 422
    assert len(env["db"]["survey_suppliers"].docs) == 1
    assert len(env["db"]["vendors"].docs) == 1  # vendor never created


def test_duplicate_vendor_in_survey_409(env):
    c = env["client"]
    _seed_vendor(env["db"], "101", "Vendor One")
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    assert c.post(f"/api/ops/surveys/{sid}/suppliers", json={"vendorIds": ["101"]}).status_code == 200
    again = c.post(f"/api/ops/surveys/{sid}/suppliers", json={"vendorIds": ["101"]})
    assert again.status_code == 409


def test_remove_supplier_leaves_vendor(env):
    c = env["client"]
    _seed_vendor(env["db"], "101", "Vendor One")
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    sup = c.post(f"/api/ops/surveys/{sid}/suppliers", json={"vendorIds": ["101"]}).json()["items"][0]
    before = dict(env["db"]["vendors"].docs[0])

    r = c.delete(f"/api/ops/survey-suppliers/{sup['id']}")
    assert r.status_code == 200
    assert c.get(f"/api/ops/surveys/{sid}/suppliers").json()["items"] == []
    assert env["db"]["vendors"].docs[0] == before  # vendor untouched


def test_duplicate_survey_fresh_number_and_no_suppliers(env):
    c = env["client"]
    _seed_vendor(env["db"], "101", "Vendor One")
    pid = _project(c)
    original = _survey(c, pid)
    sid = original["id"]
    c.post(f"/api/ops/surveys/{sid}/status", json={"status": "live"})
    c.post(f"/api/ops/surveys/{sid}/suppliers", json={"vendorIds": ["101"]})
    before = dict(env["db"]["projects"].find_one({"_id": env["db"]["projects"].docs[0]["_id"]}))

    r = c.post(f"/api/ops/surveys/{sid}/duplicate")
    assert r.status_code == 200, r.text
    new = r.json()["survey"]
    assert new["id"] != sid
    assert new["surveyNo"] != original["surveyNo"]
    assert new["status"] == "draft"
    assert new["parentProjectId"] == pid
    assert c.get(f"/api/ops/surveys/{new['id']}/suppliers").json()["items"] == []

    after = env["db"]["projects"].docs[0]
    assert after["surveyNo"] == before["surveyNo"]
    assert after["projectStatus"] == "live"
    assert after["projectName"] == before["projectName"]


def test_per_supplier_metrics_count_only_that_vendor(env):
    c = env["client"]
    env["admin"]["on"] = True
    _seed_vendor(env["db"], "101", "Vendor One")
    _seed_vendor(env["db"], "102", "Vendor Two")
    pid = _project(c)
    survey = _survey(c, pid)
    sid, no = survey["id"], survey["surveyNo"]
    c.post(f"/api/ops/surveys/{sid}/suppliers",
           json={"vendorIds": ["101"], "buyPrice": "2.50", "currency": "INR"})
    c.post(f"/api/ops/surveys/{sid}/suppliers", json={"vendorIds": ["102"]})

    t = env["traffic"]
    _rec(t, no, "101", "Complete", minutes=10)
    _rec(t, no, "101", "Complete", minutes=20)
    _rec(t, no, "101", "Terminate")
    _rec(t, no, "102", "Complete", minutes=5)
    _rec(t, no, "102", "Complete", minutes=5)
    _rec(t, no, "102", "Complete", minutes=5)
    _rec(t, no, "102", "Complete", minutes=5)
    _rec(t, no, "102", "Complete", minutes=5)
    _rec(t, no, "999", "Complete", minutes=5)  # unrelated vendor, same survey number
    _rec(t, "OTHER", "101", "Complete", minutes=5)  # different survey number

    items = {i["vendorId"]: i for i in c.get(f"/api/ops/surveys/{sid}/suppliers").json()["items"]}
    assert items["101"]["entrants"] == 3
    assert items["101"]["completes"] == 2
    assert items["101"]["terms"] == 1
    assert items["101"]["completesWindow"] == 2
    assert items["101"]["expense"] == 5.0
    assert items["101"]["expenseBasis"] == "completes*buyPrice"
    assert items["102"]["completes"] == 5
    assert items["102"]["expense"] is None and items["102"]["expenseBasis"] is None


def test_price_change_requires_admin(env):
    c = env["client"]
    _seed_vendor(env["db"], "101", "Vendor One")
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    sup = c.post(f"/api/ops/surveys/{sid}/suppliers", json={"vendorIds": ["101"]}).json()["items"][0]
    r = c.put(f"/api/ops/survey-suppliers/{sup['id']}", json={"buyPrice": "3.00"})
    assert r.status_code == 403


def test_change_log_written(env):
    c = env["client"]
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    assert c.put(f"/api/ops/surveys/{sid}", json={"targetN": 200}).status_code == 200

    items = c.get(f"/api/ops/surveys/{sid}/change-log").json()["items"]
    assert any(i["action"] == "survey.update" and i["field"] == "targetN" and i["new"] == 200
               for i in items)
    assert any(i["action"] == "survey.create" for i in c.get(
        f"/api/ops/projects/{pid}/change-log").json()["items"] + items)


def test_traffic_export_is_audited(env):
    c = env["client"]
    _seed_vendor(env["db"], "101", "Vendor One")
    pid = _project(c)
    survey = _survey(c, pid)
    _rec(env["traffic"], survey["surveyNo"], "101", "Complete", minutes=3)
    r = c.get(f"/api/ops/surveys/{survey['id']}/traffic-report?format=json")
    assert r.status_code == 200
    assert r.json()["respondents"][0]["respondentId"] is not None
    assert "email" not in r.json()["respondentColumns"]  # non-admin: no PII columns
    logs = c.get(f"/api/ops/surveys/{survey['id']}/change-log").json()["items"]
    assert any(i["action"] == "traffic.export" for i in logs)


def test_project_list_counts_and_sort(env):
    c = env["client"]
    _project(c, "P-1")
    _project(c, "P-2")
    body = c.get("/api/ops/projects?sort=completes&order=desc").json()
    assert body["total"] == 2
    assert body["counts"]["all"] == 2 and body["counts"]["live"] == 2
    assert {i["projectNumber"] for i in body["items"]} == {"P-1", "P-2"}


# ============================================================ metric definitions

def _raw_row(traffic, no, vendor, status, created):
    traffic.insert_one({"params": {"api": "false", "pid": no}, "vendorId": vendor, "status": status,
                        "createdAt": created, "respondentId": f"r{len(traffic.docs)}"})


def test_inflight_vs_abandon_split_by_age(env, monkeypatch):
    monkeypatch.setenv("OPS_INFLIGHT_MINUTES", "60")
    c, traffic = env["client"], env["traffic"]
    pid = _project(c)
    s = _survey(c, pid)
    now = datetime.utcnow()
    _raw_row(traffic, s["surveyNo"], "v1", "INCOMPLETE", now - timedelta(minutes=10))  # in-flight
    _raw_row(traffic, s["surveyNo"], "v1", "INCOMPLETE", now - timedelta(hours=3))     # abandon
    body = c.get(f"/api/ops/projects/{pid}/surveys").json()
    row = body["items"][0]
    assert (row["inFlights"], row["abandons"]) == (1, 1)
    assert body["meta"]["inflightMinutes"] == 60
    assert "inFlights" not in body["meta"]["unverifiedMetrics"]
    assert "abandons" not in body["meta"]["unverifiedMetrics"]

    monkeypatch.setenv("OPS_INFLIGHT_MINUTES", "300")  # the 3h-old row is now in-flight
    row = c.get(f"/api/ops/projects/{pid}/surveys").json()["items"][0]
    assert (row["inFlights"], row["abandons"]) == (2, 0)


def test_defender_and_sq_terms_count_only_their_statuses(env):
    c, traffic = env["client"], env["traffic"]
    pid = _project(c)
    s = _survey(c, pid)
    old = datetime.utcnow() - timedelta(hours=2)
    for status in ("SECURITY_TERMINATED", "TERMINATED", "OVERQUOTA", "COMPLETE", "NOT_ROUTED"):
        _raw_row(traffic, s["surveyNo"], "v1", status, old)
    row = c.get(f"/api/ops/projects/{pid}/surveys").json()["items"][0]
    assert row["defenderTerms"] == 1          # SECURITY_TERMINATED only
    assert row["terms"] == 2                  # TERMINATED + SECURITY_TERMINATED (all Terminate)
    assert row["oqs"] == 1
    assert row["sqTerms"] is None             # no stored status can define it
    assert row["abandons"] == 1               # NOT_ROUTED is non-final, not a termination
    body = c.get(f"/api/ops/projects/{pid}/surveys").json()
    assert body["meta"]["unverifiedMetrics"] == ["sqTerms"]


def test_managers_lists_active_users_without_email(env):
    c, db = env["client"], env["db"]
    db["users"].insert_one({"username": "m1", "name": "Alice", "email": "alice@example.com",
                            "roles": ["admin"], "status": "active", "password_hash": "x"})
    db["users"].insert_one({"username": "m2", "name": "Bob", "email": "bob@example.com",
                            "roles": [], "status": "inactive"})
    r = c.get("/api/ops/managers")
    assert r.status_code == 200
    assert r.json() == {"items": [{"username": "m1", "name": "Alice"}]}
    assert "example.com" not in r.text


def test_manager_change_refreshes_manager_name(env):
    c, db = env["client"], env["db"]
    pid = _project(c)
    assert c.get(f"/api/ops/projects/{pid}").json()["project"]["managerName"] == "manager1"
    db["users"].insert_one({"username": "m2", "name": "Bob Ray", "status": "active"})
    r = c.put(f"/api/ops/projects/{pid}", json={"managerId": "m2"})
    assert r.status_code == 200, r.text
    assert r.json()["project"]["managerId"] == "m2"
    assert r.json()["project"]["managerName"] == "Bob Ray"
    r = c.put(f"/api/ops/projects/{pid}", json={"managerId": "ghost"})
    assert r.status_code == 422
    assert r.json()["detail"] == "managerId is not a known user"


def test_search_supplier_hits_carry_survey_and_parent(env):
    c, db, traffic = env["client"], env["db"], env["traffic"]
    _seed_vendor(db, "v1", "Acme Panel")
    pid = _project(c)
    s = _survey(c, pid)
    r = c.post(f"/api/ops/surveys/{s['id']}/suppliers", json={"vendorIds": ["v1"]})
    assert r.status_code == 200, r.text
    db["survey_suppliers"].insert_one({"surveyId": str(ObjectId()), "vendorId": "v9",
                                       "vendorName": "Acme Orphan", "removed": False})
    hits = c.get("/api/ops/search", params={"q": "Acme"}).json()["suppliers"]
    linked = next(h for h in hits if h["vendorId"] == "v1")
    assert linked["surveyId"] == s["id"]
    assert linked["surveyNo"] == s["surveyNo"]
    assert linked["parentProjectId"] == pid
    assert linked["vendorName"] == "Acme Panel"
    orphan = next(h for h in hits if h["vendorId"] == "v9")
    assert orphan["parentProjectId"] is None
    assert orphan["surveyNo"] is None
    sr = c.get("/api/ops/search", params={"q": s["surveyNo"]}).json()["surveys"]
    assert sr[0]["parentProjectId"] == pid


def test_test_link_returns_stored_url_only(env):
    c, db, traffic = env["client"], env["db"], env["traffic"]
    pid = _project(c)
    s = _survey(c, pid, surveyUrl="https://example.com/survey?x=1&y=2")
    r = c.get(f"/api/ops/surveys/{s['id']}/test-link")
    assert r.status_code == 200
    assert r.json() == {"url": "https://example.com/survey?x=1&y=2"}
    assert traffic.docs == []  # records no traffic

    db["projects"].update_one({"_id": ObjectId(s["id"])}, {"$set": {"liveLink": "javascript:alert(1)"}})
    r = c.get(f"/api/ops/surveys/{s['id']}/test-link")
    assert r.status_code == 404
    assert r.json()["detail"] == "No survey URL set"


def test_validation_message_is_one_readable_line():
    msg = ops._validation_message([{"loc": ("body", "managerId"), "msg": "Field required"},
                                   {"loc": ("body",), "msg": "bad body"}])
    assert msg == "managerId: Field required; request: bad body"
