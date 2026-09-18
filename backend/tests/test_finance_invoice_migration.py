"""
Covers a 2026-09-18 fix to migrations/004_link_finance_invoices.py: the
original account-matching used name fields (customer_name, customer, ...)
that finance_db.invoices doesn't actually carry -- confirmed live, a dry
run against all 265 real invoices found "no_customer" on every single one.
finance_db.invoices does carry customer_id, and finance_db.customers
already carries crm_account_id for every customer that's been invoiced
(confirmed live: 265/265 resolve to a real crm_db.accounts doc). This adds
that direct join ahead of the name-based fallback.

Module filename starts with a digit, so it's loaded via importlib rather
than a normal import statement (same approach as the existing smoke test
for this migration, tests/smoke/test_finance_linkage.py).
"""
import importlib
from unittest.mock import MagicMock, patch

from bson import ObjectId

mod = importlib.import_module("migrations.004_link_finance_invoices")


def test_resolves_account_via_customer_id_when_present():
    customer_id = str(ObjectId())
    account_id = ObjectId()
    fake_customers = MagicMock()
    fake_customers.find_one.return_value = {"crm_account_id": account_id}

    with patch.object(mod, "get_database", return_value={"customers": fake_customers}):
        result = mod._resolve_account_via_customer_id({"customer_id": customer_id})

    assert result == str(account_id)
    called_filter = fake_customers.find_one.call_args.args[0]
    assert called_filter == {"_id": ObjectId(customer_id)}


def test_returns_none_when_no_customer_id_field():
    assert mod._resolve_account_via_customer_id({}) is None


def test_returns_none_when_customer_id_is_not_a_valid_objectid():
    assert mod._resolve_account_via_customer_id({"customer_id": "not-an-oid"}) is None


def test_returns_none_when_customer_doc_not_found():
    fake_customers = MagicMock()
    fake_customers.find_one.return_value = None

    with patch.object(mod, "get_database", return_value={"customers": fake_customers}):
        result = mod._resolve_account_via_customer_id({"customer_id": str(ObjectId())})

    assert result is None


def test_returns_none_when_customer_has_no_crm_account_id():
    fake_customers = MagicMock()
    fake_customers.find_one.return_value = {"crm_account_id": None}

    with patch.object(mod, "get_database", return_value={"customers": fake_customers}):
        result = mod._resolve_account_via_customer_id({"customer_id": str(ObjectId())})

    assert result is None


def test_migrate_prefers_customer_id_link_over_name_matching():
    """The real bug this fixes: a finance invoice with a resolvable
    customer_id must not fall through to name-based account creation, even
    though it also happens to carry a recognizable customer name field."""
    account_id = ObjectId()
    source_doc = {
        "_id": ObjectId(),
        "customer_id": str(ObjectId()),
        "customer_name": "Some Client Pvt Ltd",
        "total": 1000,
        "status": "paid",
    }

    fake_src_collection = MagicMock()
    fake_src_collection.find.return_value = iter([source_doc])

    fake_invoices_col = MagicMock()
    fake_invoices_col.find.return_value = iter([])  # no prior migrations

    with patch.object(mod, "get_database", return_value=fake_src_collection), \
         patch.object(mod.crm_service, "_col", return_value=fake_invoices_col), \
         patch.object(mod.crm_service, "create") as mock_create, \
         patch.object(mod.crm_service, "get_or_create_account") as mock_get_or_create, \
         patch.object(mod, "_resolve_account_via_customer_id", return_value=str(account_id)):
        # get_database("finance_db") is called twice: once for the source
        # collection (via [source_collection]) and once inside
        # _resolve_account_via_customer_id -- the latter is mocked out
        # directly above, so the single fake_src_collection double is only
        # exercised for the [source_collection] indexing.
        fake_src_collection.__getitem__ = MagicMock(return_value=fake_src_collection)
        stats = mod.migrate_finance_invoices(dry_run=False)

    mock_get_or_create.assert_not_called()
    mock_create.assert_called_once()
    created_doc = mock_create.call_args.args[1]
    assert created_doc["account_id"] == str(account_id)
    assert stats["accounts_linked_via_customer_id"] == 1
    assert stats["accounts_created"] == 0
