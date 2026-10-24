"""Vendor engagement (CRM plan 3.7a): shortlist, request, timing, selection, invoice, scorecard."""
from datetime import datetime

from bson import ObjectId

from vendors import bids, runner
from vendors.bids import DEFAULTS as CFG
from tests._fakemongo import FakeDB


def _v(name, score, countries=("IN",), status="active"):
    return {"name": name, "status": status, "procurement": {"countries": list(countries), "quality_score": score}}


def test_shortlist_by_country_and_score_with_minimum():
    vs = [_v("A", 70), _v("B", 90), _v("C", 50), _v("D", 95, ("US",)), _v("E", 80, status="inactive"), _v("F", 65)]
    assert [v["name"] for v in bids.shortlist(vs, "in")] == ["B", "A", "F"]


def test_bid_request_has_ref_and_never_the_client_name():
    r = bids.bid_request({"country": "IN", "loi_minutes": 15, "ir_percent": 25, "target": "Hansa panel SUV owners"},
                         400, bids.ref_id("6adb49f57e9ca4b06a1e8c37", 1), client_name="Hansa Research Group")
    assert r["subject"].startswith("[VB-1e8c37-1]")
    assert "hansa" not in (r["subject"] + r["body"]).lower() and "n=400" in r["subject"]


def test_working_hours_skip_nights_and_weekends():
    fri_5pm = datetime(2026, 10, 23, 17, 0)
    assert bids.add_working_hours(fri_5pm, 4) == datetime(2026, 10, 26, 13, 0)    # Monday 13:00 IST


def test_follow_up_then_no_bid():
    b = {"status": "requested", "requested_at_ist": datetime(2026, 10, 26, 10, 0)}
    assert bids.bid_due_action(b, datetime(2026, 10, 26, 13, 0)) is None
    assert bids.bid_due_action(b, datetime(2026, 10, 26, 14, 30)) == "follow_up"
    assert bids.bid_due_action({**b, "followed_up_at": 1}, datetime(2026, 10, 26, 15, 0)) is None
    assert bids.bid_due_action(b, datetime(2026, 10, 29, 10, 0)) == "no_bid"


def test_bid_parse_check_rejects_invented_numbers():
    assert bids.bid_code_check({"cpi": 2.5, "feasible_n": 300}, "We can do 300 at USD 2.5") == []
    assert bids.bid_code_check({"cpi": 3.0}, "We can do 300 at USD 2.5") == ["cpi 3.0 not found in the mail"]


def _b(cpi, n, score=80):
    return {"_id": ObjectId(), "status": "received", "cpi": cpi, "feasible_n": n, "quality_score": score, "vendor_id": "v"}


def test_auto_select_cheapest_cover_with_margin_floor():
    ok = bids.auto_select([_b(2.0, 200), _b(1.5, 150), _b(1.0, 100, score=40)], 300, client_cpi=4.0, own_cost=1.2,
                          own_n=200, margin_floor=0.30, min_quality=60)
    assert ok["ok"] and [p["cpi"] for p in ok["picked"]] == [1.5, 2.0] and sum(p["n"] for p in ok["picked"]) == 300
    thin = bids.auto_select([_b(3.5, 300)], 300, client_cpi=4.0, own_cost=1.2, own_n=0, margin_floor=0.30, min_quality=60)
    assert not thin["ok"] and "below floor" in thin["reason"]
    short = bids.auto_select([_b(1.0, 100)], 300, client_cpi=4.0, own_cost=1.0, own_n=0, margin_floor=0.3, min_quality=60)
    assert not short["ok"] and "cover 100 of 300" in short["reason"]


def test_invoice_match_and_mismatch_lists_the_difference():
    po = {"cpi": 2.0, "currency": "USD"}
    assert bids.invoice_match(po, 150, {"n": 150, "amount": 300, "currency": "USD"})["match"]
    bad = bids.invoice_match(po, 150, {"n": 160, "amount": 320, "currency": "USD"})
    assert not bad["match"] and len(bad["differences"]) == 2


def test_scorecard_running_means():
    s1 = bids.scorecard({}, {"response_hours": 2, "committed_n": 100, "delivered_n": 100, "rejection_rate": 0.1,
                             "invoice_matched": True})
    s2 = bids.scorecard(s1, {"response_hours": 6, "committed_n": 100, "delivered_n": 50, "rejection_rate": 0.3,
                             "invoice_matched": False})
    assert s2["projects"] == 2 and s2["delivery_ratio"] == 0.75 and round(s2["rejection_rate"], 2) == 0.2
    assert s2["quality_score"] < s1["quality_score"]


def test_shadow_run_records_but_never_changes_bids(monkeypatch):
    d = {n: FakeDB() for n in ("crm_db", "email_automation", "torpedo_gmail")}
    monkeypatch.setattr(runner, "_gd", lambda: (lambda name: d[name]))
    from platform_core import config_store
    monkeypatch.setattr(config_store, "get", lambda s, db=None: config_store.defaults(s))
    bid = d["crm_db"]["vendor_bids"].insert_one({"status": "requested", "ref_id": "VB-x-1",
                                                 "requested_at_ist": datetime(2026, 10, 20, 10, 0)}).inserted_id
    mid = d["torpedo_gmail"]["email_metadata"].insert_one({"subject": "Re: [VB-x-1]", "body_plain": "300 at 2.5"}).inserted_id
    d["email_automation"]["mail_decisions"].insert_one({"message_id": str(mid), "link": {"type": "vendor_bid",
                                                                                          "vendor_bid_id": str(bid)}})
    s = runner.run(now=datetime(2026, 10, 26, 6, 0), run_model=lambda **kw: {"status": "review", "data": {"cpi": 2.5, "feasible_n": 300}})
    assert s["no_bid"] == 1 and s["parsed"] == 1
    assert d["crm_db"]["vendor_bids"].find_one({"_id": bid})["status"] == "requested"


def test_award_gives_po_entry_link_and_regrets_the_rest():
    a, b, c = _b(1.5, 150), _b(2.0, 200), _b(3.0, 100)
    sel = bids.auto_select([a, b, c], 300, client_cpi=5, own_cost=0, own_n=0, margin_floor=0.3, min_quality=60)
    plan = bids.award_plan(sel, [a, b, c], base_url="https://torpedo.cogentixresearch.com", survey_no="P1",
                           country="in", vendor_redirects={"complete": "x"})
    assert len(plan["awards"]) == 2 and plan["regrets"] == [str(c["_id"])]
    assert plan["awards"][0]["entry_link"].endswith("/takesurvey?api=false&pid=P1&vid=v&cc=IN&rid=[RID]")


def test_daily_counts_per_vendor():
    t = [{"vendorId": "5", "status": "COMPLETE"}, {"vendorId": "5", "status": "TERMINATED"}, {"vendorId": "5", "status": "COMPLETE"}]
    assert bids.daily_vendor_counts(t) == {"5": {"complete": 2, "terminated": 1}}
