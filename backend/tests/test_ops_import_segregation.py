"""Segregation import (scripts/ops_import_segregation.py). Fake mongo only, no network."""
import json
import os
from datetime import datetime

import pytest
from bson import ObjectId

from scripts import ops_import_segregation as imp
from tests._fakemongo import FakeDB

SAMPLE = """PROJECT SEGREGATION: test sample
P001 RFQ_Single [Client A]
  Research Desk(00234,Live), Lucid_new(00777,Live), Research Desk(00999,Closed), Lucid_new(00998,Closed)
P002 Two Surveys [Client B]
  S1 Alpha: Research Desk(10001,Paused)
  S2 Beta: Lucid_new(10002,Closed)
P003 Tricky (Name) [with brackets] [Client (C)] -- no supplier
P004 Mismatch [Client D]
  Dynata DIY(10003,Live)
P005 Missing doc [Client E]
  Research Desk(99999,Live)
P006 Underscore names [Client F]
  S1 Only: Lucid_new(00888,Closed)
P007 Deleted legacy [Client G]
  Research Desk(55555,Live)
"""


def _seed(db):
    db["vendors"].insert_one({"vid": "101", "vendorName": "Research Desk", "status": "active"})
    db["vendors"].insert_one({"vid": "102", "vendorName": "Lucid new", "status": "active"})
    db["vendors"].insert_one({"vid": "103", "vendorName": "Lucid_term", "status": "active"})
    legacy = [
        {"surveyNo": "00234", "vendorId": "101"},
        {"surveyNo": "10001", "vendorId": "101"},
        {"surveyNo": "10002", "vendorId": "102"},
        {"surveyNo": "00777", "vendorId": "102"},
        {"surveyNo": "10003", "vendorId": "102"},  # pasted as Dynata DIY -> mismatch
        {"surveyNo": "00888", "vendorId": "102"},
        {"surveyNo": "00999", "vendorId": "101"},
        {"surveyNo": "00998", "vendorId": "102"},
        {"surveyNo": "55555", "vendorId": "101", "is_deleted": True},
    ]
    for doc in legacy:
        db["projects"].insert_one({**doc, "projectStatus": "live"})


@pytest.fixture
def db():
    d = FakeDB()
    _seed(d)
    return d


def _paths(tmp_path):
    return str(tmp_path / "report.json"), str(tmp_path / "backup")


# ---------------------------------------------------------------- parser

def test_parser_handles_single_survey_s_lines_no_supplier_and_tricky_names():
    projects, problems = imp.parse_segregation(SAMPLE)
    by_no = {p["projectNumber"]: p for p in projects}

    p1 = by_no["P001"]
    assert p1["projectName"] == "RFQ_Single" and p1["clientName"] == "Client A"
    assert [(s["name"], s["surveyNo"], s["status"]) for s in p1["suppliers"]] == [
        ("Research Desk", "00234", "live"), ("Lucid_new", "00777", "live"),
        ("Research Desk", "00999", "completed"), ("Lucid_new", "00998", "completed")]
    assert all(s["group"] == ("P", "") for s in p1["suppliers"])  # plain line = one survey

    p2 = by_no["P002"]
    assert [(s["label"], s["name"], s["status"]) for s in p2["suppliers"]] == [
        ("Alpha", "Research Desk", "paused"), ("Beta", "Lucid_new", "completed")]
    assert p2["suppliers"][0]["group"] != p2["suppliers"][1]["group"]

    p3 = by_no["P003"]
    assert p3["noSupplier"] is True and p3["suppliers"] == []
    assert p3["projectName"] == "Tricky (Name) [with brackets]"
    assert p3["clientName"] == "Client (C)"
    assert problems == []


def test_parser_reports_bad_lines_without_crashing():
    text = "HEADER\nP010 No client here\n  Research Desk(1,Live)\nP011 Ok [C]\n  Research Desk(2,Maybe)\n"
    projects, problems = imp.parse_segregation(text)
    assert [p["projectNumber"] for p in projects] == ["P011"]
    reasons = [p["reason"] for p in problems]
    assert any("no [client]" in r for r in reasons)
    assert any("unknown status" in r for r in reasons)


# ---------------------------------------------------------------- dry run / apply

def _run(db, tmp_path, apply=False, text=SAMPLE):
    report_path, backup_dir = _paths(tmp_path)
    return imp.run(db, text, apply=apply, report_path=report_path, backup_dir=backup_dir), report_path, backup_dir


def test_dry_run_writes_nothing_and_reports(db, tmp_path):
    before = {k: len(v.docs) for k, v in db.items()}
    report, report_path, backup_dir = _run(db, tmp_path)
    after = {k: len(v.docs) for k, v in db.items()}
    assert all(after[k] == before.get(k, 0) for k in after)
    assert not os.path.exists(backup_dir)
    assert os.path.exists(report_path)
    with open(report_path, encoding="utf-8") as fh:
        assert json.load(fh)["mode"] == "dry-run"
    c = report["counts"]
    assert c["projectsToCreate"] == 4            # P001, P002, P003, P006
    assert c["noSupplierProjectsToCreate"] == 1  # P003
    assert c["surveysToCreate"] == 4             # P001 x1 (plain line), P002 x2 (S1/S2), P006 x1
    assert c["suppliersToCreate"] == 7           # P001 x4, P002 x2, P006 x1
    problem_projects = {p["projectNumber"] for p in report["problems"]}
    assert {"P004", "P005", "P007"} <= problem_projects


def test_apply_creates_expected_docs(db, tmp_path):
    report, _, backup_dir = _run(db, tmp_path, apply=True)

    projects = {p["projectNumber"]: p for p in db["ops_projects"].docs}
    assert set(projects) == {"P001", "P002", "P003", "P006"}
    assert projects["P001"]["status"] == "live"
    assert projects["P002"]["status"] == "paused"
    assert projects["P003"]["status"] == "completed"
    p = projects["P001"]
    assert p["managerId"] == "unassigned" and p["managerName"] == "Unassigned"
    assert p["timezone"] == "Asia/Kolkata" and p["source"] == "import" and p["is_deleted"] is False
    assert p["clientName"] == "Client A" and p["projectName"] == "RFQ_Single"

    surveys = db["ops_surveys"].docs
    names = {s["surveyName"] for s in surveys}
    numbers = {s["surveyNumber"] for s in surveys}
    assert len(surveys) == 4
    assert {"RFQ_Single", "Alpha", "Beta", "Only"} == names
    assert "100001" in numbers                       # first issued number
    assert len(numbers) == len(surveys)              # unique

    sups = db["survey_suppliers"].docs
    assert len(sups) == 7
    by_legacy = {s["surveyNo"]: s for s in sups}
    assert set(by_legacy) == {"00234", "00777", "00999", "00998", "10001", "10002", "00888"}
    assert by_legacy["00234"]["vendorName"] == "Research Desk"
    assert by_legacy["00234"]["currency"] == "INR" and by_legacy["00234"]["removed"] is False
    plain = [s for s in sups if s["surveyId"] == by_legacy["00234"]["surveyId"]]
    assert len(plain) == 4                           # one plain survey holds all four participations
    survey_00234 = next(s for s in surveys if s["surveyName"] == "RFQ_Single")
    assert by_legacy["00234"]["surveyId"] == str(survey_00234["_id"])
    assert by_legacy["00234"]["legacyProjectId"] == str(
        next(d["_id"] for d in db["projects"].docs if d["surveyNo"] == "00234"))

    logs = [d for d in db["ops_change_log"].docs if d["action"] == "project.import"]
    assert len(logs) == 4

    with open(os.path.join(backup_dir, "ops_projects.json"), encoding="utf-8") as fh:
        assert json.load(fh) == []  # backup taken before the first write
    for name in ("ops_projects", "ops_surveys", "survey_suppliers", "ops_survey_links",
                 "counters", "ops_change_log"):
        assert os.path.exists(os.path.join(backup_dir, f"{name}.json"))
    assert report["written"]["projects"] == 4


def test_name_mismatch_and_missing_doc_go_to_problems(db, tmp_path):
    report, _, _ = _run(db, tmp_path, apply=True)
    msgs = {}
    for p in report["problems"]:
        msgs.setdefault(p["projectNumber"], []).append(p["reason"])
    assert any("name mismatch" in r for r in msgs["P004"])
    assert any("no live legacy" in r for r in msgs["P005"])
    assert any("no live legacy" in r for r in msgs["P007"])  # is_deleted legacy doc is not matched
    assert db["ops_projects"].find_one({"projectNumber": "P004"}) is None
    assert db["ops_projects"].find_one({"projectNumber": "P005"}) is None
    assert all(s["surveyNo"] != "10003" for s in db["survey_suppliers"].docs)


def test_rerun_is_idempotent(db, tmp_path):
    _run(db, tmp_path, apply=True)
    counts = {k: len(v.docs) for k, v in db.items()}
    report, _, _ = _run(db, tmp_path, apply=True)
    assert {k: len(v.docs) for k, v in db.items() if k != "counters"} == \
        {k: v for k, v in counts.items() if k != "counters"}
    assert report["written"] == {"projects": 0, "surveys": 0, "suppliers": 0}
    assert report["counts"]["suppliersAlreadyAttached"] == 7
    assert db["counters"].find_one({"_id": "ops_survey_number"})["seq"] == 100004  # no new numbers


def test_backfill_artifacts_removed_and_change_log_kept(db, tmp_path):
    db["ops_projects"].insert_one({"projectNumber": "P-OLD", "backfilledFromSurveyId": "abc",
                                   "projectName": "old"})
    db["ops_projects"].insert_one({"projectNumber": "P-KEEP", "projectName": "manual"})
    db["ops_survey_links"].insert_one({"surveyId": "a", "source": "backfill"})
    db["ops_survey_links"].insert_one({"surveyId": "b", "source": "manual"})
    db["ops_change_log"].insert_one({"action": "project.backfill", "projectId": "x"})

    _, _, backup_dir = _run(db, tmp_path, apply=True)

    numbers = {p["projectNumber"] for p in db["ops_projects"].docs}
    assert "P-OLD" not in numbers and "P-KEEP" in numbers
    assert [l["surveyId"] for l in db["ops_survey_links"].docs] == ["b"]
    assert any(d["action"] == "project.backfill" for d in db["ops_change_log"].docs)
    with open(os.path.join(backup_dir, "ops_projects.json"), encoding="utf-8") as fh:
        assert any(d["projectNumber"] == "P-OLD" for d in json.load(fh))  # backup kept the artifact


def test_backup_failure_refuses_to_apply(db, tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    db["ops_projects"].insert_one({"projectNumber": "P-OLD", "backfilledFromSurveyId": "abc"})
    report_path = str(tmp_path / "report.json")
    with pytest.raises(OSError):
        imp.run(db, SAMPLE, apply=True, report_path=report_path, backup_dir=str(blocker))
    assert [p["projectNumber"] for p in db["ops_projects"].docs] == ["P-OLD"]  # nothing deleted
    assert db["survey_suppliers"].docs == [] and db["ops_surveys"].docs == []


def test_survey_numbers_continue_from_counter(db, tmp_path):
    db["counters"].insert_one({"_id": "ops_survey_number", "seq": 100500})
    _run(db, tmp_path, apply=True)
    numbers = sorted(s["surveyNumber"] for s in db["ops_surveys"].docs)
    assert numbers[0] == "100501"
    assert all(len(n) == 6 for n in numbers)


def test_main_dry_run_cli_uses_getter(db, tmp_path, monkeypatch, capsys):
    import sys
    import types
    # Stand-in for the `database` module so the test never needs MONGO_URI.
    monkeypatch.setitem(sys.modules, "database", types.SimpleNamespace(get_email_automation_db=lambda: db))
    src = tmp_path / "seg.txt"
    src.write_text(SAMPLE, encoding="utf-8")
    rc = imp.main(["--file", str(src), "--report", str(tmp_path / "r.json")])
    assert rc == 0
    assert "mode=dry-run" in capsys.readouterr().out
    assert db["ops_projects"].docs == []
