"""
Spine connector smoke tests.

Verifies that module events (lead ingestion, sales accounts, finance
invoices/parties, panelist registrations) mirror correctly into the canonical
crm_db spine, isolated to a throwaway database that is dropped at the end.
Skips cleanly if Mongo is unreachable.

Run:
    pytest backend/tests/smoke/test_spine_connector.py -v
"""

import pytest

pytestmark = pytest.mark.smoke

crm_service = None
connector = None
_import_error = None
try:
    from backend.app.services import crm_service as _svc
    from backend.app.services import spine_connector as _conn
    crm_service = _svc
    connector = _conn
except Exception as e:  # pragma: no cover
    _import_error = e


@pytest.fixture(scope="module")
def svc():
    if crm_service is None or connector is None:
        pytest.skip(f"spine services unavailable: {_import_error}")
    crm_service.CRM_DB_NAME = "crm_db_connector_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    yield crm_service
    crm_service._db().client.drop_database("crm_db_connector_test")


def test_mirror_lead_creates_account_contact_lead_and_activity(svc):
    lead_id = connector.mirror_lead_to_spine(
        {"name": "Jane Doe", "email": "jane@acmecorp.com",
         "company_name": "AcmeCorp", "title": "Director of Insights"},
        source="test_ingestion", source_id="raw123")
    assert lead_id

    lead = svc.get("leads", lead_id)
    assert lead["email"] == "jane@acmecorp.com"
    assert lead["metadata"]["source"] == "test_ingestion"
    assert lead["account_id"] and lead["contact_id"]

    account = svc.get("accounts", lead["account_id"])
    assert account["name"] == "AcmeCorp"

    timeline = svc.timeline("lead", lead_id)
    assert any(a["type"] == "lead_ingested" for a in timeline["activities"])


def test_mirror_lead_dedupes_account_by_name(svc):
    a = connector.mirror_lead_to_spine(
        {"name": "A", "email": "a@dupeco.com", "company_name": "DupeCo"},
        source="t")
    b = connector.mirror_lead_to_spine(
        {"name": "B", "email": "b@dupeco.com", "company_name": "dupeco"},
        source="t")
    assert svc.get("leads", a)["account_id"] == svc.get("leads", b)["account_id"]


def test_mirror_invoice_links_account_and_logs_activity(svc):
    inv_id = connector.mirror_invoice_to_spine(
        {"invoice_number": "INV-001", "total": 1500, "currency": "USD",
         "status": "sent"},
        customer_name="BillCo", source_id="fin42")
    assert inv_id

    inv = svc.get("invoices", inv_id)
    assert inv["amount"] == 1500
    assert inv["account_id"]
    timeline = svc.timeline("account", inv["account_id"])
    assert any(a["type"] == "invoice_created" for a in timeline["activities"])


def test_mirror_finance_party_vendor(svc):
    acc_id = connector.mirror_finance_party_to_spine("PanelVendor GmbH", "vendor",
                                                     source_id="v1")
    assert acc_id
    assert svc.get("accounts", acc_id)["account_type"] == "vendor"


def test_mirror_panelist_creates_contact_activity(svc):
    contact_id = connector.mirror_panelist_registration_to_spine(
        "panelist@example.com", country="DE")
    assert contact_id
    timeline = svc.timeline("contact", contact_id)
    assert any(a["type"] == "panelist_registered" for a in timeline["activities"])


def test_mirror_is_non_fatal_on_bad_input(svc):
    assert connector.mirror_sales_account_to_spine("") is None
    assert connector.mirror_panelist_registration_to_spine("") is None
