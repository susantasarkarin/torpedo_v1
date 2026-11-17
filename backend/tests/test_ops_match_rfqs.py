"""ops_match_rfqs script: tiers, ambiguity, manual protection, dry run, apply, backup gate.

Runs against the in-memory fake (tests/_fakemongo.py). No network, no real DB.
"""
import copy
import json
from datetime import datetime

import pytest
from bson import ObjectId

from scripts import ops_match_rfqs as m
from tests._fakemongo import FakeCollection

NOW = datetime(2026, 11, 17, 12, 0, 0)


def _ctx():
    return {k: FakeCollection() for k in
            ("projects", "surveys", "suppliers", "legacy", "log", "opps", "accounts")}


def _opp(ctx, oid, title, account_id=None, stage="rfq"):
    ctx["opps"].insert_one({"_id": oid, "title": title, "stage": stage, "account_id": account_id})


def _account(ctx, aid, name):
    ctx["accounts"].insert_one({"_id": aid, "name": name})


def _project(ctx, name, number, client=None, **extra):
    pid = ObjectId()
    ctx["projects"].insert_one({"_id": pid, "projectName": name, "projectNumber": number,
                                "clientName": client, "is_deleted": False, **extra})
    return pid


def _link_legacy(ctx, pid, legacy_fields):
    """project -> live survey -> live supplier -> legacy traffic doc carrying rfq fields."""
    sid = ObjectId()
    ctx["surveys"].insert_one({"_id": sid, "projectId": str(pid), "is_deleted": False})
    lid = ObjectId()
    ctx["legacy"].insert_one({"_id": lid, "is_deleted": False, **legacy_fields})
    ctx["suppliers"].insert_one({"surveyId": str(sid), "legacyProjectId": str(lid), "removed": False})


def _proj(ctx, pid):
    return ctx["projects"].find_one({"_id": pid})


def test_tier_legacy_link_wins_over_title():
    ctx = _ctx()
    _opp(ctx, "o1", "Unrelated Title")
    pid = _project(ctx, "Some Name", "P-1")
    _link_legacy(ctx, pid, {"opportunity_id": "o1"})
    report = m.run(ctx, now=NOW)
    assert report["matches"] == [{"projectNumber": "P-1", "projectName": "Some Name",
                                  "method": "legacy-link", "rfqId": "o1", "rfqTitle": "Unrelated Title"}]


def test_tier_title_exact_is_case_and_whitespace_insensitive():
    ctx = _ctx()
    _opp(ctx, "o1", "Amazon Pay Study")
    _project(ctx, "  amazon   PAY study ", "P-1")
    report = m.run(ctx, now=NOW)
    assert [x["method"] for x in report["matches"]] == ["title-exact"]


def test_tier_title_normalized_strips_prefix_and_vendor_suffix():
    ctx = _ctx()
    _opp(ctx, "o1", "Fwd: Brand Lift - Lucid_new")
    _opp(ctx, "o2", "RE: Pricing Test - Research Desk")
    _project(ctx, "Brand Lift", "P-1")
    _project(ctx, "Pricing Test", "P-2")
    report = m.run(ctx, now=NOW)
    assert sorted((x["projectNumber"], x["method"], x["rfqId"]) for x in report["matches"]) == [
        ("P-1", "title-normalized", "o1"), ("P-2", "title-normalized", "o2")]


def test_no_tier_hits_means_unmatched():
    ctx = _ctx()
    _opp(ctx, "o1", "Something Else")
    _project(ctx, "Nothing Alike", "P-1")
    report = m.run(ctx, now=NOW)
    assert report["matches"] == []
    assert [u["projectNumber"] for u in report["unmatched"]] == ["P-1"]
    assert report["counts"]["unmatched"] == 1


def test_ambiguous_left_unmatched_with_candidates_on_apply(tmp_path):
    ctx = _ctx()
    _account(ctx, "a1", "Other Co")
    _account(ctx, "a2", "Beta")
    _opp(ctx, "o1", "Study X", account_id="a1")
    _opp(ctx, "o2", "Study X", account_id="a2", stage="won")
    pid = _project(ctx, "Study X", "P-1", client="Acme")
    report = m.run(ctx, apply=True, backup_dir=str(tmp_path), now=NOW)
    assert report["matches"] == []
    amb = report["ambiguous"][0]
    assert amb["projectNumber"] == "P-1" and amb["tier"] == "title-exact"
    assert sorted(c["id"] for c in amb["candidates"]) == ["o1", "o2"]
    stored = _proj(ctx, pid)
    assert not stored.get("rfqId")
    assert sorted(c["id"] for c in stored["rfqCandidates"]) == ["o1", "o2"]
    assert ctx["log"].docs == []  # candidates are not a match, so no change-log row


def test_account_name_disambiguates_tier():
    ctx = _ctx()
    _account(ctx, "a1", "Acme")
    _account(ctx, "a2", "Beta")
    _opp(ctx, "o1", "Study X", account_id="a1")
    _opp(ctx, "o2", "Study X", account_id="a2")
    _project(ctx, "Study X", "P-1", client="  acme ")
    report = m.run(ctx, now=NOW)
    assert [(x["rfqId"], x["method"]) for x in report["matches"]] == [("o1", "title-exact")]
    assert report["ambiguous"] == []


def test_legacy_ambiguity_stops_cascade_instead_of_falling_to_title():
    ctx = _ctx()
    _opp(ctx, "o1", "Alpha")
    _opp(ctx, "o2", "Beta")
    _opp(ctx, "o3", "Gamma Study")  # exact title match, must NOT win after legacy ambiguity
    pid = _project(ctx, "Gamma Study", "P-1")
    _link_legacy(ctx, pid, {"rfqId": "o1"})
    _link_legacy(ctx, pid, {"opportunity_id": "o2"})
    report = m.run(ctx, now=NOW)
    assert report["matches"] == []
    assert report["ambiguous"][0]["tier"] == "legacy-link"


def test_candidates_capped_at_five():
    ctx = _ctx()
    for i in range(7):
        _opp(ctx, f"o{i}", "Same Name")
    _project(ctx, "Same Name", "P-1", client="Nobody")
    report = m.run(ctx, now=NOW)
    assert len(report["ambiguous"][0]["candidates"]) == 5


def test_manual_and_linked_projects_never_overwritten(tmp_path):
    ctx = _ctx()
    _opp(ctx, "o1", "Study A")
    _opp(ctx, "o2", "Study B")
    manual = _project(ctx, "Study A", "P-1", rfqId=None, rfqMatch={"method": "manual", "by": "ops"})
    linked = _project(ctx, "Study B", "P-2", rfqId="o9", rfqTitle="Old", rfqStage="rfq",
                      rfqMatch={"method": "manual", "by": "ops"})
    before = copy.deepcopy([_proj(ctx, manual), _proj(ctx, linked)])
    report = m.run(ctx, apply=True, backup_dir=str(tmp_path), now=NOW)
    assert report["matches"] == [] and report["unmatched"] == []
    assert report["counts"]["skipped_manual"] == 1
    assert report["counts"]["skipped_linked"] == 1
    assert [_proj(ctx, manual), _proj(ctx, linked)] == before
    assert ctx["log"].docs == []


def test_dry_run_writes_nothing():
    ctx = _ctx()
    _opp(ctx, "o1", "Study A")
    pid = _project(ctx, "Study A", "P-1")
    before = copy.deepcopy(_proj(ctx, pid))
    report = m.run(ctx, apply=False, now=NOW)
    assert report["mode"] == "dry-run" and report["counts"]["matched"]["title-exact"] == 1
    assert _proj(ctx, pid) == before
    assert ctx["log"].docs == []


def test_apply_writes_match_and_log_then_is_idempotent(tmp_path):
    ctx = _ctx()
    _opp(ctx, "o1", "Study A", stage="proposal")
    pid = _project(ctx, "Study A", "P-1")
    first = m.run(ctx, apply=True, backup_dir=str(tmp_path), now=NOW)
    assert first["applied"] == {"matched": 1, "candidates_updated": 0}
    stored = _proj(ctx, pid)
    assert stored["rfqId"] == "o1" and stored["rfqTitle"] == "Study A" and stored["rfqStage"] == "proposal"
    assert stored["rfqMatch"] == {"method": "title-exact", "matchedAt": NOW, "by": m.SCRIPT_USER}
    assert len(ctx["log"].docs) == 1
    assert ctx["log"].docs[0]["action"] == "project.rfq_match"

    second = m.run(ctx, apply=True, backup_dir=str(tmp_path), now=NOW)
    assert second["applied"] == {"matched": 0, "candidates_updated": 0}
    assert second["matches"] == [] and len(ctx["log"].docs) == 1


def test_apply_writes_backup_file(tmp_path):
    ctx = _ctx()
    _opp(ctx, "o1", "Study A")
    _project(ctx, "Study A", "P-1")
    report = m.run(ctx, apply=True, backup_dir=str(tmp_path), now=NOW)
    assert report["backup"]["projects"] == 1
    assert list(tmp_path.glob("ops_projects_*.json"))


def test_backup_failure_refuses_apply(tmp_path):
    ctx = _ctx()
    _opp(ctx, "o1", "Study A")
    pid = _project(ctx, "Study A", "P-1")
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("a file is in the way of the backup dir")
    before = copy.deepcopy(_proj(ctx, pid))
    with pytest.raises(OSError):
        m.run(ctx, apply=True, backup_dir=str(blocker), now=NOW)
    assert _proj(ctx, pid) == before
    assert ctx["log"].docs == []


def test_cli_apply_requires_backup_dir():
    with pytest.raises(SystemExit) as exc:
        m.main(["--apply"], ctx=_ctx())
    assert exc.value.code == 2


def test_cli_dry_run_writes_report(tmp_path):
    ctx = _ctx()
    _opp(ctx, "o1", "Study A")
    _project(ctx, "Study A", "P-1")
    out = tmp_path / "report.json"
    assert m.main(["--report", str(out)], ctx=ctx) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["mode"] == "dry-run" and data["matches"][0]["rfqId"] == "o1"
    assert ctx["log"].docs == []
