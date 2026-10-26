"""Decision Engine core (MARKETING_PLAN Section 4): guardrails, validator, confidence, autonomy, shadow, undo,
stop-loss -- with a fake Qwen and FakeDB."""
import copy
from datetime import datetime, timedelta

import pytest

from marketing import config as mcfg, engine as E
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 25, 10, 0)


def cfg(**over):
    c = copy.deepcopy(mcfg.DEFAULTS)
    c["budget"]["monthly_cap_inr"] = {"SFW": {"google": 100000}}
    c["enforce_go_live_gate"] = False          # the gate has its own test below
    for k, v in over.items():
        c[k] = v
    return c


@pytest.fixture
def env(monkeypatch):
    d = {"email_automation": FakeDB()}
    from platform_core import review_queue, audit
    monkeypatch.setattr(review_queue, "_col", lambda db=None: d["email_automation"]["review_queue_items"])
    monkeypatch.setattr(audit, "log_action", lambda **k: None)
    return d, (lambda n: d[n])


def cand(**kw):
    c = {"decision_type": "D2", "entity_key": "google:camp:1", "entity_label": "SFW Search India", "bu": "SFW",
         "platform": "google", "action": "pause", "parameters": {}, "rule_id": "zero_rfq_30d",
         "evidence": {"spend_inr": 42000, "conversions": 12, "clicks": 900, "rfqs_30d": 0, "cpl_inr": 3500, "target_cpl_inr": 1500}}
    c.update(kw)
    return c


def qwen_says(**out):
    base = {"decision_type": "D2", "action": "pause", "parameters": {}, "expected_impact": {"metric": "cpl", "direction": "down", "size": "medium"},
            "reasoning": "Spend of 42000 produced 0 RFQs in 30 days; CPL 3500 is above the 1500 target.",
            "risks": "pausing loses brand searches", "alternatives_considered": ["cut budget"], "needs_human": False}
    base.update(out)
    return lambda t, br, check: {"status": "ok", "data": base, "problems": check(base, "")}


def test_l1_goes_to_review_with_qwen_reasoning(env):
    d, gd = env
    r = E.decide(cand(), gd=gd, qwen=qwen_says(), cfg=cfg(), now=NOW)
    assert r["status"] == "in_review" and r["reasoning"].startswith("Spend of 42000") and not r["validation_problems"]
    item = d["email_automation"]["review_queue_items"].find_one({"type": "marketing_decision"})
    assert item["suggested"]["action"] == "pause" and item["resume"]["handler"] == "marketing_decision"


def test_invented_numbers_are_caught(env):
    _, gd = env
    r = E.decide(cand(), gd=gd, qwen=qwen_says(reasoning="CPL is 9999 and falling; spend ₹42,000."), cfg=cfg(), now=NOW)
    assert any("9999" in p for p in r["validation_problems"]) and r["status"] == "in_review"
    assert not any("42" in p for p in r["validation_problems"])        # 42,000 is in the brief


def test_disallowed_action_rejected_by_validator(env):
    _, gd = env
    r = E.decide(cand(), gd=gd, qwen=qwen_says(action="delete_account"), cfg=cfg(), now=NOW)
    assert any("not allowed" in p for p in r["validation_problems"]) and r["final_action"] == "pause"   # rule candidate goes on


def test_qwen_down_rule_candidate_still_reviewed(env):
    _, gd = env

    def boom(*a):
        raise ConnectionError("llm down")
    r = E.decide(cand(), gd=gd, qwen=boom, cfg=cfg(autonomy={**mcfg.DEFAULTS["autonomy"], "D2": "L2"}), now=NOW)
    assert r["qwen_status"] == "unavailable" and r["status"] == "in_review"           # rule only never auto-acts
    assert r["confidence"]["score"] < E.CONFIDENCE_TO_ACT


def test_l2_auto_executes_in_shadow_with_undo_window(env):
    d, gd = env
    c = cfg(autonomy={**mcfg.DEFAULTS["autonomy"], "D2": "L2"})
    r = E.decide(cand(evidence={**cand()["evidence"], "conversions": 40}), gd=gd, qwen=qwen_says(), cfg=c, now=NOW)
    assert r["status"] == "shadow_executed" and r["would_execute"]["action"] == "pause" and r["notify"]
    assert r["shadow_reason"] == "shadow mode"
    assert E.undo(str(r["_id"]), "owner", gd=gd)["ok"]
    assert d["email_automation"]["decisions"].find_one({})["status"] == "undone"


def test_live_needs_mode_action_switch_and_executor(env):
    d, gd = env
    calls = []
    E.register_executor("google", "pause", do=lambda p, d: (calls.append(p), {"was": "ENABLED"})[1], undo=lambda u, d: calls.append(("undo", u)))
    try:
        c = cfg(mode="live", autonomy={**mcfg.DEFAULTS["autonomy"], "D2": "L2"})
        ev = {**cand()["evidence"], "conversions": 40}
        r = E.decide(cand(evidence=ev), gd=gd, qwen=qwen_says(), cfg=c, now=NOW)
        assert r["status"] == "shadow_executed" and not calls             # action type not switched to live
        c["action_modes"] = {"D2:pause": "live"}
        r = E.decide(cand(entity_key="google:camp:2", evidence=ev), gd=gd, qwen=qwen_says(), cfg=c, now=NOW)
        assert r["status"] == "executed" and calls and r["undo_payload"] == {"was": "ENABLED"}
        assert E.undo(str(r["_id"]), "owner", gd=gd)["ok"] and calls[-1] == ("undo", {"was": "ENABLED"})
    finally:
        E._EXECUTORS.clear()


def test_kill_switch_and_l0(env):
    _, gd = env
    assert E.decide(cand(), gd=gd, qwen=qwen_says(), cfg=cfg(kill_switch={"global": False, "SFW": True}), now=NOW)["status"] == "skipped"
    assert E.decide(cand(bu="BIM"), gd=gd, qwen=qwen_says(), cfg=cfg(autonomy={"D2": "L0"}), now=NOW)["status"] == "skipped"


def test_conflicting_decision_blocked_inside_cooldown(env):
    _, gd = env
    E.decide(cand(), gd=gd, qwen=qwen_says(), cfg=cfg(), now=NOW)
    r = E.decide(cand(action="resume"), gd=gd, qwen=qwen_says(action="resume"), cfg=cfg(), now=NOW + timedelta(days=2))
    assert r["status"] == "blocked" and "cooldown" in r["reason"]
    again = E.decide(cand(), gd=gd, qwen=qwen_says(), cfg=cfg(), now=NOW + timedelta(days=1))
    assert again["status"] == "skipped"                                   # same action already in review


def test_budget_guardrails():
    c = cfg()
    base = {"decision_type": "D1", "bu": "SFW", "platform": "google", "created_at": NOW,
            "evidence": {"realloc_pct_this_week": 10, "month_spend_inr": 95000}}
    p = E.guardrail_problems(base, {"shift_pct": 25, "net_change_inr": 6000}, c, [])
    assert any("max daily" in x for x in p) and any("weekly" in x for x in p) and any("raises total" in x for x in p)
    assert any("cap would be exceeded" in x for x in p)
    assert any("no monthly cap" in x for x in E.guardrail_problems({**base, "bu": "BIM"}, {"shift_pct": 5}, c, []))
    assert E.guardrail_problems(base, {"shift_pct": 4, "net_change_inr": 0}, c, []) == []


def test_bid_guardrails_and_pause_limits():
    c = cfg()
    d3 = {"decision_type": "D3", "created_at": NOW, "evidence": {}}
    hist = [{"status": "executed", "created_at": NOW - timedelta(days=3)}]
    p = E.guardrail_problems(d3, {"change_pct": 20}, c, hist)
    assert any("> 15%" in x for x in p) and any("3 days ago" in x for x in p)
    d2 = {"decision_type": "D2", "created_at": NOW, "evidence": {"conversions": 1, "spend_inr": 900, "learning_phase": True}}
    p = E.guardrail_problems(d2, {}, c, [], action="pause")
    assert any("learning" in x for x in p) and any("too little data" in x for x in p)
    assert E.guardrail_problems(d2, {}, c, [], action="flag") == []


def test_l3_capped_for_budget_types(env):
    _, gd = env
    c = cfg(autonomy={**mcfg.DEFAULTS["autonomy"], "D1": "L3"})
    r = E.decide(cand(decision_type="D1", action="shift_budget", entity_key="google:SFW",
                      evidence={"realloc_pct_this_week": 0, "month_spend_inr": 1000, "conversions": 50}),
                 gd=gd, qwen=qwen_says(decision_type="D1", action="shift_budget", parameters={"shift_pct": 5, "net_change_inr": 0},
                                       reasoning="Move 5 percent."), cfg=c, now=NOW)
    assert r["autonomy"] == "L2"


def test_review_approval_executes_and_rejection_syncs(env):
    d, gd = env
    r = E.decide(cand(), gd=gd, qwen=qwen_says(), cfg=cfg(), now=NOW)
    item = d["email_automation"]["review_queue_items"].find_one({"type": "marketing_decision"})
    out = E.resume_from_review(item, {"action": "approve", "by": "owner", "at": NOW, "value": item["suggested"]}, gd=gd)
    assert out["status"] == "shadow_executed" and out["human"] == "approved"
    r2 = E.decide(cand(entity_key="google:camp:9"), gd=gd, qwen=qwen_says(), cfg=cfg(), now=NOW)
    it2 = [i for i in d["email_automation"]["review_queue_items"].docs if i["ref"]["id"] == str(r2["_id"])][0]
    it2["status"] = "rejected"
    assert E.sync_rejections(gd) == 1
    assert d["email_automation"]["decisions"].find_one({"entity_key": "google:camp:9"})["human"] == "rejected"


def test_confidence_is_code_computed():
    c = cand()
    full = E.confidence({**c, "evidence": {"conversions": 40}}, "pause", {"acceptance": 1.0, "accuracy": 1.0})
    assert full["score"] == 1.0
    disagree = E.confidence({**c, "evidence": {"conversions": 40}}, "resume", {"acceptance": 1.0, "accuracy": 1.0})
    assert disagree["score"] == 0.7 - 0.0 or disagree["agreement"] == 0.0
    assert E.confidence(c, None, {})["score"] < E.CONFIDENCE_TO_ACT


def test_outcomes_and_stop_loss(env, monkeypatch):
    d, gd = env
    col = d["email_automation"]["decisions"]
    for i in range(10):
        col.insert_one({"decision_type": "D4", "status": "executed", "entity_key": f"k{i}", "bu": "SFW",
                        "executed_at": NOW - timedelta(days=20 - i), "outcome_due_at": NOW - timedelta(days=1),
                        "expected_impact": {"direction": "down"}, "created_at": NOW - timedelta(days=20)})
    set_calls = []
    from platform_core import config_store
    monkeypatch.setattr(config_store, "get", lambda s: cfg(autonomy={**mcfg.DEFAULTS["autonomy"], "D4": "L2", "D9": "L2"}))
    monkeypatch.setattr(config_store, "set", lambda s, v, actor: set_calls.append(v))
    c = cfg(autonomy={**mcfg.DEFAULTS["autonomy"], "D4": "L2", "D9": "L2"})
    rep = E.measure_due(gd, metric=lambda dd: {"baseline": 100, "actual": 130, "higher_is_better": False, "name": "wasted ₹"},
                        now=NOW, cfg=c)
    assert rep["measured"] == 10 and rep["downgraded"] == ["D4"]
    assert set_calls and set_calls[0]["autonomy"]["D4"] == "L1" and set_calls[0]["autonomy"]["D9"] == "L2"   # others kept
    o = col.find_one({"entity_key": "k0"})["outcome"]
    assert o["better_than_baseline"] is False and o["direction_correct"] is False
    assert d["email_automation"]["decision_outcomes"].count_documents({}) == 10


def test_qwen_lane_tasks_registered_without_dropping_existing():
    from platform_core import config_store
    before = set(config_store.SECTIONS["qwen"]()["tasks"])
    mcfg.register_qwen_tasks()
    mcfg.register_qwen_tasks()                       # idempotent
    tasks = config_store.SECTIONS["qwen"]()["tasks"]
    assert before <= set(tasks) and {"marketing_decision_p1", "marketing_decision_p2", "marketing_decision_p3"} <= set(tasks)
    assert tasks["marketing_decision_p1"]["priority"] == "P1" and tasks["marketing_decision_p3"]["max_input_chars"] <= 2500
    assert set(E.QWEN_TASK.values()) == set(mcfg.QWEN_TASKS)


def test_brief_fits_the_small_model_context():
    import json
    cap = 4 * 600
    c = cand(evidence={f"m{i}": i * 1000.5 for i in range(80)})
    b = E.brief(c, cfg(), [{"action": "pause", "status": "executed", "outcome": {"summary": "x" * 500}}] * 3)
    assert len(json.dumps(b, default=str)) <= cap and len(b["recent"]) < 3        # recent history dropped first
    huge = E.brief(cand(evidence={f"metric_{i}": i * 1000.5 for i in range(300)}), cfg(), [])
    assert len(huge["metrics"]) == 12                                               # then metrics trimmed to the top 12


def test_go_live_gate_holds_l2_at_l1_until_85pct_agreement(env):
    d, gd = env
    c = cfg(autonomy={**mcfg.DEFAULTS["autonomy"], "D2": "L2"}, enforce_go_live_gate=True)
    ev = {**cand()["evidence"], "conversions": 40}
    r = E.decide(cand(evidence=ev), gd=gd, qwen=qwen_says(), cfg=c, now=NOW)
    assert r["status"] == "in_review" and r["autonomy"] == "L1" and "judged" in r["gate"]
    col = d["email_automation"]["decisions"]
    for i in range(10):
        col.insert_one({"decision_type": "D2", "human": "approved" if i < 9 else "rejected", "created_at": NOW - timedelta(days=2),
                        "entity_key": f"old{i}", "status": "approved"})
    r = E.decide(cand(entity_key="google:camp:77", evidence=ev), gd=gd, qwen=qwen_says(), cfg=c, now=NOW)
    assert r["status"] == "shadow_executed"                                 # 9/10 = 90% >= 85%
