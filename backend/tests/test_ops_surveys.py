"""Ops Project -> Survey -> Supplier API (routers/ops_surveys.py).

Schema under test: ops_projects -> ops_surveys -> survey_suppliers -> legacy projects doc
(one legacy doc = one supplier traffic link, pid = surveyNo).

Runs against the in-memory fake (tests/_fakemongo.py). No network, no real DB.
"""
import copy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

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
# No projectNumber: the system allocates it (P001, P002, ...).
PROJECT_BODY = {
    "projectName": "Project A",
    "managerId": "manager1",
    "fieldworkDatetime": "2026-12-01T10:00:00+05:30",
    "timezone": "Asia/Kolkata",
}
IST = ZoneInfo("Asia/Kolkata")


class _Counters(FakeCollection):
    """Stand-in for the atomic counter: the fake has no find_one_and_update."""

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
    app.dependency_overrides[verify_session] = lambda: "tester"
    return {"db": db, "traffic": traffic, "admin": admin, "client": TestClient(app)}


def _seed_vendor(db, vid, name, status="active"):
    db["vendors"].insert_one({"vid": vid, "vendorName": name, "vendorType": "panel", "status": status})


class _UniqueProjects(FakeCollection):
    """Enforces the unique projectNumber index that the real collection has."""

    def insert_one(self, doc):
        if any(d.get("projectNumber") == doc.get("projectNumber") for d in self.docs):
            raise DuplicateKeyError("E11000 duplicate key error (projectNumber)")
        return super().insert_one(doc)


def _project(client):
    r = client.post("/api/ops/projects", json=PROJECT_BODY)
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


def _number(client, pid):
    return client.get(f"/api/ops/projects/{pid}").json()["project"]["projectNumber"]


def _survey(client, pid, **over):
    r = client.post(f"/api/ops/projects/{pid}/surveys", json={**SURVEY_BODY, **over})
    assert r.status_code == 200, r.text
    return r.json()["survey"]


def _legacy(db, no, vendor, status="live", deleted=False):
    """A legacy projects doc = one supplier traffic link."""
    doc = {"surveyNo": no, "vendorId": vendor, "projectStatus": status,
           "projectName": f"Legacy {no}", "is_deleted": deleted}
    return str(db["projects"].insert_one(doc).inserted_id)


def _link(client, db, sid, vendor, no, **extra):
    """Seeds the legacy doc and attaches it as a participation via the API."""
    _legacy(db, no, vendor)
    r = client.post(f"/api/ops/surveys/{sid}/suppliers",
                    json={"links": [{"vendorId": vendor, "surveyNo": no}], **extra})
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def _rec(traffic, surveyNo, vendor, status, minutes=None, completed_ago_h=1):
    t0 = datetime.utcnow() - timedelta(hours=completed_ago_h + 1)
    doc = {"params": {"api": "false", "pid": surveyNo}, "vendorId": vendor,
           "status": status, "createdAt": t0, "respondentId": f"r{len(traffic.docs)}"}
    if minutes is not None:
        doc["completedAt"] = t0 + timedelta(minutes=minutes)
    traffic.insert_one(doc)


def _raw_row(traffic, no, vendor, status, created):
    traffic.insert_one({"params": {"api": "false", "pid": no}, "vendorId": vendor, "status": status,
                        "createdAt": created, "respondentId": f"r{len(traffic.docs)}"})


def test_project_number_allocated_in_sequence(env):
    c = env["client"]
    a, b = _project(c), _project(c)
    assert _number(c, a) == "P001"
    assert _number(c, b) == "P002"


def test_first_number_continues_from_existing_max(env):
    c, db = env["client"], env["db"]
    for n in ("P223", "P007", "X999", "P-5"):  # only P<digits> counts toward the max
        db[ops.COL_OPS_PROJECTS].insert_one({"projectName": n, "projectNumber": n, "is_deleted": False})
    assert _number(c, _project(c)) == "P224"


def test_supplied_project_number_is_ignored(env):
    c = env["client"]
    r = c.post("/api/ops/projects", json={**PROJECT_BODY, "projectNumber": "P-HACK"})
    assert r.status_code == 200, r.text
    assert r.json()["project"]["projectNumber"] == "P001"


def test_number_clash_retries_with_next_number(env):
    c, db = env["client"], env["db"]
    db[ops.COL_OPS_PROJECTS] = _UniqueProjects()
    db[ops.COL_COUNTERS].insert_one({"_id": ops.PROJECT_NUMBER_KEY, "seq": 0})  # counter behind data
    db[ops.COL_OPS_PROJECTS].insert_one({"projectName": "Old", "projectNumber": "P001", "is_deleted": False})
    assert _number(c, _project(c)) == "P002"


def test_default_manager_and_timezone_applied(env, monkeypatch):
    monkeypatch.delenv("OPS_DEFAULT_MANAGER_ID", raising=False)
    monkeypatch.delenv("OPS_DEFAULT_MANAGER_NAME", raising=False)
    c = env["client"]
    r = c.post("/api/ops/projects", json={"projectName": "Name only"})
    assert r.status_code == 200, r.text
    proj = r.json()["project"]
    assert proj["managerId"] == "susanta.sarkar"
    assert proj["managerName"] == "Susanta Sarkar"
    assert proj["timezone"] == "Asia/Kolkata"


def test_default_manager_name_from_env(env, monkeypatch):
    monkeypatch.setenv("OPS_DEFAULT_MANAGER_ID", "ops.lead")
    monkeypatch.setenv("OPS_DEFAULT_MANAGER_NAME", "Ops Lead")
    c = env["client"]
    proj = c.post("/api/ops/projects", json={"projectName": "Env"}).json()["project"]
    assert (proj["managerId"], proj["managerName"]) == ("ops.lead", "Ops Lead")


def test_other_manager_is_looked_up_in_users(env):
    c, db = env["client"], env["db"]
    db[ops.COL_USERS].insert_one({"username": "manager1", "name": "Manager One"})
    proj = c.post("/api/ops/projects", json={**PROJECT_BODY, "managerId": "manager1"}).json()["project"]
    assert (proj["managerId"], proj["managerName"]) == ("manager1", "Manager One")


def test_fieldwork_defaults_to_now_in_india_time(env):
    c = env["client"]
    before = datetime.now(IST).replace(microsecond=0)
    r = c.post("/api/ops/projects", json={"projectName": "Now"})
    after = datetime.now(IST)
    assert r.status_code == 200, r.text
    stored = datetime.fromisoformat(r.json()["project"]["fieldworkDatetime"])
    assert before <= stored <= after
    assert stored.utcoffset() == timedelta(hours=5, minutes=30)


def test_supplied_timezone_kept_and_validated(env):
    c = env["client"]
    ok = c.post("/api/ops/projects", json={**PROJECT_BODY, "timezone": "Europe/London"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["project"]["timezone"] == "Europe/London"
    assert c.post("/api/ops/projects", json={**PROJECT_BODY, "timezone": "Mars/Base"}).status_code == 422


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
    assert env["db"]["ops_surveys"].docs == []  # nothing written on failure


def test_survey_numbers_are_sequential_from_100001(env):
    c = env["client"]
    pid = _project(c)
    a = _survey(c, pid, surveyName="A")
    b = _survey(c, pid, surveyName="B")
    assert (a["surveyNumber"], b["surveyNumber"]) == ("100001", "100002")
    assert a["surveyNo"] == a["surveyNumber"]  # compatibility key


def test_add_supplier_requires_existing_vendor(env):
    c = env["client"]
    _seed_vendor(env["db"], "101", "Vendor One")
    pid = _project(c)
    sid = _survey(c, pid)["id"]

    ok = c.post(f"/api/ops/surveys/{sid}/suppliers", json={"vendorIds": ["101"]})
    assert ok.status_code == 200, ok.text
    item = ok.json()["items"][0]
    assert item["vendorName"] == "Vendor One"
    assert item["needsLink"] is True and item["surveyNo"] is None

    unknown = c.post(f"/api/ops/surveys/{sid}/suppliers", json={"vendorIds": ["999"]})
    assert unknown.status_code == 422
    assert len(env["db"]["survey_suppliers"].docs) == 1
    assert len(env["db"]["vendors"].docs) == 1  # vendor never created


def test_same_vendor_twice_in_survey_ok(env):
    c, db = env["client"], env["db"]
    _seed_vendor(db, "101", "Vendor One")
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    _link(c, db, sid, "101", "L1")
    _link(c, db, sid, "101", "L2")
    again = c.post(f"/api/ops/surveys/{sid}/suppliers", json={"vendorIds": ["101"]})
    assert again.status_code == 200, again.text

    items = c.get(f"/api/ops/surveys/{sid}/suppliers").json()["items"]
    assert len(items) == 3
    assert all(i["vendorId"] == "101" for i in items)
    assert sorted(str(i["surveyNo"]) for i in items if i["surveyNo"]) == ["L1", "L2"]
    assert sum(1 for i in items if i["needsLink"]) == 1


def test_add_link_validations_write_nothing_on_failure(env):
    c, db = env["client"], env["db"]
    _seed_vendor(db, "101", "Vendor One")
    _seed_vendor(db, "102", "Vendor Two")
    pid = _project(c)
    sa = _survey(c, pid, surveyName="A")["id"]
    sb = _survey(c, pid, surveyName="B")["id"]
    _link(c, db, sa, "101", "L1")  # L1 now attached in survey A
    _legacy(db, "L5", "102")  # vendor 102 link
    _legacy(db, "L6", "101", deleted=True)  # soft-deleted link
    before = len(db["survey_suppliers"].docs)

    missing = c.post(f"/api/ops/surveys/{sb}/suppliers", json={"links": [{"vendorId": "101", "surveyNo": "NOPE"}]})
    assert missing.status_code == 422 and "No traffic link" in missing.json()["detail"]
    mismatch = c.post(f"/api/ops/surveys/{sb}/suppliers", json={"links": [{"vendorId": "101", "surveyNo": "L5"}]})
    assert mismatch.status_code == 422 and "not 101" in mismatch.json()["detail"]
    deleted = c.post(f"/api/ops/surveys/{sb}/suppliers", json={"links": [{"vendorId": "101", "surveyNo": "L6"}]})
    assert deleted.status_code == 422
    attached = c.post(f"/api/ops/surveys/{sb}/suppliers", json={"links": [{"vendorId": "101", "surveyNo": "L1"}]})
    assert attached.status_code == 409
    dup_in_request = c.post(f"/api/ops/surveys/{sb}/suppliers", json={"links": [
        {"vendorId": "101", "surveyNo": "L5"}, {"vendorId": "101", "surveyNo": "L5"}]})
    assert dup_in_request.status_code == 422

    assert len(db["survey_suppliers"].docs) == before  # all-or-nothing


def test_attach_link_validations(env):
    c, db = env["client"], env["db"]
    _seed_vendor(db, "101", "Vendor One")
    _seed_vendor(db, "102", "Vendor Two")
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    _link(c, db, sid, "101", "L1")  # attached
    unlinked = c.post(f"/api/ops/surveys/{sid}/suppliers", json={"vendorIds": ["101"]}).json()["items"][0]
    url = f"/api/ops/survey-suppliers/{unlinked['id']}/link"

    assert c.put(url, json={"surveyNo": "NOPE"}).status_code == 422          # missing legacy doc
    _legacy(db, "L9", "102")
    assert c.put(url, json={"surveyNo": "L9"}).status_code == 422            # vendor mismatch
    _legacy(db, "L8", "101", deleted=True)
    assert c.put(url, json={"surveyNo": "L8"}).status_code == 422            # deleted doc
    assert c.put(url, json={"surveyNo": "L1"}).status_code == 409            # already attached

    _legacy(db, "L7", "101")
    ok = c.put(url, json={"surveyNo": "L7"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["item"]["surveyNo"] == "L7" and ok.json()["item"]["needsLink"] is False


def test_per_supplier_metrics_keyed_by_own_pid(env):
    c, db, t = env["client"], env["db"], env["traffic"]
    env["admin"]["on"] = True
    _seed_vendor(db, "101", "Vendor One")
    _seed_vendor(db, "102", "Vendor Two")
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    a = _link(c, db, sid, "101", "L1", buyPrice="2.50", currency="INR")
    b = _link(c, db, sid, "102", "L2")
    cc = _link(c, db, sid, "101", "L3")  # same vendor again, different link

    _rec(t, "L1", "101", "Complete", minutes=10)
    _rec(t, "L1", "101", "Complete", minutes=20)
    _rec(t, "L1", "101", "Terminate")
    _rec(t, "L1", "999", "Complete", minutes=5)  # pid is link-specific: counts for L1 whatever the vendor field
    for _ in range(5):
        _rec(t, "L2", "102", "Complete", minutes=5)
    _rec(t, "L3", "101", "Complete", minutes=5)
    _rec(t, "OTHER", "101", "Complete", minutes=5)  # no participation has this pid

    items = {i["id"]: i for i in c.get(f"/api/ops/surveys/{sid}/suppliers").json()["items"]}
    assert items[a["id"]]["entrants"] == 4
    assert items[a["id"]]["completes"] == 3
    assert items[a["id"]]["terms"] == 1
    assert items[a["id"]]["completesWindow"] == 3
    assert items[a["id"]]["expense"] == 7.5           # 3 completes * 2.50
    assert items[a["id"]]["expenseBasis"] == "completes*buyPrice"
    assert items[b["id"]]["completes"] == 5
    assert items[b["id"]]["expense"] is None and items[b["id"]]["expenseBasis"] is None
    assert items[cc["id"]]["completes"] == 1


def test_survey_metrics_equal_sum_of_suppliers_and_loi_is_median(env):
    c, db, t = env["client"], env["db"], env["traffic"]
    _seed_vendor(db, "101", "Vendor One")
    _seed_vendor(db, "102", "Vendor Two")
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    _link(c, db, sid, "101", "L1")
    _link(c, db, sid, "102", "L2")
    _rec(t, "L1", "101", "Complete", minutes=10)
    _rec(t, "L1", "101", "Complete", minutes=20)
    _rec(t, "L2", "102", "Complete", minutes=30)
    _rec(t, "L2", "102", "Terminate")

    survey_row = c.get(f"/api/ops/projects/{pid}/surveys").json()["items"][0]
    sup = {i["vendorId"]: i for i in c.get(f"/api/ops/surveys/{sid}/suppliers").json()["items"]}
    assert sup["101"]["loi"] == 15.0 and sup["102"]["loi"] == 30.0
    assert survey_row["completes"] == sup["101"]["completes"] + sup["102"]["completes"] == 3
    assert survey_row["entrants"] == sup["101"]["entrants"] + sup["102"]["entrants"] == 4
    assert survey_row["terms"] == 1
    assert survey_row["ir"] == 75.0                    # 3 / (3 + 1)
    assert survey_row["conversion"] == 75.0            # 3 / 4
    assert survey_row["loi"] == 20.0                   # median of 10, 20, 30 (not average of 15 and 30)


def test_remove_supplier_leaves_vendor_and_legacy(env):
    c, db = env["client"], env["db"]
    _seed_vendor(db, "101", "Vendor One")
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    sup = _link(c, db, sid, "101", "L1")
    vendor_before = dict(db["vendors"].docs[0])
    legacy_before = dict(db["projects"].docs[0])

    r = c.delete(f"/api/ops/survey-suppliers/{sup['id']}")
    assert r.status_code == 200
    assert c.get(f"/api/ops/surveys/{sid}/suppliers").json()["items"] == []
    assert db["vendors"].docs[0] == vendor_before      # vendor untouched
    assert db["projects"].docs[0] == legacy_before     # legacy traffic doc untouched


def test_duplicate_survey_fresh_number_and_no_suppliers(env):
    c, db = env["client"], env["db"]
    _seed_vendor(db, "101", "Vendor One")
    pid = _project(c)
    original = _survey(c, pid)
    sid = original["id"]
    c.post(f"/api/ops/surveys/{sid}/status", json={"status": "live"})
    _link(c, db, sid, "101", "L1")
    before = dict(db["ops_surveys"].docs[0])

    r = c.post(f"/api/ops/surveys/{sid}/duplicate")
    assert r.status_code == 200, r.text
    new = r.json()["survey"]
    assert new["id"] != sid
    assert new["surveyNumber"] != original["surveyNumber"]
    assert new["status"] == "draft"
    assert new["parentProjectId"] == pid
    assert c.get(f"/api/ops/surveys/{new['id']}/suppliers").json()["items"] == []
    assert len(db["survey_suppliers"].docs) == 1       # copy has no participations

    after = db["ops_surveys"].find_one({"_id": ObjectId(sid)})
    assert after["surveyNumber"] == before["surveyNumber"]
    assert after["status"] == "live"
    assert after["surveyName"] == before["surveyName"]
    assert len(db["projects"].docs) == 1                # no legacy doc created


def test_status_write_through_to_legacy_doc(env):
    c, db = env["client"], env["db"]
    _seed_vendor(db, "101", "Vendor One")
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    sup = _link(c, db, sid, "101", "L1")
    legacy_id = ObjectId(sup["legacyProjectId"])
    url = f"/api/ops/survey-suppliers/{sup['id']}"

    r = c.put(url, json={"status": "paused"})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["status"] == "paused"
    assert db["projects"].find_one({"_id": legacy_id})["projectStatus"] == "pause"
    assert c.get(f"/api/ops/surveys/{sid}/suppliers").json()["items"][0]["status"] == "paused"

    c.put(url, json={"status": "completed"})
    assert db["projects"].find_one({"_id": legacy_id})["projectStatus"] == "close"
    c.put(url, json={"status": "live"})
    assert db["projects"].find_one({"_id": legacy_id})["projectStatus"] == "live"
    assert db["projects"].find_one({"_id": legacy_id})["projectName"] == "Legacy L1"  # other fields untouched
    assert c.put(url, json={"status": "draft"}).status_code == 422

    # Survey status is independent: it never reaches the legacy doc or the supplier.
    assert c.post(f"/api/ops/surveys/{sid}/status", json={"status": "paused"}).status_code == 200
    assert db["projects"].find_one({"_id": legacy_id})["projectStatus"] == "live"
    assert c.get(f"/api/ops/surveys/{sid}/suppliers").json()["items"][0]["status"] == "live"
    assert c.get(f"/api/ops/surveys/{sid}").json()["survey"]["status"] == "paused"


def test_per_supplier_pricing_and_status_fields_present(env):
    c, db = env["client"], env["db"]
    _seed_vendor(db, "101", "Vendor One")
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    sup = _link(c, db, sid, "101", "L1")
    assert sup["needsLink"] is False and sup["surveyNo"] == "L1"
    assert sup["legacyProjectId"] is not None


def test_unlinked_supplier_zero_metrics(env):
    c, db = env["client"], env["db"]
    _seed_vendor(db, "101", "Vendor One")
    pid = _project(c)
    sid = _survey(c, pid)["id"]
    c.post(f"/api/ops/surveys/{sid}/suppliers", json={"vendorIds": ["101"]})
    item = c.get(f"/api/ops/surveys/{sid}/suppliers").json()["items"][0]
    assert item["needsLink"] is True and item["surveyNo"] is None
    assert item["entrants"] == 0 and item["completes"] == 0 and item["loi"] is None
    assert item["status"] == "live"


def test_project_totals_sum_surveys_each_pid_once(env):
    c, db, t = env["client"], env["db"], env["traffic"]
    _seed_vendor(db, "101", "Vendor One")
    _seed_vendor(db, "102", "Vendor Two")
    pid = _project(c)
    a = _survey(c, pid, surveyName="A")["id"]
    b = _survey(c, pid, surveyName="B", targetN=50)["id"]
    _link(c, db, a, "101", "L1")
    _link(c, db, b, "102", "L2")
    _rec(t, "L1", "101", "Complete", minutes=5)
    _rec(t, "L1", "101", "Complete", minutes=5)
    _rec(t, "L2", "102", "Complete", minutes=5)
    _rec(t, "L2", "102", "Terminate")

    row = next(r for r in c.get("/api/ops/projects?sort=completes&order=desc").json()["items"] if r["id"] == pid)
    assert row["surveyCount"] == 2
    assert row["completes"] == 3
    assert row["target"] == 150
    survey_items = c.get(f"/api/ops/projects/{pid}/surveys").json()["items"]
    assert sum(i["completes"] for i in survey_items) == row["completes"]


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
    c, db = env["client"], env["db"]
    _seed_vendor(db, "101", "Vendor One")
    pid = _project(c)
    survey = _survey(c, pid)
    _link(c, db, survey["id"], "101", "L1")
    _rec(env["traffic"], "L1", "101", "Complete", minutes=3)
    r = c.get(f"/api/ops/surveys/{survey['id']}/traffic-report?format=json")
    assert r.status_code == 200
    row = r.json()["respondents"][0]
    assert row["respondentId"] is not None
    assert row["supplier"] == "Vendor One" and row["supplierSurveyNo"] == "L1"
    assert "email" not in r.json()["respondentColumns"]  # non-admin: no PII columns
    logs = c.get(f"/api/ops/surveys/{survey['id']}/change-log").json()["items"]
    assert any(i["action"] == "traffic.export" for i in logs)


def test_project_list_counts_and_sort(env):
    c = env["client"]
    _project(c)
    _project(c)
    body = c.get("/api/ops/projects?sort=completes&order=desc").json()
    assert body["total"] == 2
    assert body["counts"]["all"] == 2 and body["counts"]["live"] == 2
    assert {i["projectNumber"] for i in body["items"]} == {"P001", "P002"}


def test_client_name_and_source_on_project(env):
    c = env["client"]
    r = c.post("/api/ops/projects", json={**PROJECT_BODY, "clientName": "  Hansa  "})
    assert r.status_code == 200, r.text
    proj = r.json()["project"]
    assert proj["clientName"] == "Hansa"
    assert c.get(f"/api/ops/projects/{proj['id']}").json()["project"]["source"] == "manual"
    upd = c.put(f"/api/ops/projects/{proj['id']}", json={"clientName": ""})
    assert upd.json()["project"]["clientName"] is None


# ============================================================ metric definitions

def test_inflight_vs_abandon_split_by_age(env, monkeypatch):
    monkeypatch.setenv("OPS_INFLIGHT_MINUTES", "60")
    c, db, traffic = env["client"], env["db"], env["traffic"]
    _seed_vendor(db, "v1", "Vendor One")
    pid = _project(c)
    s = _survey(c, pid)
    _link(c, db, s["id"], "v1", "L1")
    now = datetime.utcnow()
    _raw_row(traffic, "L1", "v1", "INCOMPLETE", now - timedelta(minutes=10))  # in-flight
    _raw_row(traffic, "L1", "v1", "INCOMPLETE", now - timedelta(hours=3))     # abandon
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
    c, db, traffic = env["client"], env["db"], env["traffic"]
    _seed_vendor(db, "v1", "Vendor One")
    pid = _project(c)
    s = _survey(c, pid)
    _link(c, db, s["id"], "v1", "L1")
    old = datetime.utcnow() - timedelta(hours=2)
    for status in ("SECURITY_TERMINATED", "TERMINATED", "OVERQUOTA", "COMPLETE", "NOT_ROUTED"):
        _raw_row(traffic, "L1", "v1", status, old)  # bare NOT_ROUTED: no screener reason
    row = c.get(f"/api/ops/projects/{pid}/surveys").json()["items"][0]
    assert row["defenderTerms"] == 1          # SECURITY_TERMINATED only
    assert row["terms"] == 2                  # TERMINATED + SECURITY_TERMINATED (all Terminate)
    assert row["oqs"] == 1
    assert row["sqTerms"] == 0                # no screener reason on the NOT_ROUTED row
    assert row["abandons"] == 1               # non-screener NOT_ROUTED stays non-final
    body = c.get(f"/api/ops/projects/{pid}/surveys").json()
    assert body["meta"]["unverifiedMetrics"] == []
    assert body["meta"]["sqTermsNote"].startswith("Screened out by our qualification")


def test_sq_terms_counts_only_screener_not_routed(env, monkeypatch):
    monkeypatch.setenv("OPS_INFLIGHT_MINUTES", "60")
    c, db, traffic = env["client"], env["db"], env["traffic"]
    pid = _project(c)
    env["admin"]["on"] = True
    _seed_vendor(db, "v1", "Vendor One")
    s = _survey(c, pid)
    _link(c, db, s["id"], "v1", "L1")
    now = datetime.utcnow()
    old = now - timedelta(hours=2)

    def add(status, reason=None, created=old):
        doc = {"params": {"api": "false", "pid": "L1"}, "vendorId": "v1", "status": status,
               "createdAt": created, "respondentId": f"r{len(traffic.docs)}"}
        if reason is not None:
            doc["notRoutedReason"] = reason
        traffic.insert_one(doc)

    add("NOT_ROUTED", "prescreen_fail")                  # screener -> sqTerms
    add("not_routed", "country")                         # case-insensitive, screener -> sqTerms
    add("NOT_ROUTED", "prescreen_fail", created=now)     # recent screener row: still sqTerms, not in-flight
    add("NOT_ROUTED", "router_link")                     # capacity: not sqTerms, non-final -> abandon
    add("NOT_ROUTED", None)                              # no reason: not sqTerms, non-final -> abandon
    add("TERMINATED")                                    # terms only

    row = c.get(f"/api/ops/projects/{pid}/surveys").json()["items"][0]
    assert row["sqTerms"] == 3
    assert row["terms"] == 1                             # sqTerms rows never inflate terms
    assert row["inFlights"] == 0                         # recent screener row not in-flight
    assert row["abandons"] == 2                          # router_link + bare NOT_ROUTED only
    assert row["entrants"] == 6

    sup = c.get(f"/api/ops/surveys/{s['id']}/suppliers").json()
    assert sup["items"][0]["sqTerms"] == 3
    assert sup["items"][0]["abandons"] == 2
    assert "sqTerms" not in sup["meta"]["unverifiedMetrics"]


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
    c, db = env["client"], env["db"]
    _seed_vendor(db, "v1", "Acme Panel")
    pid = _project(c)
    s = _survey(c, pid)
    link = _link(c, db, s["id"], "v1", "L1")
    db["survey_suppliers"].insert_one({"surveyId": str(ObjectId()), "vendorId": "v9",
                                       "vendorName": "Acme Orphan", "removed": False})
    hits = c.get("/api/ops/search", params={"q": "Acme"}).json()["suppliers"]
    linked = next(h for h in hits if h["id"] == link["id"])
    assert linked["surveyId"] == s["id"]
    assert linked["surveyNo"] == "L1"                  # supplier link number
    assert linked["surveyNumber"] == s["surveyNumber"]
    assert linked["parentProjectId"] == pid
    assert linked["vendorName"] == "Acme Panel"
    orphan = next(h for h in hits if h["vendorId"] == "v9")
    assert orphan["parentProjectId"] is None
    assert orphan["surveyNo"] is None
    sr = c.get("/api/ops/search", params={"q": s["surveyNumber"]}).json()["surveys"]
    assert sr[0]["parentProjectId"] == pid


def test_test_link_returns_stored_url_only(env):
    c, db, traffic = env["client"], env["db"], env["traffic"]
    pid = _project(c)
    s = _survey(c, pid, surveyUrl="https://example.com/survey?x=1&y=2")
    r = c.get(f"/api/ops/surveys/{s['id']}/test-link")
    assert r.status_code == 200
    assert r.json() == {"url": "https://example.com/survey?x=1&y=2"}
    assert traffic.docs == []  # records no traffic

    db["ops_surveys"].update_one({"_id": ObjectId(s["id"])}, {"$set": {"surveyUrl": "javascript:alert(1)"}})
    r = c.get(f"/api/ops/surveys/{s['id']}/test-link")
    assert r.status_code == 404
    assert r.json()["detail"] == "No survey URL set"


def test_validation_message_is_one_readable_line():
    msg = ops._validation_message([{"loc": ("body", "managerId"), "msg": "Field required"},
                                   {"loc": ("body",), "msg": "bad body"}])
    assert msg == "managerId: Field required; request: bad body"


# ============================================================ RFQ link (ops_projects <-> crm_db.opportunities)

@pytest.fixture
def rfq_env(env, monkeypatch):
    crm = FakeDB()
    monkeypatch.setattr(ops, "_crm_db", lambda: crm)
    env["crm"] = crm
    return env


def _opp(crm, oid, title, stage="rfq", account_id=None):
    crm["opportunities"].insert_one({"_id": oid, "title": title, "stage": stage, "account_id": account_id})


def test_project_detail_and_list_report_rfq_fields(rfq_env):
    c = rfq_env["client"]
    pid = _project(c)
    detail = c.get(f"/api/ops/projects/{pid}").json()["project"]
    assert detail["rfq"] is None
    assert detail["rfqCandidates"] == []
    row = c.get("/api/ops/projects").json()["items"][0]
    assert row["rfq"] is None and row["rfqCandidates"] == []


def test_rfq_set_then_clear_is_manual_and_logged(rfq_env):
    c, db, crm = rfq_env["client"], rfq_env["db"], rfq_env["crm"]
    pid = _project(c)
    _opp(crm, "o1", "Amazon Pay Study", stage="proposal")

    r = c.put(f"/api/ops/projects/{pid}/rfq", json={"rfqId": "o1"})
    assert r.status_code == 200, r.text
    assert r.json()["project"]["rfq"] == {"id": "o1", "title": "Amazon Pay Study",
                                          "stage": "proposal", "method": "manual"}

    r = c.put(f"/api/ops/projects/{pid}/rfq", json={"rfqId": None})
    assert r.status_code == 200, r.text
    assert r.json()["project"]["rfq"] is None
    stored = db["ops_projects"].find_one({"_id": ObjectId(pid)})
    assert stored["rfqMatch"]["method"] == "manual"  # a cleared link stays manual; matcher leaves it alone

    logs = [d for d in db["ops_change_log"].docs if d["action"] == "project.rfq_match"]
    assert [d["new"] for d in logs] == ["o1", None]


def test_rfq_unknown_id_is_422(rfq_env):
    c = rfq_env["client"]
    pid = _project(c)
    r = c.put(f"/api/ops/projects/{pid}/rfq", json={"rfqId": "missing"})
    assert r.status_code == 422
    assert r.json()["detail"] == "rfqId is not a known RFQ"


def test_project_list_rfq_filter(rfq_env):
    c, db = rfq_env["client"], rfq_env["db"]
    p1 = _project(c)
    p2 = _project(c)
    _project(c)
    db["ops_projects"].update_one({"_id": ObjectId(p1)},
                                  {"$set": {"rfqId": "o1", "rfqTitle": "T", "rfqStage": "rfq",
                                            "rfqMatch": {"method": "title-exact"}}})
    db["ops_projects"].update_one({"_id": ObjectId(p2)},
                                  {"$set": {"rfqCandidates": [{"id": "a", "title": "A", "stage": "rfq"},
                                                              {"id": "b", "title": "B", "stage": "won"}]}})

    matched = c.get("/api/ops/projects", params={"rfq": "matched"}).json()
    assert [i["projectNumber"] for i in matched["items"]] == ["P001"]
    assert matched["items"][0]["rfq"]["method"] == "title-exact"

    amb = c.get("/api/ops/projects", params={"rfq": "ambiguous"}).json()
    assert [i["projectNumber"] for i in amb["items"]] == ["P002"]
    assert len(amb["items"][0]["rfqCandidates"]) == 2
    assert amb["items"][0]["rfq"] is None

    unm = c.get("/api/ops/projects", params={"rfq": "unmatched"}).json()
    assert [i["projectNumber"] for i in unm["items"]] == ["P003"]

    assert c.get("/api/ops/projects", params={"rfq": "bogus"}).status_code == 422


def test_rfq_lookup_title_search(rfq_env):
    c, crm = rfq_env["client"], rfq_env["crm"]
    _opp(crm, "o1", "Amazon Pay Study")
    _opp(crm, "o2", "amazon pay wave 2")
    _opp(crm, "o3", "Other Thing")

    items = c.get("/api/ops/rfq/lookup", params={"q": "AMAZON"}).json()["items"]
    assert sorted(i["id"] for i in items) == ["o1", "o2"]
    assert set(items[0]) == {"id", "title", "stage"}
    assert len(c.get("/api/ops/rfq/lookup").json()["items"]) == 3
    assert c.get("/api/ops/rfq/lookup", params={"q": "nomatch"}).json()["items"] == []


def test_rfq_lookup_caps_at_20(rfq_env):
    crm, c = rfq_env["crm"], rfq_env["client"]
    for i in range(25):
        _opp(crm, f"x{i}", f"Study {i}")
    assert len(c.get("/api/ops/rfq/lookup", params={"q": "study"}).json()["items"]) == 20


def test_rfq_reverse_lookup_lists_linked_projects(rfq_env):
    c, crm = rfq_env["client"], rfq_env["crm"]
    p1 = _project(c)
    _project(c)
    _opp(crm, "o1", "Amazon Pay Study")
    c.put(f"/api/ops/projects/{p1}/rfq", json={"rfqId": "o1"})
    items = c.get("/api/ops/rfq/o1/projects").json()["items"]
    assert items == [{"id": p1, "projectName": "Project A", "projectNumber": "P001"}]
    assert c.get("/api/ops/rfq/o2/projects").json()["items"] == []
