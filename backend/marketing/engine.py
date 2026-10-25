"""Qwen Decision Engine core (MARKETING_PLAN Section 4). Code computes, Qwen judges and
explains, guardrails decide whether anything may act.

    candidate (rule layer) -> decide() -> decision log (email_automation.decisions)

decide():
  1. kill switch (global / BU), autonomy L0 -> skipped
  2. conflict / cooldown on the same entity -> blocked
  3. decision brief (compact JSON, capped) -> Qwen via platform_core.qwen_gateway
     (Qwen down, deferred, invalid twice -> the rule candidate goes on alone)
  4. validator (code): schema, action allowed for the type, parameters inside the
     guardrails, every number Qwen cites exists in the brief
  5. confidence (code, never Qwen's): data volume, rule/Qwen agreement, the type's
     acceptance rate, its predicted-vs-actual accuracy
  6. autonomy: L1 -> Review Queue; L2/L3 -> execute when confidence clears the bar
     (L3 never for budget, bids or client-facing: marketing.config.NO_L3)
  7. executor: shadow logs "would execute" + the undo payload; live needs the
     action type switched to live by the owner AND a registered platform executor
Outcome tracker measures each executed decision after its window; stop-loss drops
a type to L1 when its last N executed outcomes are worse than baseline.
"""
import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from marketing import config as mcfg, schema

DECISION_SCHEMA = {"type": "object", "required": ["decision_type", "action", "parameters", "reasoning", "expected_impact",
                                                  "risks", "alternatives_considered", "needs_human"]}
QWEN_TASK = {"P1": "marketing_decision_p1", "P2": "marketing_decision_p2", "P3": "marketing_decision_p3"}
SYSTEM = ("You review one marketing decision for a B2B research company. You get a JSON brief: the metrics (already "
          "computed), targets, guardrails, recent decisions and their outcomes. Do no arithmetic: use only numbers that "
          "appear in the brief. Choose one action from allowed_actions and parameters inside the guardrails. Reply with "
          "JSON only: {\"decision_type\", \"action\", \"parameters\", \"reasoning\" (2-4 plain sentences), "
          "\"expected_impact\": {\"metric\", \"direction\": \"up|down\", \"size\": \"small|medium|large\"}, \"risks\", "
          "\"alternatives_considered\": [..], \"needs_human\": true|false}.")

# allowed actions per decision type (the validator refuses anything else)
ACTIONS: Dict[str, List[str]] = {
    "D1": ["shift_budget", "flag_cross_platform", "no_change"], "D2": ["pause", "resume", "flag", "no_change"],
    "D3": ["adjust_target", "adjust_bid", "no_change"], "D4": ["add_negatives", "no_change"],
    "D5": ["promote_winner", "retire_loser", "request_variants", "no_change"],
    "D6": ["add_audience", "exclude_audience", "expand_lookalike", "no_change"],
    "D7": ["rank_fixes", "generate_fix_package", "no_change"], "D8": ["plan_topics", "no_change"],
    "D9": ["set_schedule", "no_change"], "D10": ["route_sequence", "route_sales_call", "route_whatsapp", "route_nurture", "no_change"],
    "D11": ["next_touch", "no_change"], "D12": ["start_test", "stop_test", "declare_winner", "no_change"],
    "D13": ["alert", "pause_spend_spike", "open_incident"], "D14": ["weekly_actions"],
}
CONFLICTS = {("pause", "resume"), ("resume", "pause"), ("promote_winner", "retire_loser"), ("retire_loser", "promote_winner")}
CONFIDENCE_TO_ACT = 0.7
_EXECUTORS: Dict[Tuple[str, str], Dict[str, Callable]] = {}   # (platform, action) -> {"do": fn, "undo": fn}


def register_executor(platform: str, action: str, do: Callable[[Dict[str, Any]], Dict[str, Any]],
                      undo: Callable[[Dict[str, Any]], Any]) -> None:
    """A platform integration (M3) registers its write call. do(params) returns the undo payload."""
    _EXECUTORS[(platform, action)] = {"do": do, "undo": undo}


def _cfg():
    try:
        from platform_core import config_store
        return config_store.get("marketing")
    except Exception:
        return mcfg.DEFAULTS


# ------------------------------------------------------------------ guardrails (4.3), pure
def guardrail_problems(c: Dict[str, Any], params: Dict[str, Any], cfg: Dict[str, Any],
                       history: List[Dict[str, Any]], action: Optional[str] = None) -> List[str]:
    t, ev, out = c["decision_type"], c.get("evidence") or {}, []
    action = action or c.get("action")
    b, bids, pause = cfg["budget"], cfg["bids"], cfg["pause"]
    if t == "D1" and params.get("shift_pct") is not None:
        pct = abs(float(params["shift_pct"]))
        if pct > b["max_daily_change_pct"]:
            out.append(f"budget change {pct}% > max daily {b['max_daily_change_pct']}%")
        used = float(ev.get("realloc_pct_this_week") or 0)
        if used + pct > b["max_weekly_realloc_pct"]:
            out.append(f"weekly reallocation would reach {used + pct}% > {b['max_weekly_realloc_pct']}%")
        if float(params.get("net_change_inr") or 0) > 0 and not b["allow_total_increase"]:
            out.append("raises total spend (never automatic)")
        cap = ((b.get("monthly_cap_inr") or {}).get(c.get("bu")) or {}).get(c.get("platform"))
        if cap is None:
            out.append("no monthly cap set for this BU and platform")
        elif float(ev.get("month_spend_inr") or 0) + float(params.get("net_change_inr") or 0) > cap:
            out.append("monthly cap would be exceeded")
    if t == "D3":
        pct = abs(float(params.get("change_pct") or 0))
        if pct > bids["max_change_pct"]:
            out.append(f"bid/target change {pct}% > {bids['max_change_pct']}%")
        last = max((h["created_at"] for h in history if h.get("status") in ("executed", "shadow_executed")), default=None)
        if last and (c["created_at"] - last).days < bids["min_days_between"]:
            out.append(f"last adjustment {(c['created_at'] - last).days} days ago < {bids['min_days_between']}")
    if t == "D2" and action == "pause":
        if pause.get("skip_learning_phase") and ev.get("learning_phase"):
            out.append("campaign is in its learning phase")
        if float(ev.get("conversions") or 0) < pause["min_conversions"] and float(ev.get("spend_inr") or 0) < pause["min_spend_inr"]:
            out.append(f"too little data to pause (< {pause['min_conversions']} conversions and < ₹{pause['min_spend_inr']})")
    return out


def _numbers(obj) -> set:
    # ensure_ascii=False: "₹42,000" must not become "₹42,000" (-> 942000); 1,500 / 1,50,000 grouping removed
    s = re.sub(r"(?<=\d),(?=\d{2,3}\b)", "", json.dumps(obj, default=str, ensure_ascii=False))
    return {_n(x) for x in re.findall(r"-?\d+(?:\.\d+)?", s)}


def _n(x: str) -> str:
    try:
        v = float(x)
    except ValueError:
        return x
    return str(int(v)) if v == int(v) else f"{v:.2f}".rstrip("0").rstrip(".")


def validate(out: Any, c: Dict[str, Any], brief: Dict[str, Any], cfg: Dict[str, Any],
             history: List[Dict[str, Any]]) -> List[str]:
    """4.1.4. Returns problems; empty = valid."""
    if not isinstance(out, dict):
        return ["output is not a JSON object"]
    probs = [f"missing {k}" for k in DECISION_SCHEMA["required"] if k not in out]
    if probs:
        return probs
    t = c["decision_type"]
    if out.get("decision_type") != t:
        probs.append(f"decision_type {out.get('decision_type')!r} != {t}")
    if out.get("action") not in ACTIONS[t]:
        probs.append(f"action {out.get('action')!r} not allowed for {t}")
    if not isinstance(out.get("parameters"), dict):
        probs.append("parameters must be an object")
    else:
        probs += guardrail_problems(c, out["parameters"], cfg, history, action=out.get("action"))
    ei = out.get("expected_impact") or {}
    if ei.get("direction") not in ("up", "down") or ei.get("size") not in ("small", "medium", "large"):
        probs.append("expected_impact needs direction up|down and size small|medium|large")
    known = _numbers(brief)
    cited = _numbers({"r": out.get("reasoning"), "k": out.get("risks")}) - {"0", "1", "2", "3", "4", "5", "7", "14", "28", "30", "100"}
    invented = sorted(x for x in cited if x not in known)
    if invented:
        probs.append(f"numbers not in the brief: {', '.join(invented[:5])}")
    return probs


# ------------------------------------------------------------------ confidence (4.1.5), code only
def confidence(c: Dict[str, Any], qwen_action: Optional[str], stats: Dict[str, Any]) -> Dict[str, float]:
    ev = c.get("evidence") or {}
    vol = float(ev.get("conversions") or 0) + float(ev.get("clicks") or 0) / 50
    need = float(c.get("min_volume") or 20)
    parts = {
        "volume": min(1.0, vol / need) if need else 1.0,
        "agreement": 1.0 if qwen_action is None or qwen_action == c["action"] else 0.0 if qwen_action != "no_change" else 0.5,
        "acceptance": stats.get("acceptance", 0.5),
        "accuracy": stats.get("accuracy", 0.5),
    }
    w = {"volume": 0.3, "agreement": 0.3, "acceptance": 0.2, "accuracy": 0.2}
    parts["score"] = round(sum(parts[k] * w[k] for k in w), 3)
    if qwen_action is None:                    # rule only (Qwen down / invalid): never above the act bar
        parts["score"] = min(parts["score"], CONFIDENCE_TO_ACT - 0.01)
    return parts


def type_stats(col, decision_type: str, n: int = 50) -> Dict[str, Any]:
    rows = list(col.find({"decision_type": decision_type, "status": {"$in": ["approved", "rejected", "executed",
                                                                            "shadow_executed", "undone"]}})
                .sort("created_at", -1).limit(n))
    judged = [r for r in rows if r.get("human") in ("approved", "rejected")]
    measured = [r for r in rows if r.get("outcome", {}).get("direction_correct") is not None]
    return {"acceptance": (sum(r["human"] == "approved" for r in judged) / len(judged)) if judged else 0.5,
            "accuracy": (sum(bool(r["outcome"]["direction_correct"]) for r in measured) / len(measured)) if measured else 0.5,
            "judged": len(judged), "measured": len(measured)}


# ------------------------------------------------------------------ brief (4.1.3)
def brief(c: Dict[str, Any], cfg: Dict[str, Any], recent: List[Dict[str, Any]]) -> Dict[str, Any]:
    cap_chars = 4 * int((cfg["qwen"]["max_input_tokens"].get(c["decision_type"]) or cfg["qwen"]["max_input_tokens"]["default"]))
    b = {"decision_type": c["decision_type"], "name": mcfg.DECISION_TYPES[c["decision_type"]], "bu": c.get("bu"),
         "entity": c.get("entity_label") or c.get("entity_key"), "rule_suggests": {"action": c["action"], "parameters": c.get("parameters")},
         "allowed_actions": ACTIONS[c["decision_type"]], "metrics": c.get("evidence") or {}, "targets": c.get("targets") or {},
         "guardrails": {"max_daily_budget_change_pct": cfg["budget"]["max_daily_change_pct"],
                        "max_weekly_realloc_pct": cfg["budget"]["max_weekly_realloc_pct"],
                        "max_bid_change_pct": cfg["bids"]["max_change_pct"], "never_raise_total_spend": True},
         "recent": [{"action": r.get("action"), "status": r.get("status"),
                     "outcome": (r.get("outcome") or {}).get("summary")} for r in recent[:3]]}
    while len(json.dumps(b, default=str)) > cap_chars and b["recent"]:
        b["recent"].pop()
    if len(json.dumps(b, default=str)) > cap_chars:          # metrics trimmed last: top-N already chosen by the rule
        keep = dict(list(b["metrics"].items())[:12])
        b["metrics"] = keep
    return b


def _hash(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


# ------------------------------------------------------------------ decide
def decide(c: Dict[str, Any], *, gd: Optional[Callable] = None, qwen: Optional[Callable] = None,
           cfg: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """c: {decision_type, entity_key, bu, platform, action, parameters, evidence, targets, rule_id}."""
    if gd is None:
        from database import get_database as gd
    cfg = cfg or _cfg()
    now = now or datetime.utcnow()
    c = dict(c, created_at=now)
    t = c["decision_type"]
    col = gd(schema.DB)["decisions"]
    level = mcfg.autonomy(cfg, t)
    doc: Dict[str, Any] = {**{k: c.get(k) for k in ("decision_type", "entity_key", "entity_label", "bu", "platform",
                                                    "action", "parameters", "evidence", "targets", "rule_id")},
                           "autonomy": level, "lane": mcfg.LANES.get(t, "P3"), "mode": cfg.get("mode", "shadow")}

    def save(status, **kw):
        d = schema.stamp({**doc, **kw, "status": status}, bu=c.get("bu") if c.get("bu") in schema.BUS else None,
                         source="decision_engine", now=now)
        d["_id"] = col.insert_one(d).inserted_id
        return d

    if mcfg.killed(cfg, c.get("bu")):
        return save("skipped", reason="kill switch on")
    if level == "L0":
        return save("skipped", reason=f"{t} is off (L0)")
    cool = int((cfg.get("cooldown_days") or {}).get(t) or cfg["cooldown_days"]["default"])
    history = list(col.find({"entity_key": c["entity_key"], "created_at": {"$gte": now - timedelta(days=max(cool, 30))}}))
    clash = [h for h in history if h.get("status") in ("in_review", "executed", "shadow_executed")
             and (h["created_at"] >= now - timedelta(days=cool)) and (h.get("action"), c["action"]) in CONFLICTS]
    if clash:
        return save("blocked", reason=f"conflicts with decision {clash[0]['_id']} ({clash[0]['action']}) inside the {cool}-day cooldown")
    same = [h for h in history if h.get("action") == c["action"] and h.get("status") in ("in_review", "executed", "shadow_executed")
            and h["created_at"] >= now - timedelta(days=cool)]
    if same:
        return save("skipped", reason=f"same action already {same[0]['status']} for this entity")

    recent = list(col.find({"decision_type": t, "outcome": {"$exists": True}}).sort("created_at", -1).limit(3))
    br = brief(c, cfg, recent)
    doc["brief_hash"] = _hash(br)
    out, qstatus, problems = None, None, []
    qwen = qwen or _qwen_call
    try:
        res = qwen(t, br, lambda data, _clean: validate(data, c, br, cfg, history))
        qstatus = res.get("status")
        if qstatus in ("ok", "review") and isinstance(res.get("data"), dict):
            out = res["data"]
            problems = res.get("problems") or validate(out, c, br, cfg, history)
    except Exception as e:                       # Qwen unavailable: marketing never stops (4.4)
        qstatus, problems = "unavailable", [f"qwen: {str(e)[:150]}"]
    valid_qwen = out is not None and not problems
    action = out["action"] if valid_qwen else c["action"]
    params = out["parameters"] if valid_qwen else (c.get("parameters") or {})
    rule_probs = guardrail_problems(c, params, cfg, history, action=action) if not valid_qwen else []
    conf = confidence(c, out["action"] if valid_qwen else None, type_stats(col, t))
    doc.update(qwen_status=qstatus, qwen_output=out, validation_problems=problems + rule_probs, confidence=conf,
               final_action=action, final_parameters=params,
               expected_impact=(out or {}).get("expected_impact"), reasoning=(out or {}).get("reasoning"),
               risks=(out or {}).get("risks"), alternatives=(out or {}).get("alternatives_considered"))
    if action == "no_change":
        return save("no_change")
    can_act = (level in ("L2", "L3") and valid_qwen and not rule_probs and conf["score"] >= CONFIDENCE_TO_ACT
               and not (out or {}).get("needs_human"))
    if not can_act:
        d = save("in_review")
        _to_review(d, gd)
        return d
    return _execute(save("approved", human=None, approved_by="engine"), gd, cfg, notify=level == "L2")


def _qwen_call(t: str, br: Dict[str, Any], code_check: Callable) -> Dict[str, Any]:
    from platform_core import qwen_gateway
    mcfg.register_qwen_tasks()
    lane = mcfg.LANES.get(t, "P3")
    return qwen_gateway.run(task=QWEN_TASK[lane], system=SYSTEM, body=json.dumps(br, default=str), schema=DECISION_SCHEMA,
                            code_check=code_check, ref={"collection": "email_automation.decisions", "id": _hash(br)},
                            bu=br.get("bu"))


def _to_review(d: Dict[str, Any], gd) -> None:
    from platform_core import review_queue
    item = review_queue.enqueue(
        type="marketing_decision", module="marketing", bu=d.get("bu"),
        ref={"collection": "email_automation.decisions", "id": str(d["_id"])},
        reason=f"{d['decision_type']} {mcfg.DECISION_TYPES[d['decision_type']]}: {d['final_action']} — "
               f"{d.get('entity_label') or d.get('entity_key')}" + (f" [{'; '.join(d['validation_problems'][:2])}]"
                                                                   if d.get("validation_problems") else ""),
        payload={k: d.get(k) for k in ("decision_type", "entity_key", "evidence", "reasoning", "risks", "confidence",
                                       "expected_impact", "validation_problems", "autonomy", "mode")},
        suggested={"action": d["final_action"], "parameters": d["final_parameters"]},
        resume={"handler": "marketing_decision", "ref": {"decision_id": str(d["_id"])}})
    gd(schema.DB)["decisions"].update_one({"_id": d["_id"]}, {"$set": {"review_item": item}})


def resume_from_review(item: Dict[str, Any], decision: Dict[str, Any], gd: Optional[Callable] = None) -> Dict[str, Any]:
    """Review Queue approve / correct -> execute (shadow unless live)."""
    if gd is None:
        from database import get_database as gd
    from bson import ObjectId
    col = gd(schema.DB)["decisions"]
    did = (item.get("resume") or {}).get("ref", {}).get("decision_id")
    d = col.find_one({"_id": ObjectId(did)}) if did and ObjectId.is_valid(did) else None
    if not d or d.get("status") != "in_review":
        return {"ok": False, "error": "decision not in review"}
    val = decision.get("value") or {}
    upd = {"status": "approved", "human": "approved", "approved_by": decision.get("by"), "approved_at": decision.get("at"),
           "final_action": val.get("action", d["final_action"]), "final_parameters": val.get("parameters", d["final_parameters"])}
    if decision.get("action") == "correct":
        upd["human_corrected"] = True
    col.update_one({"_id": d["_id"]}, {"$set": upd})
    d.update(upd)
    return _execute(d, gd, _cfg(), notify=False)


def sync_rejections(gd: Optional[Callable] = None) -> int:
    """Rejected review items do not call a resume handler: copy the verdict into the log (acceptance rate)."""
    if gd is None:
        from database import get_database as gd
    from bson import ObjectId
    ea = gd(schema.DB)
    n = 0
    for it in ea["review_queue_items"].find({"type": "marketing_decision", "status": "rejected", "synced": {"$ne": True}}):
        did = (it.get("ref") or {}).get("id")
        if did and ObjectId.is_valid(did):
            ea["decisions"].update_one({"_id": ObjectId(did), "status": "in_review"},
                                       {"$set": {"status": "rejected", "human": "rejected",
                                                 "rejected_by": it.get("resolved_by"), "updated_at": datetime.utcnow()}})
            n += 1
        ea["review_queue_items"].update_one({"_id": it["_id"]}, {"$set": {"synced": True}})
    return n


def _execute(d: Dict[str, Any], gd, cfg: Dict[str, Any], notify: bool) -> Dict[str, Any]:
    col = gd(schema.DB)["decisions"]
    now = datetime.utcnow()
    act = d["final_action"]
    live = cfg.get("mode") == "live" and (cfg.get("action_modes") or {}).get(f"{d['decision_type']}:{act}") == "live"
    ex = _EXECUTORS.get((d.get("platform") or "", act))
    win = int(cfg["outcome_window_days"].get(d["decision_type"], 14))
    base = {"executed_at": now, "outcome_due_at": now + timedelta(days=win), "undo_until": now + timedelta(days=cfg["undo_days"])}
    if mcfg.killed(cfg, d.get("bu")):
        col.update_one({"_id": d["_id"]}, {"$set": {"status": "skipped", "reason": "kill switch on at execution"}})
        return {**d, "status": "skipped"}
    if not live or not ex:
        upd = {**base, "status": "shadow_executed", "would_execute": {"platform": d.get("platform"), "action": act,
                                                                      "parameters": d["final_parameters"]},
               "shadow_reason": "shadow mode" if not live else f"no executor registered for {d.get('platform')}:{act}"}
    else:
        try:
            undo = ex["do"](d["final_parameters"])
            upd = {**base, "status": "executed", "undo_payload": undo}
        except Exception as e:
            upd = {"status": "failed", "error": str(e)[:300]}
    col.update_one({"_id": d["_id"]}, {"$set": upd})
    try:
        from platform_core.audit import log_action
        log_action(actor=d.get("approved_by") or "engine", action="update", entity_type="marketing_decision",
                   entity_id=str(d["_id"]), reason=f"{upd['status']}: {d['decision_type']} {act}", source="decision_engine")
    except Exception:
        pass
    return {**d, **upd, "notify": notify}


def undo(decision_id: str, actor: str, gd: Optional[Callable] = None) -> Dict[str, Any]:
    if gd is None:
        from database import get_database as gd
    from bson import ObjectId
    col = gd(schema.DB)["decisions"]
    d = col.find_one({"_id": ObjectId(decision_id)})
    if not d or d.get("status") not in ("executed", "shadow_executed"):
        return {"ok": False, "error": "nothing to undo"}
    if d.get("undo_until") and datetime.utcnow() > d["undo_until"]:
        return {"ok": False, "error": "undo window (30 days) has passed"}
    if d["status"] == "executed":
        ex = _EXECUTORS.get((d.get("platform") or "", d["final_action"]))
        if not ex:
            return {"ok": False, "error": "executor no longer registered"}
        ex["undo"](d.get("undo_payload") or {})
    col.update_one({"_id": d["_id"]}, {"$set": {"status": "undone", "undone_by": actor, "undone_at": datetime.utcnow()}})
    return {"ok": True}


# ------------------------------------------------------------------ outcomes + stop-loss (4.1.7, 4.3)
def measure_due(gd: Optional[Callable] = None, metric: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, float]]]] = None,
                now: Optional[datetime] = None, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """metric(decision) -> {"baseline": x, "actual": y, "higher_is_better": bool} or None (not measurable yet)."""
    if gd is None:
        from database import get_database as gd
    now, cfg = now or datetime.utcnow(), cfg or _cfg()
    ea = gd(schema.DB)
    col = ea["decisions"]
    rep = {"measured": 0, "downgraded": []}
    for d in col.find({"status": {"$in": ["executed", "shadow_executed"]}, "outcome": {"$exists": False},
                       "outcome_due_at": {"$lte": now}}):
        m = metric(d) if metric else None
        if not m:
            continue
        hib = m.get("higher_is_better", True)
        delta = m["actual"] - m["baseline"]
        better = delta > 0 if hib else delta < 0
        predicted = (d.get("expected_impact") or {}).get("direction")
        moved = "up" if delta > 0 else "down" if delta < 0 else None
        oc = {"baseline": m["baseline"], "actual": m["actual"], "delta": round(delta, 4), "better_than_baseline": better,
              "direction_correct": (predicted == moved) if predicted and moved else None, "measured_at": now,
              "shadow": d["status"] == "shadow_executed",
              "summary": f"{m.get('name', 'metric')} {m['baseline']} -> {m['actual']}"}
        col.update_one({"_id": d["_id"]}, {"$set": {"outcome": oc}})
        ea["decision_outcomes"].update_one({"decision_id": str(d["_id"])}, {"$set": schema.stamp(
            {"decision_id": str(d["_id"]), "decision_type": d["decision_type"], **oc, "predicted": d.get("expected_impact")},
            bu=d.get("bu") if d.get("bu") in schema.BUS else None, source="outcome_tracker", now=now)}, upsert=True)
        rep["measured"] += 1
    rep["downgraded"] = stop_loss(gd, cfg)
    return rep


def stop_loss(gd, cfg: Dict[str, Any]) -> List[str]:
    """A type whose last N executed (live) outcomes are mostly worse than baseline drops to L1 + alert."""
    n = int(cfg["stop_loss"]["window"])
    col = gd(schema.DB)["decisions"]
    out = []
    for t, lvl in (cfg.get("autonomy") or {}).items():
        if lvl not in ("L2", "L3"):
            continue
        last = list(col.find({"decision_type": t, "status": "executed", "outcome.better_than_baseline": {"$exists": True}})
                    .sort("executed_at", -1).limit(n))
        if len(last) >= n and sum(not r["outcome"]["better_than_baseline"] for r in last) > n / 2:
            try:
                from platform_core import config_store, review_queue
                # set() replaces the stored dict: write the whole map, changing only this type
                levels = dict(config_store.get("marketing").get("autonomy") or {})
                levels[t] = "L1"
                config_store.set("marketing", {"autonomy": levels}, actor="stop_loss")
                review_queue.enqueue(type="marketing_stop_loss", module="marketing",
                                     ref={"collection": "marketing.autonomy", "id": f"{t}:{datetime.utcnow():%Y%m%d}"},
                                     reason=f"{t} {mcfg.DECISION_TYPES[t]} dropped to L1: {sum(not r['outcome']['better_than_baseline'] for r in last)}"
                                            f" of the last {n} executed decisions did worse than baseline")
            except Exception:
                pass
            out.append(t)
    return out


try:      # Review Queue approve -> execute
    from platform_core import review_queue as _rq
    _rq.register_handler("marketing_decision", lambda item, decision: resume_from_review(item, decision))
except Exception:      # pragma: no cover
    pass
