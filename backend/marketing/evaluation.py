"""Decision Engine evaluation before go-live (MARKETING_PLAN 4.5).

History is empty for most decision types, so the test set starts synthetic:
3 realistic cases per type (marketing.evaluation.CASES), each with the expected
action. They are written to email_automation.marketing_eval_cases with
status "proposed"; the owner marks each "agreed" (or corrects the expected
action) at M-CP2 -- only agreed cases count as the answer key.

run_eval() asks Qwen each case through the engine's own brief + validator and
reports per type: validity rate, agreement with the rule (expected action),
latency. user_agreement() reads the shadow decisions the owner judged in the
Review Queue. go_live_ok(type): user agreement >= 85% over the last 14 days
(and at least `min_judged` judged decisions) -- required to move a type above L1.
"""
import copy
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from marketing import config as mcfg, engine, rules, schema


def _c(t, action, ev, **kw):
    expected = kw.pop("expected", action)
    return {**rules.cand(t, kw.pop("key", f"eval:{t}:{action}:{len(ev)}"), action, bu=kw.pop("bu", "SFW"),
                         platform=kw.pop("platform", "google"), evidence=ev, **kw), "expected": expected}


CASES: List[Dict[str, Any]] = [
    # D1 budget allocation
    _c("D1", "shift_budget", {"from_cost_per_rfq_inr": 64000, "to_cost_per_rfq_inr": 18000, "from_spend_inr_30d": 96000, "conversions": 30,
                              "realloc_pct_this_week": 0, "month_spend_inr": 120000}, params={"from": "a", "to": "b", "shift_pct": 10, "net_change_inr": 0}),
    _c("D1", "shift_budget", {"from_cost_per_rfq_inr": 42000, "to_cost_per_rfq_inr": 25000, "from_spend_inr_30d": 50000, "conversions": 18,
                              "realloc_pct_this_week": 10, "month_spend_inr": 80000}, params={"from": "a", "to": "b", "shift_pct": 5, "net_change_inr": 0}),
    _c("D1", "flag_cross_platform", {"google_cost_per_rfq_inr": 20000, "linkedin_cost_per_rfq_inr": 90000, "conversions": 25}, platform="all"),
    # D2 pause / resume
    _c("D2", "pause", {"spend_inr_30d": 42000, "leads_30d": 3, "rfqs_30d": 0, "cpl_inr": 14000, "target_cpl_inr": 1500, "conversions": 12,
                       "spend_inr": 42000, "clicks": 900}),
    _c("D2", "pause", {"spend_inr_30d": 18000, "leads_30d": 0, "rfqs_30d": 0, "conversions": 6, "spend_inr": 18000, "clicks": 400}),
    _c("D2", "flag", {"spend_inr_30d": 16000, "leads_30d": 1, "rfqs_30d": 0, "conversions": 2, "spend_inr": 4000, "clicks": 120,
                      "learning_phase": True}, expected="flag"),
    # D3 bids
    _c("D3", "adjust_target", {"cpa_inr": 2100, "target_cpa_inr": 1500, "conversions": 40}, params={"change_pct": -10}),
    _c("D3", "adjust_target", {"cpa_inr": 1900, "target_cpa_inr": 1500, "conversions": 22}, params={"change_pct": -10}),
    _c("D3", "no_change", {"cpa_inr": 1550, "target_cpa_inr": 1500, "conversions": 16}, expected="no_change"),
    # D4 negatives
    _c("D4", "add_negatives", {"terms": 3, "wasted_spend_inr_30d": 6200, "clicks": 48, "top": {"free survey jobs": 3100, "survey for money": 2200}},
       params={"terms": ["free survey jobs", "survey for money"], "match_type": "phrase"}),
    _c("D4", "add_negatives", {"terms": 1, "wasted_spend_inr_30d": 1800, "clicks": 14, "top": {"bim course online": 1800}},
       params={"terms": ["bim course online"], "match_type": "phrase"}, bu="BIM"),
    _c("D4", "add_negatives", {"terms": 2, "wasted_spend_inr_30d": 2600, "clicks": 20, "top": {"market research jobs": 1600}},
       params={"terms": ["market research jobs", "research internship"], "match_type": "phrase"}, bu="COGENTIX"),
    # D5 creative
    _c("D5", "promote_winner", {"winner_ctr": 0.031, "loser_ctr": 0.012, "p_value": 0.001, "clicks": 430}, params={"winner": "B", "loser": "A"}),
    _c("D5", "request_variants", {"frequency": 6.2, "clicks": 90}),
    _c("D5", "no_change", {"winner_ctr": 0.021, "loser_ctr": 0.019, "p_value": 0.62, "clicks": 300}, expected="no_change"),
    # D6 audience
    _c("D6", "exclude_audience", {"audience_cpl_inr": 9200, "platform_avg_cpl_inr": 2800, "spend_inr": 23000, "leads": 2}, platform="linkedin"),
    _c("D6", "exclude_audience", {"audience_cpl_inr": None, "platform_avg_cpl_inr": 3100, "spend_inr": 6000, "leads": 0}, platform="meta"),
    _c("D6", "expand_lookalike", {"audience_cpl_inr": 900, "platform_avg_cpl_inr": 2600, "spend_inr": 12000, "leads": 13}, platform="meta"),
    # D7 SEO
    _c("D7", "rank_fixes", {"opportunity_pages": 6, "impressions_28d": 4800, "clicks_28d": 61, "open_issues": 22, "high_issues": 2,
                            "medium_issues": 20, "clicks": 61}, platform="site", bu="COGENTIX"),
    _c("D7", "rank_fixes", {"opportunity_pages": 0, "impressions_28d": 0, "clicks_28d": 0, "open_issues": 23, "high_issues": 0,
                            "medium_issues": 23, "clicks": 0}, platform="site", bu="BIM"),
    _c("D7", "generate_fix_package", {"opportunity_pages": 2, "impressions_28d": 900, "clicks_28d": 8, "open_issues": 41, "high_issues": 3,
                                      "medium_issues": 20, "clicks": 8}, platform="site"),
    # D8 content plan
    _c("D8", "plan_topics", {"open_gaps": 6, "clicks": 0}, platform="content", params={"topics": ["CATI fieldwork India", "panel quality"]}),
    _c("D8", "plan_topics", {"open_gaps": 3, "clicks": 0}, platform="content", bu="BIM", params={"topics": ["scan to BIM cost"]}),
    _c("D8", "plan_topics", {"open_gaps": 4, "clicks": 0}, platform="content", bu="COGENTIX", params={"topics": ["ESG consumer research"]}),
    # D9 schedule
    _c("D9", "set_schedule", {"posts_90d": 24, "best_slot_engagement": 0.061, "avg_engagement": 0.028, "clicks": 140}, platform="linkedin",
       params={"slots": ["Tue 10:00", "Thu 10:00"], "per_week": 2}),
    _c("D9", "set_schedule", {"posts_90d": 40, "best_slot_engagement": 0.044, "avg_engagement": 0.031, "clicks": 210}, platform="linkedin",
       params={"slots": ["Wed 09:00"], "per_week": 3}),
    _c("D9", "no_change", {"posts_90d": 9, "best_slot_engagement": 0.03, "avg_engagement": 0.029, "clicks": 20}, platform="instagram",
       expected="no_change"),
    # D10 lead routing
    _c("D10", "route_sales_call", {"score": 80, "signals": ["form", "replied", "high-intent page"], "touches_14d": 5, "whatsapp_optin": False,
                                   "clicks": 50}, platform="crm", params={"grade": "A", "score": 80}),
    _c("D10", "route_sequence", {"score": 40, "signals": ["form"], "touches_14d": 1, "whatsapp_optin": False, "clicks": 10}, platform="crm",
       params={"grade": "C", "score": 40}),
    _c("D10", "route_whatsapp", {"score": 65, "signals": ["replied", "2 visits"], "touches_14d": 4, "whatsapp_optin": True, "clicks": 40},
       platform="crm", params={"grade": "B", "score": 65}),
    # D11 next best action
    _c("D11", "next_touch", {"days_since_last_touch": 9, "grade": "A", "score": 75, "clicks": 30}, platform="crm",
       params={"channel": "email", "message_type": "follow_up", "when": "next_working_morning"}),
    _c("D11", "next_touch", {"days_since_last_touch": 12, "grade": "B", "score": 62, "clicks": 20}, platform="crm",
       params={"channel": "whatsapp", "message_type": "follow_up", "when": "next_working_morning"}),
    _c("D11", "no_change", {"days_since_last_touch": 2, "grade": "B", "score": 60, "clicks": 20}, platform="crm", expected="no_change"),
    # D12 experiments
    _c("D12", "declare_winner", {"a_rate": 0.02, "b_rate": 0.045, "p_value": 0.002, "a_n": 1000, "b_n": 1000, "days_running": 12, "clicks": 2000},
       params={"winner": "B"}),
    _c("D12", "stop_test", {"a_rate": 0.02, "b_rate": 0.04, "p_value": 0.4, "a_n": 50, "b_n": 50, "days_running": 50, "clicks": 100}),
    _c("D12", "no_change", {"a_rate": 0.021, "b_rate": 0.024, "p_value": 0.3, "a_n": 600, "b_n": 600, "days_running": 9, "clicks": 1200},
       expected="no_change"),
    # D13 anomalies
    _c("D13", "pause_spend_spike", {"spend_yesterday_inr": 9800, "avg_daily_7d_inr": 2100, "conversions": 0, "spend_inr": 9800, "clicks": 300}),
    _c("D13", "alert", {"ctr_yesterday": 0.004, "ctr_7d": 0.019, "clicks": 40}),
    _c("D13", "open_incident", {"hours_silent": 31, "clicks": 0}, platform="site"),
    # D14 weekly
    _c("D14", "weekly_actions", {"candidates": 12, "top5_impact_inr": 61000, "clicks": 0}, platform="all",
       params={"actions": [{"type": "D2", "entity": "SFW Search India", "action": "pause", "impact_inr": 42000}]}),
    _c("D14", "weekly_actions", {"candidates": 4, "top5_impact_inr": 9000, "clicks": 0}, platform="all",
       params={"actions": [{"type": "D7", "entity": "cogentixresearch.com", "action": "rank_fixes", "impact_inr": 1000}]}),
    _c("D14", "weekly_actions", {"candidates": 1, "top5_impact_inr": 0, "clicks": 0}, platform="all",
       params={"actions": [{"type": "D4", "entity": "BIM campaign", "action": "add_negatives", "impact_inr": 1800}]}),
]


def seed(gd: Optional[Callable] = None, now: Optional[datetime] = None) -> int:
    """Write the synthetic cases as 'proposed' (owner agrees or corrects each at M-CP2). Idempotent."""
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    col = gd(schema.DB)["marketing_eval_cases"]
    n = 0
    for i, c in enumerate(CASES):
        key = f"synthetic:{i:02d}:{c['decision_type']}"
        if col.find_one({"key": key}):
            continue
        col.insert_one(schema.stamp({"key": key, "decision_type": c["decision_type"], "candidate": {k: v for k, v in c.items() if k != "expected"},
                                     "expected_action": c["expected"], "status": "proposed"},
                                    bu=c["bu"] if c.get("bu") in schema.BUS else None, source="synthetic_eval", now=now))
        n += 1
    return n


def run_eval(gd: Optional[Callable] = None, *, qwen: Optional[Callable] = None, types: Optional[List[str]] = None,
             only_agreed: bool = False, cfg: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    cfg = copy.deepcopy(cfg or engine._cfg())
    # measure the model, not the missing owner config: placeholder caps so D1 cases are not all "no cap set"
    caps = cfg["budget"].setdefault("monthly_cap_inr", {})
    for bu in schema.BUS:
        for plat in ("google", "linkedin", "meta", "quora", "all"):
            caps.setdefault(bu, {}).setdefault(plat, 10 ** 7)
    qwen = qwen or engine._qwen_call
    col = gd(schema.DB)["marketing_eval_cases"]
    q: Dict[str, Any] = {"status": "agreed"} if only_agreed else {"status": {"$in": ["proposed", "agreed"]}}
    rows = [r for r in col.find(q) if not types or r["decision_type"] in types]
    per: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        t, c = r["decision_type"], dict(r["candidate"], created_at=now)
        p = per.setdefault(t, {"cases": 0, "valid": 0, "agree_rule": 0, "latency_s": [], "deferred": 0, "errors": []})
        p["cases"] += 1
        br = engine.brief(c, cfg, [])
        t0 = time.time()
        try:
            res = qwen(t, br, lambda data, _clean: engine.validate(data, c, br, cfg, []))
        except Exception as e:
            p["errors"].append(str(e)[:120])
            continue
        p["latency_s"].append(round(time.time() - t0, 2))
        if res.get("status") == "deferred":
            p["deferred"] += 1
            continue
        out = res.get("data")
        probs = engine.validate(out, c, br, cfg, []) if isinstance(out, dict) else ["no JSON object"]
        if not probs:
            p["valid"] += 1
            if out.get("action") == r["expected_action"]:
                p["agree_rule"] += 1
    rep = {"at": now, "cases": len(rows), "only_agreed": only_agreed, "types": {}}
    for t, p in sorted(per.items()):
        answered = p["cases"] - p["deferred"] - len(p["errors"])
        lat = sorted(p["latency_s"])
        rep["types"][t] = {"cases": p["cases"], "answered": answered,
                           "validity": round(p["valid"] / answered, 3) if answered else None,
                           "agreement_with_rules": round(p["agree_rule"] / answered, 3) if answered else None,
                           "median_latency_s": lat[len(lat) // 2] if lat else None,
                           "deferred": p["deferred"], "errors": p["errors"][:3]}
    gd(schema.DB)["marketing_eval_runs"].insert_one(schema.stamp({**rep}, bu=None, source="eval", now=now))
    return rep


def user_agreement(gd: Optional[Callable] = None, *, days: int = 14, now: Optional[datetime] = None) -> Dict[str, Dict[str, Any]]:
    """Per type: share of the owner's Review Queue verdicts (last `days`) that approved the engine's proposal unchanged."""
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    out: Dict[str, Dict[str, Any]] = {}
    for d in gd(schema.DB)["decisions"].find({"human": {"$in": ["approved", "rejected"]},
                                               "created_at": {"$gte": now - timedelta(days=days)}}):
        o = out.setdefault(d["decision_type"], {"judged": 0, "agreed": 0})
        o["judged"] += 1
        o["agreed"] += 1 if d["human"] == "approved" and not d.get("human_corrected") else 0
    for o in out.values():
        o["agreement"] = round(o["agreed"] / o["judged"], 3) if o["judged"] else None
    return out


def go_live_ok(decision_type: str, gd: Optional[Callable] = None, *, min_judged: int = 10,
               cfg: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    cfg = cfg or engine._cfg()
    ua = user_agreement(gd, now=now).get(decision_type, {"judged": 0, "agreed": 0, "agreement": None})
    need = float(cfg.get("go_live_min_agreement", 0.85))
    ok = ua["judged"] >= min_judged and (ua["agreement"] or 0) >= need
    return {**ua, "required": need, "min_judged": min_judged, "ok": ok,
            "why": "" if ok else (f"only {ua['judged']} judged decisions in 14 days (need {min_judged})" if ua["judged"] < min_judged
                                  else f"agreement {ua['agreement']} < {need}")}
