"""
Smoke tests for the Phase 3 legacy-lead migration adapter.

Seeds a throwaway source collection and migrates it into a throwaway crm_db,
asserting account dedupe, provenance, idempotency, and dry-run safety. Both
databases are dropped at the end. Skips cleanly if Mongo is unreachable.
"""

import importlib
import pytest

pytestmark = pytest.mark.smoke

crm_service = None
migration = None
_import_error = None
try:
    from backend.app.services import crm_service as _svc
    crm_service = _svc
    migration = importlib.import_module("backend.migrations.002_migrate_legacy_leads")
    from backend.database import get_database
except Exception as e:  # pragma: no cover
    _import_error = e

SRC_DB = "crm_src_test"
SRC_COL = "leads"


@pytest.fixture()
def env():
    if crm_service is None or migration is None:
        pytest.skip(f"imports unavailable: {_import_error}")
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")

    src = get_database(SRC_DB)[SRC_COL]
    src.delete_many({})
    src.insert_many(
        [
            {"name": "Jane Doe", "email": "jane@acme.com", "company": "Acme Inc", "source": "import"},
            {"name": "John Roe", "email": "john@acme.com", "company": "acme inc", "source": "import"},
            {"name": "Sam Lee", "email": "sam@globex.com", "company": "Globex"},
            {"email": "noname@nocompany.com"},  # no name, no company
        ]
    )
    yield
    crm_service._db().client.drop_database("crm_db_test")
    crm_service._db().client.drop_database(SRC_DB)


def test_dry_run_writes_nothing(env):
    stats = migration.migrate_legacy_leads(
        source_db=SRC_DB, source_collection=SRC_COL, dry_run=True
    )
    assert stats["scanned"] == 4
    assert stats["leads_created"] == 4
    assert crm_service._col("leads").count_documents({}) == 0
    assert crm_service._col("accounts").count_documents({}) == 0


def test_execute_creates_and_dedupes(env):
    stats = migration.migrate_legacy_leads(
        source_db=SRC_DB, source_collection=SRC_COL, dry_run=False
    )
    assert stats["leads_created"] == 4
    # "Acme Inc" and "acme inc" collapse to one account; Globex is a second.
    assert stats["accounts_created"] == 2
    assert stats["accounts_reused"] == 1
    assert crm_service._col("leads").count_documents({}) == 4
    assert crm_service._col("accounts").count_documents({}) == 2

    # Both Acme leads point at the same account.
    acme_leads = list(crm_service._col("leads").find({"company": {"$in": ["Acme Inc", "acme inc"]}}))
    account_ids = {l.get("account_id") for l in acme_leads}
    assert len(account_ids) == 1 and None not in account_ids

    # Provenance is recorded.
    sample = crm_service._col("leads").find_one({"email": "jane@acme.com"})
    assert sample["metadata"]["source"] == f"{SRC_DB}.{SRC_COL}"
    assert sample["metadata"]["source_id"]


def test_idempotent_rerun(env):
    first = migration.migrate_legacy_leads(source_db=SRC_DB, source_collection=SRC_COL, dry_run=False)
    assert first["leads_created"] == 4

    second = migration.migrate_legacy_leads(source_db=SRC_DB, source_collection=SRC_COL, dry_run=False)
    assert second["leads_created"] == 0
    assert second["leads_skipped_existing"] == 4
    # No duplicates introduced on re-run.
    assert crm_service._col("leads").count_documents({}) == 4
    assert crm_service._col("accounts").count_documents({}) == 2
