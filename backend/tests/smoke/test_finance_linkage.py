"""
Smoke tests for migration 004 (finance invoices -> canonical crm_db invoices).

Seeds a throwaway finance source and verifies account linkage + dedupe,
provenance, idempotency, and dry-run safety. Throwaway DBs dropped at the end.
"""

import importlib
import pytest

pytestmark = pytest.mark.smoke

crm_service = None
migration = None
get_database = None
_import_error = None
try:
    from backend.app.services import crm_service as _svc
    from backend.database import get_database as _gd
    crm_service = _svc
    get_database = _gd
    migration = importlib.import_module("backend.migrations.004_link_finance_invoices")
except Exception as e:  # pragma: no cover
    _import_error = e

SRC_DB = "crm_src_test"
COL = "invoices"


@pytest.fixture()
def env():
    if migration is None:
        pytest.skip(f"imports unavailable: {_import_error}")
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    src = get_database(SRC_DB)[COL]
    src.delete_many({})
    src.insert_many([
        {"customer_name": "Acme Inc", "total": 5000, "invoice_number": "INV-1", "status": "sent"},
        {"customer": "acme inc", "grand_total": 2000, "invoice_number": "INV-2"},   # dedupe vs Acme Inc
        {"invoice_number": "INV-3", "amount": 100},                                  # no customer
    ])
    yield
    crm_service._db().client.drop_database("crm_db_test")
    crm_service._db().client.drop_database(SRC_DB)


def test_dry_run_writes_nothing(env):
    stats = migration.migrate_finance_invoices(source_db=SRC_DB, dry_run=True)
    assert stats["scanned"] == 3
    assert crm_service._col("invoices").count_documents({}) == 0
    assert crm_service._col("accounts").count_documents({}) == 0


def test_execute_links_and_dedupes(env):
    stats = migration.migrate_finance_invoices(source_db=SRC_DB, dry_run=False)
    assert stats["invoices_created"] == 3
    assert stats["no_customer"] == 1                 # INV-3
    assert crm_service._col("invoices").count_documents({}) == 3
    # Acme Inc + acme inc collapse to ONE account.
    assert crm_service._col("accounts").count_documents({}) == 1

    inv1 = crm_service._col("invoices").find_one({"metadata.invoice_number": "INV-1"})
    inv2 = crm_service._col("invoices").find_one({"metadata.invoice_number": "INV-2"})
    assert inv1["amount"] == 5000 and inv2["amount"] == 2000
    assert inv1["account_id"] == inv2["account_id"]  # same deduped account
    assert inv1["metadata"]["source"] == f"{SRC_DB}.invoices"


def test_idempotent_rerun(env):
    migration.migrate_finance_invoices(source_db=SRC_DB, dry_run=False)
    second = migration.migrate_finance_invoices(source_db=SRC_DB, dry_run=False)
    assert second["invoices_created"] == 0
    assert second["invoices_skipped_existing"] == 3
    assert crm_service._col("invoices").count_documents({}) == 3
