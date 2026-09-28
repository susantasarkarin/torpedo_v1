"""
Invoices raised from an Operations project (routers/operations.py
create_invoice_from_project, used by close_project).

Found by a live end-to-end sample on 2026-09-28: a USD project's final invoice
came out in INR, and its dates were stored as strings, which the daily
overdue check ({"due_date": {"$lt": now}}) can never match.
"""
from datetime import datetime

from bson import ObjectId

import routers.operations as ops


class _Col:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _match(self, doc, q):
        return all(doc.get(k) == v for k, v in q.items() if not isinstance(v, dict))

    def find_one(self, q=None, *a, **k):
        return next((d for d in self.docs if self._match(d, q or {})), None)

    def count_documents(self, q=None):
        return len(self.docs)

    def insert_one(self, doc):
        doc["_id"] = ObjectId()
        self.docs.append(doc)

        class _R:
            inserted_id = doc["_id"]
        return _R()

    def update_one(self, *a, **k):
        pass


def _wire(monkeypatch, project):
    invoices = _Col()
    monkeypatch.setattr(ops, "projects_collection", _Col([project]))
    monkeypatch.setattr(ops, "invoices_collection", invoices)
    monkeypatch.setattr(ops, "customers_collection", _Col())
    monkeypatch.setattr(ops, "accounts_collection", _Col())
    return invoices


def _project(**kw):
    p = {"_id": ObjectId(), "projectName": "Brand tracker", "projectValue": 1000.0,
         "customer_id": str(ObjectId())}
    p.update(kw)
    return p


def _raise(monkeypatch, project, data=None):
    invoices = _wire(monkeypatch, project)
    data = {"customer_id": project["customer_id"], **(data or {})}
    ops.create_invoice_from_project(str(project["_id"]), data)
    return invoices.docs[-1]


def test_invoice_uses_the_projects_own_currency(monkeypatch):
    inv = _raise(monkeypatch, _project(currency="USD"))
    assert inv["currency_code"] == "USD" and inv["currency"] == "USD"


def test_explicit_currency_wins_over_the_project(monkeypatch):
    inv = _raise(monkeypatch, _project(currency="USD"), {"currency_code": "EUR"})
    assert inv["currency_code"] == "EUR"


def test_legacy_project_without_currency_still_defaults_to_inr(monkeypatch):
    inv = _raise(monkeypatch, _project())
    assert inv["currency_code"] == "INR"


def test_dates_are_stored_as_datetimes(monkeypatch):
    inv = _raise(monkeypatch, _project())
    assert isinstance(inv["invoice_date"], datetime)
    assert isinstance(inv["due_date"], datetime)
    assert (inv["due_date"] - inv["invoice_date"]).days == 30


def test_indian_client_is_charged_18_percent_gst(monkeypatch):
    inv = _raise(monkeypatch, _project(currency="INR"))
    assert inv["tax_total"] == 180.0 and inv["total_amount"] == 1180.0


def test_export_invoice_carries_no_gst(monkeypatch):
    inv = _raise(monkeypatch, _project(currency="USD"))
    assert inv["tax_total"] == 0 and inv["total_amount"] == 1000.0


def test_close_items_are_actually_taxed(monkeypatch):
    # The close invoice passes items with a rate and no amount: the line said
    # 18% and the total charged 0%.
    items = [{"description": "Final billing", "quantity": 1, "rate": 500.0, "tax_rate": 18}]
    inv = _raise(monkeypatch, _project(currency="INR"), {"items": items})
    assert inv["items"][0]["tax_amount"] == 90.0 and inv["total_amount"] == 590.0


def test_a_rate_set_by_hand_wins(monkeypatch):
    inv = _raise(monkeypatch, _project(currency="INR"), {"tax_rate": 5})
    assert inv["tax_total"] == 50.0


def test_gstin_means_domestic_whatever_the_currency():
    assert ops.default_gst_rate("USD", "27AABCU9603R1ZM") == 18.0
    assert ops.default_gst_rate("USD", None) == 0.0
    assert ops.default_gst_rate(None, None) == 18.0


def test_string_dates_from_the_ui_are_parsed(monkeypatch):
    inv = _raise(monkeypatch, _project(), {"invoice_date": "2026-10-01", "due_date": "2026-10-31"})
    assert inv["invoice_date"] == datetime(2026, 10, 1)
    assert inv["due_date"] == datetime(2026, 10, 31)
