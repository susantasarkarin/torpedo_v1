"""Every RFQ has an estimate; a change of scope or price is a new version, the old one kept."""
from datetime import datetime

from bson import ObjectId

from rfq import estimates
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 26)


def _opp(**rfq):
    return {"_id": ObjectId(), "status": "open", "title": "Brand tracker", "created_at": NOW,
            "metadata": {"rfq": {"country": "IN", "sample_size": 500, "loi": 15, "ir": 30, **rfq}}}


def _decision(cpi=4.0, n=500):
    return {"line_items": [{"country": "US", "n": n, "loi_minutes": 10, "ir_percent": 50, "methodology": "CAWI"}],
            "pricing": [{"country": "US", "client_cpi_usd": cpi}]}


def test_first_sync_is_version_one_then_unchanged():
    fin, opp = FakeDB(), _opp()
    res, doc = estimates.sync(fin, opp, None, now=NOW)
    assert res == "created" and doc["version"] == 1 and doc["is_latest"] and doc["status"] == "draft"
    assert doc["estimate_number"].endswith("-V1")
    assert estimates.sync(fin, opp, None, now=NOW)[0] == "unchanged"
    assert fin["estimates"].count_documents({}) == 1


def test_price_change_is_a_new_version_and_old_is_kept_superseded():
    fin, opp = FakeDB(), _opp()
    estimates.sync(fin, opp, _decision(cpi=4.0), now=NOW)
    res, v2 = estimates.sync(fin, opp, _decision(cpi=4.5), now=NOW)
    assert res == "new_version" and v2["version"] == 2 and v2["total_amount"] == 2250
    assert v2["change"]["price"] == ["US CPI: 4.0 -> 4.5", "value: 2000.0 -> 2250.0"] and not v2["change"]["scope"]
    v1 = fin["estimates"].find_one({"version": 1})
    assert v1["is_latest"] is False and v1["status"] == "superseded" and v1["superseded_by"] == str(v2["_id"])


def test_scope_change_is_named_and_sent_version_keeps_its_status():
    fin, opp = FakeDB(), _opp()
    _, v1 = estimates.sync(fin, opp, _decision(n=500), now=NOW)
    fin["estimates"].update_one({"_id": v1["_id"]}, {"$set": {"status": "sent"}})
    _, v2 = estimates.sync(fin, opp, _decision(n=800), now=NOW)
    assert "US n: 500.0 -> 800.0" in v2["change"]["scope"]
    assert fin["estimates"].find_one({"version": 1})["status"] == "sent"


def test_rfq_status_sets_new_version_status_and_quoted_total_is_carried():
    fin = FakeDB()
    won = {**_opp(), "status": "won", "amount": 3000, "currency": "INR"}
    _, doc = estimates.sync(fin, won, None, now=NOW)
    assert doc["status"] == "accepted" and doc["total_amount"] == 3000 and doc["items"][0]["rate"] == 6.0
    _, closed = estimates.sync(fin, {**_opp(), "status": "closed"}, None, now=NOW)
    assert closed["status"] == "expired" and closed["total_amount"] == 0


def test_person_built_estimate_supersedes():
    fin, opp = FakeDB(), _opp()
    estimates.sync(fin, opp, None, now=NOW)
    items = [{"description": "CAWI IN", "quantity": 500, "unit_price": 5, "amount": 2500}]
    res, v2 = estimates.sync(fin, opp, None, now=NOW, override={"line_items": items, "total": 2950, "status": "draft"})
    assert res == "new_version" and v2["total_amount"] == 2950 and "set by a person" in v2["change"]["price"]


def test_dry_run_writes_nothing():
    fin = FakeDB()
    res, doc = estimates.sync(fin, _opp(), None, now=NOW, apply=False)
    assert res == "created" and fin["estimates"].count_documents({}) == 0


def test_blanks_becoming_known_complete_the_same_version():
    fin = FakeDB()
    opp = {**_opp(), "metadata": {"rfq": {}}}                      # nothing extracted yet
    estimates.sync(fin, opp, None, now=NOW)
    res, doc = estimates.sync(fin, opp, _decision(cpi=4.0), now=NOW, reason="re-extraction")
    assert res == "filled" and doc["version"] == 1 and doc["total_amount"] == 2000
    assert fin["estimates"].count_documents({}) == 1 and len(fin["estimates"].find_one({})["fills"]) == 1
    assert estimates.sync(fin, opp, _decision(cpi=5.0), now=NOW)[0] == "new_version"   # a known price changed


def test_sent_version_is_never_filled_in_place():
    fin = FakeDB()
    opp = {**_opp(), "metadata": {"rfq": {}}}
    _, v1 = estimates.sync(fin, opp, None, now=NOW)
    fin["estimates"].update_one({"_id": v1["_id"]}, {"$set": {"status": "sent"}})
    assert estimates.sync(fin, opp, _decision(), now=NOW)[0] == "new_version"
