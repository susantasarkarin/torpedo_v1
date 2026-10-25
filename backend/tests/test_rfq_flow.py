"""RFQ flow (CRM plan 3.4 / 3.5): defaults, missing info, pricing, shadow runner."""
from datetime import datetime, timedelta

import pytest
from bson import ObjectId

from pricing import rate_card
from pricing.engine import DEFAULTS as PRICING
from platform_core import config_store
from rfq import flow, runner
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 24)
CFG = config_store.defaults("rfq")
HANSA = {"_id": ObjectId(), "name": "Hansa Research Group"}


def _rows(country="IN", n=6, cpi=1.0):
    return [{"country": country, "loi": 15, "ir": 25, "cpi": cpi + i * 0.1, "completes": 100,
             "activated_at": NOW - timedelta(days=5)} for i in range(n)]


def _ext(items, status="review"):
    return lambda **kw: {"status": status, "data": {"line_items": items}, "job_id": "j1", "problems": []}


def test_hansa_defaults_fill_ir_and_country_and_cawi_everywhere():
    rules = list(CFG["client_defaults_seed"])
    items = flow.apply_defaults([{"country": None, "n": 500, "loi_minutes": 15}],
                                flow.client_defaults(HANSA, rules), CFG["default_methodology"])
    assert items[0]["country"] == "IN" and items[0]["ir_percent"] == 60 and items[0]["methodology"] == "CAWI"
    assert set(items[0]["defaulted"]) == {"country", "ir_percent", "methodology"}
    other = flow.apply_defaults([{"country": "us"}], flow.client_defaults({"name": "Acme"}, rules), "CAWI")
    assert other[0]["country"] == "US" and "ir_percent" not in other[0]


def test_account_id_rule_beats_name_rule():
    rules = [{"account_id": str(HANSA["_id"]), "defaults": {"ir_percent": 40}}] + list(CFG["client_defaults_seed"])
    assert flow.client_defaults(HANSA, rules) == {"ir_percent": 40}


def test_missing_critical_fields_ask_only_for_those():
    d = flow.process({"_id": ObjectId()}, "x", account={"name": "Acme"}, bu="SFW", rules=[], rows=[], cfg=CFG,
                     pricing_cfg=PRICING, run=_ext([{"country": "US", "loi_minutes": 10}, {"country": "GB", "n": 200}]),
                     now=NOW)
    assert d["status"] == "awaiting_info"
    assert d["missing"] == [{"line": 1, "field": "n"}, {"line": 2, "field": "loi_minutes"}]
    assert "US: sample size (N)" in d["missing_info_draft"] and "GB: interview length (LOI)" in d["missing_info_draft"]


def test_cawi_line_priced_both_weightings_non_cawi_goes_to_a_person():
    items = [{"country": "IN", "n": 500, "loi_minutes": 15, "ir_percent": 25},
             {"country": "IN", "n": 100, "loi_minutes": 15, "ir_percent": 25, "methodology": "CATI"}]
    d = flow.process({"_id": ObjectId()}, "x", account={"name": "Acme"}, bu="SFW", rules=[], rows=_rows(),
                     cfg=CFG, pricing_cfg=PRICING, run=_ext(items, status="ok"), now=NOW)
    cawi, cati = d["pricing"]
    assert set(cawi["breakdown"]) == {"completes", "recency"} and cawi["client_cpi_usd"] == round(1.2 * 1.5, 2)
    assert not cawi["review"] and cati["review"] and "CATI" in cati["review_reasons"][0]
    assert d["status"] == "priced_review"


def test_bounds_and_client_history_send_a_price_to_review():
    cfg = {**CFG, "cpi_bounds_usd": {"min": 2.0, "max": None}}
    it = [{"country": "IN", "loi_minutes": 15, "ir_percent": 25, "methodology": "CAWI"}]
    p = flow.price_items(it, _rows(), bu="SFW", now=NOW, cfg=cfg, pricing_cfg=PRICING, history={"IN": [5.0, 5.2, 4.9]})
    assert any("below bound" in r for r in p[0]["review_reasons"])
    assert any("recent median" in r for r in p[0]["review_reasons"])


def test_unknown_bu_never_guesses_a_markup():
    it = [{"country": "IN", "loi_minutes": 15, "ir_percent": 25, "methodology": "CAWI"}]
    p = flow.price_items(it, _rows(), bu=None, now=NOW, cfg=CFG, pricing_cfg=PRICING)
    assert p[0]["review"] and "BU unknown" in p[0]["review_reasons"][0]


def test_code_check_drops_required_but_keeps_invented_numbers():
    probs = flow.code_check({"line_items": [{"country": "IN", "loi_minutes": 99}]}, "India survey, 15 min")
    assert not any(p.startswith("required") for p in probs) and any("LOI 99" in p for p in probs)


def test_rate_card_uses_verified_ids_only():
    assert rate_card.country_of(8) == "GB" and rate_card.country_of("27") is None
    assert rate_card.country_of("ENG_IN") == "IN"
    from routers.cint import CINT_COUNTRY_LANGUAGE_MAP
    assert CINT_COUNTRY_LANGUAGE_MAP[8] == "GB" and CINT_COUNTRY_LANGUAGE_MAP[16] == "BR"


@pytest.fixture
def dbs(monkeypatch):
    d = {n: FakeDB() for n in ("crm_db", "email_automation", "torpedo_gmail", "cint_research")}
    monkeypatch.setattr(runner, "_gd", lambda: (lambda name: d[name]))
    monkeypatch.setattr(runner, "_bu", lambda aid, opp: "SFW")
    monkeypatch.setattr(config_store, "get", lambda section, db=None: config_store.defaults(section))
    return d


def test_shadow_runner_decides_once_and_never_touches_the_rfq(dbs):
    mid = dbs["torpedo_gmail"]["email_metadata"].insert_one({"subject": "RFQ India", "body_plain": "N=500 LOI 15 IR 25"}).inserted_id
    acc = dbs["crm_db"]["accounts"].insert_one({"name": "Acme"}).inserted_id
    oid = dbs["crm_db"]["opportunities"].insert_one({"status": "open", "account_id": str(acc), "metadata": {"rfq": {
        "source_email_id": str(mid), "received_at": NOW - timedelta(days=1)}}}).inserted_id
    run = _ext([{"country": "IN", "n": 500, "loi_minutes": 15, "ir_percent": 25}])
    s1 = runner.run_batch(now=NOW, run=run, rows=_rows())
    s2 = runner.run_batch(now=NOW, run=run, rows=_rows())
    assert s1["decided"] == 1 and s2["decided"] == 0
    dec = dbs["email_automation"]["rfq_decisions"].find_one({"opportunity_id": str(oid)})
    assert dec["mode"] == "shadow" and dec["pricing"][0]["client_cpi_usd"] is not None
    assert "flow" not in dbs["crm_db"]["opportunities"].find_one({"_id": oid})["metadata"]["rfq"]


def test_rules_tier_answers_a_plain_rfq_without_any_model():
    from rfq import rules_extract
    text = "RFQ: Online survey in India, n=500, LOI 15 mins, IR 25%. Please share CPI."
    r = rules_extract.extract(text)
    assert rules_extract.complete(r)
    li = r["line_items"][0]
    assert (li["country"], li["n"], li["loi_minutes"], li["ir_percent"], li["methodology"]) == ("IN", 500, 15, 25.0, "CAWI")
    assert flow.code_check(r, text) == []


def test_rules_leave_ambiguous_fields_empty_and_map_per_country_sizes():
    from rfq import rules_extract
    two_n = rules_extract.extract("India n=500 and also 300 completes, LOI 10 min")
    assert two_n["line_items"][0]["n"] is None and not rules_extract.complete(two_n)
    multi = rules_extract.extract("Markets: India - 500, United States - 300. LOI 12 minutes, IR 40%")
    sizes = {li["country"]: li["n"] for li in multi["line_items"]}
    assert sizes == {"IN": 500, "US": 300} and rules_extract.complete(multi)


def test_flow_accepts_rules_and_never_calls_a_model_for_a_plain_rfq():
    calls = []

    def run(**kw):
        calls.append(kw)
        from platform_core import ladder
        assert kw["rules_complete"] is True
        return {"status": "review", "data": kw["rules_result"], "tier": "rules", "problems": []}
    d = flow.process({"_id": ObjectId()}, "India n=500, LOI 15 min, IR 25%", account={"name": "Acme"}, bu="SFW",
                     rules=[], rows=_rows(), cfg=CFG, pricing_cfg=PRICING, run=run, now=NOW)
    assert d["extraction_tier"] == "rules" and d["line_items"][0]["n"] == 500
