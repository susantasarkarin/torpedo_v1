"""
Smoke tests for migration 003 (legacy vendors + clients -> canonical accounts).

Seeds throwaway vendors/clients and verifies account_type mapping, dedupe,
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
    migration = importlib.import_module("backend.migrations.003_migrate_legacy_accounts")
except Exception as e:  # pragma: no cover
    _import_error = e

SRC_DB = "crm_src_test"


@pytest.fixture()
def env():
    if migration is None:
        pytest.skip(f"imports unavailable: {_import_error}")
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    db = get_database(SRC_DB)
    db["vendors"].delete_many({})
    db["clients"].delete_many({})
    db["vendors"].insert_many([
        {"vendorName": "Panel Partner A", "vendorEmail": "a@pp.com", "vendorType": "panel", "status": "active"},
        {"vendorName": "panel partner a", "vendorEmail": "dup@pp.com"},  # dedupe vs above
    ])
    db["clients"].insert_many([
        {"name": "Kantar India", "email": "ops@kantar.in", "clientType": "agency", "currency": "INR"},
        {"name": "Acme Co", "email": "buy@acme.com"},
    ])
    yield
    crm_service._db().client.drop_database("crm_db_test")
    crm_service._db().client.drop_database(SRC_DB)


def test_dry_run_writes_nothing(env):
    stats = migration.migrate_legacy_accounts(source_db=SRC_DB, dry_run=True)
    assert stats["scanned"] == 4
    assert stats["vendors"] == 2 and stats["clients"] == 2
    assert crm_service._col("accounts").count_documents({}) == 0


def test_execute_maps_types_and_dedupes(env):
    stats = migration.migrate_legacy_accounts(source_db=SRC_DB, dry_run=False)
    # 2 vendor rows collapse to 1 account; 2 distinct clients -> 2 accounts. Total 3.
    assert crm_service._col("accounts").count_documents({}) == 3
    assert crm_service._col("accounts").count_documents({"account_type": "vendor"}) == 1
    assert crm_service._col("accounts").count_documents({"account_type": "client"}) == 2
    assert stats["accounts_created"] == 3
    assert stats["accounts_reused"] == 1  # the duplicate vendor name

    vendor = crm_service._col("accounts").find_one({"account_type": "vendor"})
    assert vendor["metadata"]["source"] == f"{SRC_DB}.vendors"
    assert vendor["metadata"]["source_id"]


def test_idempotent_rerun(env):
    migration.migrate_legacy_accounts(source_db=SRC_DB, dry_run=False)
    second = migration.migrate_legacy_accounts(source_db=SRC_DB, dry_run=False)
    # Re-run reuses all; creates nothing new.
    assert second["accounts_created"] == 0
    assert crm_service._col("accounts").count_documents({}) == 3
