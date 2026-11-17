"""Ops research API (routers/ops_research.py) and pricing-role rules in routers/ops_surveys.py.

Runs against the in-memory fake (tests/_fakemongo.py). No network, no real DB.
"""
import copy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.ops_research as research
import routers.ops_surveys as ops
from session_state import verify_session
from tests._fakemongo import FakeCollection, FakeDB

IST = ZoneInfo("Asia/Kolkata")

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


class _Counters(FakeCollection):
    """Stand-in for the atomic survey-number counter (the fake has no find_one_and_update)."""

    def find_one_and_update(self, q, upd, upsert=False, return_document=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                for k, v in upd["$inc"].items():
                    d[k] = d.get(k, 0) + v
                return copy.deepcopy(d)
        self.insert_one({**q, **upd["$inc"]})
        return copy.deepcopy(self.docs[-1])


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("RBAC_ENABLED", "false")
    db = FakeDB()
    db[ops.COL_COUNTERS] = _Counters()
    traffic = FakeCollection()
    admin = {"on": False}
    monkeypatch.setattr(ops, "_db", lambda: db)
    monkeypatch.setattr(ops, "_traffic_col", lambda: traffic)
    monkeypatch.setattr(ops, "_is_admin", lambda user: admin["on"])
    app = FastAPI()
    app.include_router(ops.router)
    app.include_router(research.router)
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


def _legacy(db, no, vendor, status="live", deleted=False):
    doc = {"surveyNo": no, "vendorId": vendor, "projectStatus": status,
           "projectName": f"Legacy {no}", "is_deleted": deleted}
    return str(db["projects"].insert_one(doc).inserted_id)


def _link(client, db, sid, vendor, no, **extra):
    """Seeds the legacy traffic doc and attaches it as a participation via the API."""
    _legacy(db, no, vendor)
    r = client.post(f"/api/ops/surveys/{sid}/suppliers",
                    json={"links": [{"vendorId": vendor, "surveyNo": no}], **extra})
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def _row(traffic, no, vendor, status, rid, minutes=None, created=None, completed=None):
    created = created or (datetime.utcnow() - timedelta(hours=2))
    doc = {"params": {"api": "false", "pid": no}, "vendorId": vendor, "status": status,
           "createdAt": created, "respondentId": rid}
    if completed is not None:
        doc["completedAt"] = completed
    elif minutes is not None:
        doc["completedAt"] = created + timedelta(minutes=minutes)
    traffic.insert_one(doc)


# ============================================================ cleaning requests

def test_cleaning_request_create_list_status_history(env):
    c = env["client"]
    pid = _project(c)
    s1 = _survey(c, pid)["id"]
    s2 = _survey(c, pid, surveyName="Two")["id"]

    r = c.post(f"/api/ops/projects/{pid}/cleaning-requests",
               json={"surveyIds": [s1, s2, s1], "notes": "check dupes"})
    assert r.status_code == 200, r.text
    req = r.json()["request"]
    assert req["status"] == "submitted"
    assert req["surveyIds"] == [s1, s2]  # de-duplicated
    assert req["requestedBy"] == "tester"
    assert req["history"][0]["status"] == "submitted"
    rid = req["id"]

    second = c.post(f"/api/ops/projects/{pid}/cleaning-requests", json={"surveyIds": [s2]}).json()["request"]
    items = c.get(f"/api/ops/projects/{pid}/cleaning-requests").json()["items"]
    assert {i["id"] for i in items} == {rid, second["id"]}
    assert items[0]["createdAt"] >= items[1]["createdAt"]  # newest first

    st = c.post(f"/api/ops/cleaning-requests/{rid}/status", json={"status": "in_progress", "note": "started"})
    assert st.status_code == 200, st.text
    hist = st.json()["request"]["history"]
    assert [h["status"] for h in hist] == ["submitted", "in_progress"]
    assert hist[1]["note"] == "started" and hist[1]["user"] == "tester"
    assert st.json()["request"]["status"] == "in_progress"

    assert c.post(f"/api/ops/cleaning-requests/{rid}/status", json={"status": "bogus"}).status_code == 422

    actions = [i["action"] for i in c.get(f"/api/ops/projects/{pid}/change-log").json()["items"]]
    assert "cleaning.create" in actions and "cleaning.status" in actions


def test_cleaning_request_rejects_survey_from_other_project(env):
    c = env["client"]
    pa = _project(c, "P-A")
    pb = _project(c, "P-B")
    foreign = _survey(c, pb)["id"]
    r = c.post(f"/api/ops/projects/{pa}/cleaning-requests", json={"surveyIds": [foreign]})
    assert r.status_code == 422
    assert env["db"]["ops_cleaning_requests"].docs == []


# ============================================================ reconciliations

def test_reconciliation_counts_split_and_traffic_untouched(env):
    c, db, t = env["client"], env["db"], env["traffic"]
    _seed_vendor(db, "101", "Vendor One")
    _seed_vendor(db, "102", "Vendor Two")
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    _link(c, db, sid, "101", "L1")
    _link(c, db, sid, "102", "L2")
    _row(t, "L1", "101", "Complete", "r1", minutes=10)
    _row(t, "L1", "101", "Complete", "r2", minutes=10)
    _row(t, "L1", "101", "Terminate", "r3")
    _row(t, "L2", "102", "Complete", "r4", minutes=5)
    _row(t, "L2", "102", "Complete", "r5", minutes=5)
    _row(t, "L2", "102", "Quota Full", "r6")
    _row(t, "OTHER", "101", "Complete", "r1", minutes=5)  # no participation has this pid
    before = [dict(d) for d in t.docs]

    r = c.post(f"/api/ops/projects/{pid}/reconciliations", json={
        "surveyId": sid,
        "acceptedIds": ["r1", " r4 ", "r3", "ghost", "r1"],
        "rejectedIds": ["r5"],
        "note": "wk1",
    })
    assert r.status_code == 200, r.text
    rec = r.json()["reconciliation"]
    assert rec["counts"] == {
        "ourCompletes": 4,
        "accepted": 4,
        "rejected": 1,
        "acceptedMatched": 2,       # r1, r4
        "acceptedNotFound": 1,      # ghost
        "acceptedNotComplete": 1,   # r3 (terminate only)
        "completesNotInClientFile": 2,  # r2, r5
        "reconciledCompletes": 2,
    }
    by = {b["vendorId"]: b for b in rec["bySupplier"]}
    keys = ("vendorName", "surveyNo", "ourCompletes", "reconciledCompletes", "rejected")
    assert {k: by["101"][k] for k in keys} == {"vendorName": "Vendor One", "surveyNo": "L1", "ourCompletes": 2,
                                               "reconciledCompletes": 1, "rejected": 0}
    assert {k: by["102"][k] for k in keys} == {"vendorName": "Vendor Two", "surveyNo": "L2", "ourCompletes": 2,
                                               "reconciledCompletes": 1, "rejected": 1}
    assert rec["unmatchedIds"] == ["r3", "ghost"]
    assert rec["rejectedIds"] == ["r5"]
    assert t.docs == before  # no traffic row modified

    listed = c.get(f"/api/ops/projects/{pid}/reconciliations").json()["items"]
    assert len(listed) == 1 and "unmatchedIds" not in listed[0] and "rejectedIds" not in listed[0]
    full = c.get(f"/api/ops/reconciliations/{rec['id']}").json()["reconciliation"]
    assert full["unmatchedIds"] == ["r3", "ghost"]
    assert any(i["action"] == "reconciliation.create" for i in
               c.get(f"/api/ops/surveys/{sid}/change-log").json()["items"])


def test_reconciliation_same_vendor_two_links_are_separate_entries(env):
    c, db, t = env["client"], env["db"], env["traffic"]
    _seed_vendor(db, "101", "Vendor One")
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    _link(c, db, sid, "101", "L1")
    _link(c, db, sid, "101", "L2")
    _row(t, "L1", "101", "Complete", "x1", minutes=5)
    _row(t, "L2", "101", "Complete", "x2", minutes=5)
    rec = c.post(f"/api/ops/projects/{pid}/reconciliations",
                 json={"surveyId": sid, "acceptedIds": ["x2"]}).json()["reconciliation"]
    assert [(b["surveyNo"], b["ourCompletes"], b["reconciledCompletes"]) for b in rec["bySupplier"]] == [
        ("L1", 1, 0), ("L2", 1, 1)]
    assert rec["counts"]["ourCompletes"] == 2 and rec["counts"]["reconciledCompletes"] == 1


def test_reconciliation_validation(env):
    c = env["client"]
    pa = _project(c, "P-A")
    pb = _project(c, "P-B")
    sa = _survey(c, pa)["id"]
    foreign = _survey(c, pb)["id"]
    assert c.post(f"/api/ops/projects/{pa}/reconciliations",
                  json={"surveyId": foreign, "acceptedIds": ["x"]}).status_code == 422
    assert c.post(f"/api/ops/projects/{pa}/reconciliations",
                  json={"surveyId": sa, "acceptedIds": ["x"], "rejectedIds": ["x"]}).status_code == 422
    too_many = [f"id{i}" for i in range(100_001)]
    assert c.post(f"/api/ops/projects/{pa}/reconciliations",
                  json={"surveyId": sa, "acceptedIds": too_many}).status_code == 422
    assert env["db"]["ops_reconciliations"].docs == []


# ============================================================ report

def test_report_totals_match_surveys_and_never_sum_currencies(env):
    c, db, t = env["client"], env["db"], env["traffic"]
    env["admin"]["on"] = True
    _seed_vendor(db, "101", "Vendor One")
    pid = _project(c)
    a = _survey(c, pid, surveyName="A")
    b = _survey(c, pid, surveyName="B")
    _link(c, db, a["id"], "101", "LA", buyPrice="2.00", currency="INR")
    _link(c, db, b["id"], "101", "LB", buyPrice="3.00", currency="USD")
    _row(t, "LA", "101", "Complete", "a1", minutes=5)
    _row(t, "LA", "101", "Complete", "a2", minutes=5)
    _row(t, "LA", "101", "Terminate", "a3")
    _row(t, "LB", "101", "Complete", "b1", minutes=5)
    _row(t, "LB", "101", "Quota Full", "b2")

    rep = c.get(f"/api/ops/projects/{pid}/report").json()
    rows = rep["surveys"]
    assert rep["totals"]["entrants"] == sum(r["entrants"] for r in rows) == 5
    assert rep["totals"]["completes"] == sum(r["completes"] for r in rows) == 3
    assert rep["totals"]["terms"] == 1 and rep["totals"]["oqs"] == 1
    assert rep["totals"]["target"] == 200
    sup = {s["vendorId"]: s for s in rep["suppliers"]}["101"]
    assert sup["entrants"] == rep["totals"]["entrants"]
    assert sup["completes"] == rep["totals"]["completes"]
    assert sup["surveys"] == 2
    assert sup["expenseByCurrency"] == {"INR": 4.0, "USD": 3.0}  # 2*2.00 INR, 1*3.00 USD
    assert rep["expenseByCurrency"] == {"INR": 4.0, "USD": 3.0}
    assert rep["latestReconciliation"] == {}


def test_report_hides_pricing_from_plain_user(env):
    c, db = env["client"], env["db"]
    env["admin"]["on"] = True
    _seed_vendor(db, "101", "Vendor One")
    pid = _project(c)
    survey = _survey(c, pid)
    sid = survey["id"]
    _link(c, db, sid, "101", "L1", buyPrice="2.00", currency="INR")
    _row(env["traffic"], "L1", "101", "Complete", "p1", minutes=5)
    env["admin"]["on"] = False  # plain user: no admin, no finance role

    rep = c.get(f"/api/ops/projects/{pid}/report").json()
    assert "expenseByCurrency" not in rep
    assert all("expenseByCurrency" not in s for s in rep["suppliers"])
    assert rep["totals"]["completes"] == 1

    items = c.get(f"/api/ops/surveys/{sid}/suppliers").json()["items"]
    assert items and all(not ({"buyPrice", "currency", "expense", "expenseBasis"} & set(i)) for i in items)

    tr = c.get(f"/api/ops/surveys/{sid}/traffic-report?format=json").json()
    assert all("buyPrice" not in s and "expense" not in s for s in tr["suppliers"])
    assert "email" not in tr["respondentColumns"]  # PII still admin-only


# ============================================================ pricing roles

def test_finance_role_can_set_and_see_pricing_but_not_pii(env):
    c = env["client"]
    _seed_vendor(env["db"], "101", "Vendor One")
    env["db"]["users"].insert_one({"username": "tester", "roles": ["finance"]})
    pid = _project(c)
    sid = _survey(c, pid)["id"]

    add = c.post(f"/api/ops/surveys/{sid}/suppliers",
                 json={"vendorIds": ["101"], "buyPrice": "2.50", "currency": "USD"})
    assert add.status_code == 200, add.text
    sup_id = add.json()["items"][0]["id"]
    upd = c.put(f"/api/ops/survey-suppliers/{sup_id}", json={"buyPrice": "3.00", "currency": "EUR"})
    assert upd.status_code == 200, upd.text
    item = c.get(f"/api/ops/surveys/{sid}/suppliers").json()["items"][0]
    assert item["buyPrice"] == 3.0 and item["currency"] == "EUR"

    tr = c.get(f"/api/ops/surveys/{sid}/traffic-report?format=json").json()
    assert "email" not in tr["respondentColumns"] and tr["pii"] is False


def test_plain_user_cannot_set_pricing(env):
    c = env["client"]
    _seed_vendor(env["db"], "101", "Vendor One")
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    sup = c.post(f"/api/ops/surveys/{sid}/suppliers", json={"vendorIds": ["101"]})
    assert sup.status_code == 200
    sup_id = sup.json()["items"][0]["id"]

    assert c.post(f"/api/ops/surveys/{sid}/suppliers",
                  json={"vendorIds": ["102"], "buyPrice": "1"}).status_code == 403
    assert c.put(f"/api/ops/survey-suppliers/{sup_id}", json={"buyPrice": "3.00"}).status_code == 403
    assert c.put(f"/api/ops/survey-suppliers/{sup_id}", json={"currency": "USD"}).status_code == 403


# ============================================================ trend

def test_trend_buckets_by_ist_day(env):
    c, db, t = env["client"], env["db"], env["traffic"]
    _seed_vendor(db, "101", "Vendor One")
    _seed_vendor(db, "102", "Vendor Two")
    pid = _project(c)
    sv = _survey(c, pid)
    sid = sv["id"]
    _link(c, db, sid, "101", "L101")
    _link(c, db, sid, "102", "L102")
    now = datetime.utcnow()

    def ist(dt):
        return dt.replace(tzinfo=timezone.utc).astimezone(IST).date().isoformat()

    _row(t, "L101", "101", "Complete", "t1", created=now - timedelta(minutes=30),
         completed=now - timedelta(minutes=20))
    _row(t, "L101", "101", "Terminate", "t2", created=now - timedelta(days=2))
    _row(t, "L102", "102", "Complete", "t3", created=now - timedelta(days=1, hours=1),
         completed=now - timedelta(days=1))
    _row(t, "L102", "102", "Complete", "t4", created=now - timedelta(days=100),
         completed=now - timedelta(days=100))  # outside the window

    r = c.get(f"/api/ops/surveys/{sid}/trend?days=14").json()
    days = r["days"]
    assert len(days) == 14
    assert days[-1] == ist(now) and days[0] == ist(now - timedelta(days=13))
    s = {x["vendorId"]: x for x in r["series"]}
    assert s["101"]["vendorName"] == "Vendor One"
    assert s["101"]["surveyNo"] == "L101" and s["101"]["label"] == "Vendor One (L101)"
    assert s["101"]["entrants"][days.index(ist(now - timedelta(minutes=30)))] == 1
    assert sum(s["101"]["entrants"]) == 2
    assert sum(s["101"]["completes"]) == 1
    assert s["101"]["completes"][days.index(ist(now - timedelta(minutes=20)))] == 1
    assert sum(s["102"]["entrants"]) == 1 and sum(s["102"]["completes"]) == 1
    assert sum(r["total"]["entrants"]) == 3
    assert sum(r["total"]["completes"]) == 2
    assert r["total"]["completes"][-1] == 1

    assert c.get(f"/api/ops/surveys/{sid}/trend?days=0").status_code == 422
    assert c.get(f"/api/ops/surveys/{sid}/trend?days=91").status_code == 422


def test_report_totals_and_suppliers_split_inflight_and_abandons(env, monkeypatch):
    monkeypatch.setenv("OPS_INFLIGHT_MINUTES", "60")
    c, db, traffic = env["client"], env["db"], env["traffic"]
    _seed_vendor(db, "v1", "Panel One")
    pid = _project(c)
    s = _survey(c, pid)
    _link(c, db, s["id"], "v1", "L1")
    now = datetime.utcnow()
    _row(traffic, "L1", "v1", "INCOMPLETE", "a", created=now - timedelta(minutes=5))
    _row(traffic, "L1", "v1", "SECURITY_TERMINATED", "b", created=now - timedelta(hours=3))
    rep = c.get(f"/api/ops/projects/{pid}/report").json()
    assert rep["meta"]["inflightMinutes"] == 60
    assert rep["totals"]["inFlights"] == 1
    assert rep["totals"]["abandons"] == 0
    assert rep["totals"]["defenderTerms"] == 1
    sup = rep["suppliers"][0]
    assert (sup["inFlights"], sup["abandons"], sup["defenderTerms"]) == (1, 0, 1)
    assert rep["surveys"][0]["defenderTerms"] == 1
    assert rep["surveys"][0]["sqTerms"] == 0                 # no screener NOT_ROUTED row here
    assert rep["totals"]["sqTerms"] == 0
    assert rep["meta"]["sqTermsNote"].startswith("Screened out by our qualification")
