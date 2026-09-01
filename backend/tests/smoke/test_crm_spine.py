"""
CRM spine service smoke tests.

Exercises the canonical CRUD layer and the cross-object flows (timeline, RFQ,
Opportunity-Won) directly against MongoDB, isolated to a throwaway database
(crm_db_test) that is dropped at the end. Skips cleanly if Mongo is unreachable.

Run:
    pytest backend/tests/smoke/test_crm_spine.py -v
"""

import os
import pytest

pytestmark = pytest.mark.smoke

# Import is guarded so the suite skips (not errors) without MONGO_URI / Mongo.
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
    # Redirect the spine to a throwaway DB and verify Mongo is actually reachable.
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    yield crm_service
    # Teardown: drop the entire test database.
    crm_service._db().client.drop_database("crm_db_test")


def test_account_crud(svc):
    acc = svc.create("accounts", {"name": "Acme Vendor", "account_type": "vendor"})
    assert acc["_id"]
    assert acc["created_at"] and acc["updated_at"]

    fetched = svc.get("accounts", acc["_id"])
    assert fetched["name"] == "Acme Vendor"

    updated = svc.update("accounts", acc["_id"], {"status": "inactive"})
    assert updated["status"] == "inactive"

    assert svc.delete("accounts", acc["_id"]) is True
    assert svc.get("accounts", acc["_id"]) is None


def test_activity_timeline(svc):
    acc = svc.create("accounts", {"name": "Timeline Co"})
    svc.log_activity({"type": "email", "subject": "Intro", "account_id": acc["_id"]})
    svc.create(
        "tasks",
        {"title": "Follow up", "linked_object_type": "account", "linked_object_id": acc["_id"]},
    )

    tl = svc.timeline("account", acc["_id"])
    assert len(tl["activities"]) == 1
    assert tl["activities"][0]["subject"] == "Intro"
    assert len(tl["tasks"]) == 1


def test_rfq_creates_opportunity_and_project(svc):
    acc = svc.create("accounts", {"name": "RFQ Client"})
    result = svc.create_rfq({"account_id": acc["_id"], "title": "Survey RFQ", "budget": 5000})

    opp = result["opportunity"]
    proj = result["project"]
    assert opp["stage"] == "rfq" and opp["status"] == "open"
    assert opp["amount"] == 5000
    # Cross-links wired both directions.
    assert opp["project_id"] == proj["_id"]
    assert proj["opportunity_id"] == opp["_id"]
    assert proj["status"] == "stub"

    # An rfq_created activity is attached to account, opportunity, and project.
    tl = svc.timeline("opportunity", opp["_id"])
    assert any(a["type"] == "rfq_created" for a in tl["activities"])


def test_opportunity_won_activates_project_and_creates_invoice(svc):
    acc = svc.create("accounts", {"name": "Won Client"})
    rfq = svc.create_rfq({"account_id": acc["_id"], "title": "Won RFQ", "budget": 8000})
    opp_id = rfq["opportunity"]["_id"]

    result = svc.mark_opportunity_won(opp_id)
    assert result["opportunity"]["status"] == "won"
    assert result["opportunity"]["stage"] == "won"
    assert result["project"]["status"] == "active"
    assert result["invoice"]["status"] == "draft"
    assert result["invoice"]["amount"] == 8000
    assert result["invoice"]["account_id"] == acc["_id"]


def test_ai_decision_defaults(svc):
    decision = svc.log_ai_decision(
        {"agent_name": "old_mail_classifier", "decision": "attach_to_account"}
    )
    assert decision["status"] == "pending"
    assert decision["autonomy_mode"] == "observe"


def test_unknown_collection_rejected(svc):
    with pytest.raises(ValueError):
        svc.create("not_a_collection", {"foo": "bar"})
