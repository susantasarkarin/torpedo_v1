"""
CRM feature smoke tests — lead conversion, pipeline stage management,
duplicate merge, search, reports, and notifications on the spine service.
Isolated to a throwaway database; skips cleanly if Mongo is unreachable.

Run:
    pytest backend/tests/smoke/test_crm_features.py -v
"""

import pytest

pytestmark = pytest.mark.smoke

crm_service = None
_import_error = None
try:
    from app.services import crm_service as _svc
    crm_service = _svc
except Exception as e:  # pragma: no cover
    _import_error = e


@pytest.fixture(scope="module")
def svc():
    if crm_service is None:
        pytest.skip(f"crm_service unavailable: {_import_error}")
    crm_service.CRM_DB_NAME = "crm_db_features_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    yield crm_service
    crm_service._db().client.drop_database("crm_db_features_test")


def test_convert_lead_creates_account_contact_opportunity(svc):
    lead = svc.create("leads", {"name": "Jane Doe", "email": "jane@convco.com",
                                "company": "ConvCo", "status": "new"})
    result = svc.convert_lead(lead["_id"],
                              opportunity={"title": "ConvCo Deal", "amount": 9000})
    assert result["lead"]["status"] == "converted"
    assert result["account"]["name"] == "ConvCo"
    assert result["contact"]["email"] == "jane@convco.com"
    assert result["opportunity"]["stage"] == "qualified"
    # double conversion is rejected
    with pytest.raises(ValueError):
        svc.convert_lead(lead["_id"])


def test_stage_moves_and_lost_requires_reason(svc):
    opp = svc.create("opportunities", {"title": "Stage Test", "amount": 100,
                                       "stage": "new", "status": "open"})
    svc.set_opportunity_stage(opp["_id"], "proposal")
    assert svc.get("opportunities", opp["_id"])["stage"] == "proposal"
    with pytest.raises(ValueError):
        svc.set_opportunity_stage(opp["_id"], "lost")
    svc.set_opportunity_stage(opp["_id"], "lost", loss_reason="budget")
    doc = svc.get("opportunities", opp["_id"])
    assert doc["status"] == "lost" and doc["loss_reason"] == "budget"
    types = {a["type"] for a in svc.list_docs("activities",
                                              {"opportunity_id": opp["_id"]})}
    assert "stage_changed" in types


def test_update_writes_field_change_history(svc):
    acc = svc.create("accounts", {"name": "HistoryCo",
                                  "name_normalized": "historyco"})
    svc.update("accounts", acc["_id"], {"owner": "susanta"}, changed_by="tester")
    acts = svc.list_docs("activities", {"account_id": acc["_id"],
                                        "type": "record_updated"})
    assert acts and acts[0]["changes"]["owner"]["to"] == "susanta"


def test_duplicate_detection_and_merge(svc):
    a1, _ = svc.get_or_create_account("MergeCo Pvt Ltd")
    a2 = svc.create("accounts", {"name": "MergeCo Limited",
                                 "name_normalized": "mergeco limited"})
    contact, _ = svc.get_or_create_contact("x@mergeco.com",
                                           defaults={"account_id": a2["_id"]})
    groups = svc.find_duplicate_accounts()
    assert any({a1["_id"], a2["_id"]} <= {a["_id"] for a in g["accounts"]}
               for g in groups)
    result = svc.merge_accounts(a1["_id"], [a2["_id"]])
    assert result["repointed"]["contacts"] == 1
    assert svc.get("accounts", a2["_id"])["status"] == "merged"
    assert svc.get("contacts", contact["_id"])["account_id"] == a1["_id"]


def test_search_and_reports(svc):
    svc.create("opportunities", {"title": "Searchable Deal", "amount": 500,
                                 "stage": "negotiation", "status": "open"})
    found = svc.search("searchable")
    assert found["opportunities"]
    report = svc.pipeline_report()
    assert report["open_value"] >= 500
    assert report["forecast"] > 0
    assert svc.activity_report(days=30)["total"] >= 1


def test_notifications_dedupe(svc):
    n1 = svc.notify("task_overdue", "Task X overdue", dedupe_key="t_x")
    n2 = svc.notify("task_overdue", "Task X overdue", dedupe_key="t_x")
    assert n1["_id"] == n2["_id"]
    svc.update("notifications", n1["_id"], {"read": True})
    n3 = svc.notify("task_overdue", "Task X overdue", dedupe_key="t_x")
    assert n3["_id"] != n1["_id"]  # read one no longer blocks a fresh alert
