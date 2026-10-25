"""Evaluation before go-live (MARKETING_PLAN 4.5)."""
from datetime import datetime, timedelta

from marketing import config as mcfg, engine as E, evaluation as V
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 25, 23, 0)


def gdb():
    d = {"email_automation": FakeDB()}
    return d, (lambda n: d[n])


def test_three_cases_per_decision_type_and_seed_is_idempotent():
    from collections import Counter
    assert Counter(c["decision_type"] for c in V.CASES) == {t: 3 for t in mcfg.DECISION_TYPES}
    assert all(c["expected"] in E.ACTIONS[c["decision_type"]] for c in V.CASES)
    d, gd = gdb()
    assert V.seed(gd, NOW) == 42 and V.seed(gd, NOW) == 0
    assert d["email_automation"]["marketing_eval_cases"].find_one({})["status"] == "proposed"


def echo_rule(t, br, check):
    """A perfect model: repeats the rule's suggestion with brief numbers only."""
    out = {"decision_type": t, "action": br["rule_suggests"]["action"], "parameters": br["rule_suggests"]["parameters"] or {},
           "reasoning": "Follows the rule.", "expected_impact": {"metric": "x", "direction": "down", "size": "small"},
           "risks": "low", "alternatives_considered": [], "needs_human": True}
    return {"status": "ok", "data": out}


def test_run_eval_reports_validity_agreement_latency():
    d, gd = gdb()
    V.seed(gd, NOW)
    cfg = mcfg.DEFAULTS
    rep = V.run_eval(gd, qwen=echo_rule, cfg=cfg, now=NOW)
    assert rep["cases"] == 42 and set(rep["types"]) == set(mcfg.DECISION_TYPES)
    for t, r in rep["types"].items():
        assert r["validity"] == 1.0, (t, r)
        assert r["agreement_with_rules"] == 1.0 and r["median_latency_s"] is not None
    assert d["email_automation"]["marketing_eval_runs"].count_documents({}) == 1


def test_bad_model_scores_low_and_deferred_is_not_counted():
    d, gd = gdb()
    V.seed(gd, NOW)

    def bad(t, br, check):
        return {"status": "ok", "data": {"decision_type": t, "action": "delete_everything", "parameters": {},
                                         "reasoning": "Spend was 999999.", "expected_impact": {}, "risks": "",
                                         "alternatives_considered": [], "needs_human": False}}
    rep = V.run_eval(gd, qwen=bad, types=["D2", "D4"], now=NOW)
    assert rep["types"]["D2"]["validity"] == 0.0 and rep["types"]["D4"]["agreement_with_rules"] == 0.0
    rep2 = V.run_eval(gd, qwen=lambda t, br, chk: {"status": "deferred"}, types=["D7"], now=NOW)
    assert rep2["types"]["D7"]["answered"] == 0 and rep2["types"]["D7"]["deferred"] == 3


def test_user_agreement_and_gate():
    d, gd = gdb()
    col = d["email_automation"]["decisions"]
    for i in range(12):
        col.insert_one({"decision_type": "D4", "human": "approved", "created_at": NOW - timedelta(days=3),
                        "human_corrected": i == 0})
    col.insert_one({"decision_type": "D4", "human": "rejected", "created_at": NOW - timedelta(days=3)})
    col.insert_one({"decision_type": "D4", "human": "rejected", "created_at": NOW - timedelta(days=30)})   # outside 14 d
    ua = V.user_agreement(gd, now=NOW)["D4"]
    assert ua == {"judged": 13, "agreed": 11, "agreement": 0.846}
    g = V.go_live_ok("D4", gd, cfg=mcfg.DEFAULTS, now=NOW)
    assert not g["ok"] and "0.846" in g["why"]
    assert not V.go_live_ok("D9", gd, cfg=mcfg.DEFAULTS, now=NOW)["ok"]
