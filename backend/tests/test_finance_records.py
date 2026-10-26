"""Finance record page edits: protected fields stay, totals follow the lines, old values kept."""
from datetime import datetime

import pytest

import finance_records as fr
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 26)


def _est(fin):
    return fin["estimates"].insert_one({"estimate_number": "EST-1-V1", "version": 1, "status": "draft",
                                        "items": [{"quantity": 100, "rate": 2, "amount": 200}], "total_amount": 200,
                                        "tax_amount": 0}).inserted_id


def test_edit_recalculates_totals_and_keeps_history():
    fin = FakeDB()
    eid = _est(fin)
    res = fr.update_record(fin, "estimates", str(eid), {
        "items": [{"description": "CAWI IN", "quantity": 500, "rate": 3}], "status": "sent",
        "expiry_date": "2026-11-30", "version": 9, "customer_name": "shown only"}, now=NOW)
    doc = fin["estimates"].find_one({"_id": eid})
    assert doc["total_amount"] == doc["total"] == 1500 and doc["items"][0]["amount"] == 1500
    assert doc["version"] == 1 and "customer_name" not in doc            # protected / display-only
    assert doc["expiry_date"] == datetime(2026, 11, 30) and doc["status"] == "sent"
    assert doc["edit_history"][0]["old"]["status"] == "draft"
    assert "version" not in res["changed"]


def test_no_change_writes_nothing_and_unknown_kind_is_refused():
    fin = FakeDB()
    eid = _est(fin)
    assert fr.update_record(fin, "estimates", str(eid), {"status": "draft"}, now=NOW) == {"changed": []}
    with pytest.raises(KeyError):
        fr.update_record(fin, "ledger", str(eid), {"x": 1})
    with pytest.raises(LookupError):
        fr.update_record(fin, "estimates", "6a0000000000000000000000", {"status": "sent"})
