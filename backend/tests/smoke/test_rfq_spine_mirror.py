"""
Smoke tests for the RFQ -> CRM spine mirror (routers.rfq.mirror_rfq_to_spine).

Verifies that creating an RFQ projects into the canonical spine: a Contact is
matched/created, and a linked Opportunity (stage=rfq) + Project stub are created,
isolated to a throwaway crm_db.
"""

import pytest

pytestmark = pytest.mark.smoke

crm_service = None
rfq = None
_import_error = None
try:
    from app.services import crm_service as _svc
    from routers import rfq as _rfq
    crm_service, rfq = _svc, _rfq
except Exception as e:  # pragma: no cover
    _import_error = e


@pytest.fixture()
def env():
    if rfq is None or crm_service is None:
        pytest.skip(f"imports unavailable: {_import_error}")
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    yield
    crm_service._db().client.drop_database("crm_db_test")


def test_mirror_creates_opportunity_project_and_contact(env):
    res = rfq.mirror_rfq_to_spine(
        rfq_id="RFQ-TEST-1", contact_email="jane@acme.com", title="CATI study", budget=5000
    )
    assert res["opportunity_id"] and res["project_id"]

    opp = crm_service.get("opportunities", res["opportunity_id"])
    proj = crm_service.get("projects", res["project_id"])
    assert opp["stage"] == "rfq" and opp["status"] == "open"
    assert opp["amount"] == 5000
    assert opp["project_id"] == proj["_id"]
    assert proj["status"] == "stub"

    # Contact matched/created and linked to the opportunity.
    contact = crm_service.find_contact_by_email("jane@acme.com")
    assert contact is not None
    assert opp["contact_id"] == contact["_id"]

    # Provenance: the rfq_id is carried in the opportunity metadata.
    assert opp["metadata"]["rfq"]["rfq_id"] == "RFQ-TEST-1"


def test_mirror_without_contact_email(env):
    res = rfq.mirror_rfq_to_spine(
        rfq_id="RFQ-TEST-2", contact_email=None, title="No contact RFQ", budget=0
    )
    opp = crm_service.get("opportunities", res["opportunity_id"])
    assert opp["stage"] == "rfq"
    assert not opp.get("contact_id")
    assert crm_service._col("contacts").count_documents({}) == 0
