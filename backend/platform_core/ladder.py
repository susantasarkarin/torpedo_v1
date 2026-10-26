"""Escalation ladder for every AI task (owner, 2026-10-25).

    rules (in the caller)  ->  Qwen 1.5B (local)  ->  Claude Haiku  ->  Claude Sonnet  ->  a person

`run()` is a drop-in for qwen_gateway.run (same arguments, same result
shape), so every caller that already tries its rules first and then calls the
model gets the ladder by switching the import. A tier's answer is accepted
only if it is valid against the task's JSON schema AND passes the task's code
checks (numbers found in the mail, countries named, allowed labels...). The
model's own confidence is never trusted. When a tier fails, the next one is
tried; when every tier fails, ONE Review Queue item holds the best attempt.

Cost control (output tokens are the expensive part):
  * the cloud tiers return only the task's schema fields (structured output,
    additionalProperties false), no prose, no reasoning (thinking off, low
    effort), small max_tokens per task
  * the input is the gateway's cleaned text (newest message, no quotes,
    signatures, disclaimers, tracking links), with email addresses and phone
    numbers masked before it leaves the VM
  * a monthly budget (config ladder.monthly_budget_usd); when it is used up,
    or the Anthropic account cannot be used (no credit, bad key), the cloud
    tiers are skipped and the item goes to a person
Every attempt is logged in ai_governance.ladder_jobs (task, tier, tokens,
cost, problems) so accuracy and spend per tier and task are visible.
"""
import copy
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config_store, qwen_gateway, review_queue

logger = logging.getLogger(__name__)

DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "monthly_budget_usd": 10.0,
    "mask_pii": True,
    "models": {
        "haiku": {"model": "claude-haiku-5-5", "usd_in_per_m": 0.10, "usd_out_per_m": 0.50,
                  "thinking": {"type": "disabled"}},
        "sonnet": {"model": "claude-sonnet-5-5", "usd_in_per_m": 2.00, "usd_out_per_m": 10.00,
                   "thinking": {"type": "between_tools"}},
    },
    "default_tiers": ["qwen", "haiku"],
    "task_tiers": {                       # which rungs each task may climb (rules run in the caller first)
        "rfq_extraction": ["qwen", "haiku", "sonnet"],
        "vendor_bid_parse": ["qwen", "haiku", "sonnet"],
        "reply_classification": ["qwen", "haiku", "sonnet"],
        "sender_type": ["qwen", "haiku"],
        "mail_summary": ["qwen", "haiku"],
        "reply_draft": ["haiku", "sonnet"],        # the 1.5B does not write natural prose
        "reengagement_draft": ["qwen", "haiku", "sonnet"],
        "contact_classification": ["qwen", "haiku", "sonnet"],
        "lead_bucketing": ["qwen", "haiku"],
    },
    "cloud_max_tokens": {"default": 400, "rfq_extraction": 3000, "vendor_bid_parse": 800, "reply_draft": 600,
                         "mail_summary": 250},   # a ceiling only: billed on tokens used; multi-country RFQs list a line per market
}

_UNAVAILABLE: Dict[str, float] = {}       # tier -> retry-after epoch (no credit / bad key / outage)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w/])\+\d[\d\s\-()]{7,16}\d|\b\d{3,5}[\s-]\d{3,4}[\s-]\d{3,4}\b")


def cfg() -> Dict[str, Any]:
    try:
        return config_store.get("ladder")
    except Exception:
        return DEFAULTS


# ---------------------------------------------------------------- masking


def mask(text: str) -> Tuple[str, Dict[str, str]]:
    """Email addresses and phone numbers -> <EMAIL_1>, <PHONE_1> before the cloud."""
    mapping: Dict[str, str] = {}

    def sub(kind):
        def f(m):
            val = m.group(0)
            for k, v in mapping.items():
                if v == val:
                    return k
            key = f"<{kind}_{sum(1 for k in mapping if k.startswith('<' + kind)) + 1}>"
            mapping[key] = val
            return key
        return f
    out = _EMAIL.sub(sub("EMAIL"), text or "")
    out = _PHONE.sub(sub("PHONE"), out)
    return out, mapping


def unmask(data: Any, mapping: Dict[str, str]) -> Any:
    if not mapping:
        return data
    if isinstance(data, str):
        for k, v in mapping.items():
            data = data.replace(k, v)
        return data
    if isinstance(data, list):
        return [unmask(x, mapping) for x in data]
    if isinstance(data, dict):
        return {k: unmask(v, mapping) for k, v in data.items()}
    return data


# ---------------------------------------------------------------- schema


def strict_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Structured outputs need every object closed and every property
    required; optional values become nullable ("type": [..., "null"]) so the
    model can still say "not stated"."""
    s = copy.deepcopy(schema or {"type": "object", "properties": {}})

    def walk(node):
        if not isinstance(node, dict):
            return
        t = node.get("type")
        if t == "object" or (isinstance(t, list) and "object" in t) or "properties" in node:
            props = node.setdefault("properties", {})
            req = set(node.get("required") or [])
            for k, v in props.items():
                walk(v)
                if k not in req and isinstance(v, dict):
                    tt = v.get("type")
                    if isinstance(tt, str) and tt != "null":
                        v["type"] = [tt, "null"]
                    elif isinstance(tt, list) and "null" not in tt:
                        v["type"] = tt + ["null"]
            node["required"] = list(props)
            node["additionalProperties"] = False
        if "items" in node:
            walk(node["items"])
        for key in ("minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum", "format", "pattern"):
            node.pop(key, None)            # constraints are enforced by our own validation afterwards
    walk(s)
    return s


# ---------------------------------------------------------------- spend


def _month() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def spent_this_month(db) -> float:
    d = db["ladder_spend"].find_one({"_id": _month()}) or {}
    return float(d.get("usd") or 0)


def _add_spend(db, usd: float, tier: str, task: str) -> None:
    db["ladder_spend"].update_one({"_id": _month()}, {"$inc": {"usd": usd, f"by_tier.{tier}": usd,
                                                               f"by_task.{task}": usd, "calls": 1}}, upsert=True)


# ---------------------------------------------------------------- cloud transport


def anthropic_transport(*, model: str, system: str, user: str, schema: Dict[str, Any], max_tokens: int,
                        thinking: Dict[str, Any]) -> Tuple[str, int, int]:
    """One Messages API call returning only JSON for `schema`. -> (text, input_tokens, output_tokens)."""
    import anthropic
    client = anthropic.Anthropic(max_retries=2, timeout=60.0)
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
        extra_body={"output_config": {"effort": "low", "format": {"type": "json_schema", "schema": schema}},
                    "thinking": thinking})
    if resp.stop_reason == "refusal":
        raise RuntimeError("refusal")
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    return text, int(resp.usage.input_tokens or 0), int(resp.usage.output_tokens or 0)


def _classify_error(e: Exception) -> Optional[float]:
    """Seconds to keep a tier switched off, or None for a one-off failure."""
    msg = str(e).lower()
    name = type(e).__name__
    if "credit balance" in msg or "billing" in msg:
        return 1800
    if name in ("AuthenticationError", "PermissionDeniedError"):
        return 6 * 3600
    if name in ("APIConnectionError", "InternalServerError", "OverloadedError") or "overloaded" in msg:
        return 300
    return None


def _cloud_attempt(tier: str, *, task: str, system: str, clean: str, schema: Optional[Dict[str, Any]],
                   code_check, c: Dict[str, Any], db, transport) -> Dict[str, Any]:
    m = c["models"][tier]
    user, mapping = mask(clean) if c.get("mask_pii", True) else (clean, {})
    st = strict_schema(schema) if schema else {"type": "object", "properties": {}, "required": [],
                                                "additionalProperties": False}
    max_tokens = int((c.get("cloud_max_tokens") or {}).get(task) or (c.get("cloud_max_tokens") or {}).get("default") or 400)
    t0 = time.time()
    try:
        raw, tin, tout = transport(model=m["model"], system=system + "\nReturn only the JSON object. No explanation.",
                                   user=user, schema=st, max_tokens=max_tokens, thinking=m.get("thinking") or {"type": "disabled"})
    except Exception as e:
        off = _classify_error(e)
        if off:
            _UNAVAILABLE[tier] = time.time() + off
        return {"tier": tier, "status": "failed", "error": str(e)[:300], "unavailable_for_s": off}
    usd = tin / 1e6 * float(m["usd_in_per_m"]) + tout / 1e6 * float(m["usd_out_per_m"])
    _add_spend(db, usd, tier, task)
    try:
        data = unmask(qwen_gateway._parse_json(raw), mapping)
        problem = qwen_gateway._validate(data, schema)
    except Exception as e:
        data, problem = None, f"invalid JSON: {str(e)[:120]}"
    problems = [problem] if problem else []
    if not problem and code_check:
        problems += code_check(data, clean) or []
    return {"tier": tier, "status": "ok" if not problems else "rejected", "data": data, "problems": problems,
            "tokens_in": tin, "tokens_out": tout, "usd": round(usd, 6), "latency_s": round(time.time() - t0, 2)}


# ---------------------------------------------------------------- run


def run(*, task: str, system: str, subject: str = "", body: str = "", body_is_html: bool = False,
        attachments_text=None, schema: Optional[Dict[str, Any]] = None, code_check=None,
        ref: Optional[Dict[str, Any]] = None, bu: Optional[str] = None, now: Optional[datetime] = None,
        db=None, qwen_run: Callable[..., Dict[str, Any]] = None, cloud_transport=None,
        tiers: Optional[List[str]] = None, rules_result: Any = None, rules_complete: Optional[bool] = None,
        enqueue_on_fail: bool = True, **_ignored) -> Dict[str, Any]:
    """Same contract as qwen_gateway.run; adds `tier` (who answered) and `attempts`.

    rules_result: the caller's rules answer (the first rung). Accepted without
    any model when it is valid, complete (rules_complete, default True) and
    passes code_check -- same bar as a model answer."""
    c = cfg()
    db = db if db is not None else qwen_gateway._gov_db()
    qwen_run = qwen_run or qwen_gateway.run
    cloud_transport = cloud_transport or anthropic_transport
    qcfg = config_store.get("qwen")
    tcfg = (qcfg.get("tasks") or {}).get(task) or {}
    ladder = list(tiers or (c.get("task_tiers") or {}).get(task) or c.get("default_tiers") or ["qwen"])
    if not c.get("enabled", True):
        ladder = [t for t in ladder if t == "qwen"] or ["qwen"]
    clean = qwen_gateway.clean_input(subject, body, body_is_html, attachments_text,
                                     int(tcfg.get("max_input_chars") or qcfg.get("max_input_chars") or 6000))
    attempts: List[Dict[str, Any]] = []
    best = None
    if rules_result is not None:
        problem = qwen_gateway._validate(rules_result, schema)
        problems = [problem] if problem else []
        if not problem and code_check:
            problems += code_check(rules_result, clean) or []
        if rules_complete is False:
            problems.append("rules answer incomplete")
        attempts.append({"tier": "rules", "status": "ok" if not problems else "rejected", "problems": problems})
        if not problems:
            return _finish(task, rules_result, "rules", attempts, tcfg, ref, bu, clean, db, now)
    for tier in ladder:
        if tier == "qwen":
            if task not in (qcfg.get("tasks") or {}):
                continue
            r = qwen_run(task=task, system=system, subject=subject, body=body, body_is_html=body_is_html,
                         attachments_text=attachments_text, schema=schema, code_check=code_check, ref=ref, bu=bu,
                         now=now, enqueue_review=False)
            if r.get("status") == "deferred":
                return {**r, "tier": "qwen", "attempts": attempts}          # night-only work: wait, don't buy it
            passed = r.get("status") in ("ok", "review") and not (r.get("problems") or []) and r.get("data") is not None
            attempts.append({"tier": "qwen", "status": "ok" if passed else (r.get("status") or "failed"),
                             "problems": r.get("problems") or ([r["error"]] if r.get("error") else []), "job_id": r.get("job_id")})
            if passed:
                return _finish(task, r.get("data"), "qwen", attempts, tcfg, ref, bu, clean, db, now)
            if r.get("data") is not None:
                best = {"tier": "qwen", "data": r.get("data"), "problems": r.get("problems") or []}
            continue
        if tier not in (c.get("models") or {}):
            continue
        if _UNAVAILABLE.get(tier, 0) > time.time():
            attempts.append({"tier": tier, "status": "skipped", "problems": ["tier unavailable (credit / key / outage)"]})
            continue
        budget = float(c.get("monthly_budget_usd") or 0)
        if budget and spent_this_month(db) >= budget:
            attempts.append({"tier": tier, "status": "skipped", "problems": [f"monthly AI budget ${budget:g} used"]})
            continue
        a = _cloud_attempt(tier, task=task, system=system, clean=clean, schema=schema, code_check=code_check,
                           c=c, db=db, transport=cloud_transport)
        _log(db, task, ref, a, now)
        attempts.append({k: a.get(k) for k in ("tier", "status", "problems", "error", "usd")})
        if a["status"] == "ok":
            return _finish(task, a["data"], tier, attempts, tcfg, ref, bu, clean, db, now)
        if a.get("data") is not None:
            best = {"tier": tier, "data": a["data"], "problems": a.get("problems") or []}
    # nobody passed the checks: one review item with the best attempt
    problems = (best or {}).get("problems") or [p for at in attempts for p in (at.get("problems") or [])][:6]
    if not enqueue_on_fail:      # the caller already has its own review item (e.g. a reply draft for one)
        return {"status": "failed", "data": None, "problems": problems, "tier": None, "attempts": attempts,
                "review_item": None, "job_id": None}
    item = review_queue.enqueue(
        type="ai_invalid_output", module=task, ref=ref or {"collection": "ladder", "id": f"{task}:{hash(clean)}"},
        reason="; ".join(str(p) for p in problems)[:400] or "no tier produced a valid answer",
        payload={"task": task, "clean_input": clean[:4000], "attempts": attempts},
        suggested=(best or {}).get("data") if isinstance((best or {}).get("data"), dict) else None, bu=bu)
    return {"status": "review", "data": (best or {}).get("data"), "problems": problems, "tier": (best or {}).get("tier"),
            "attempts": attempts, "review_item": item, "job_id": None}


def _finish(task, data, tier, attempts, tcfg, ref, bu, clean, db, now):
    """Accepted. always_review tasks (RFQ extraction until 95% per field) still go to a person."""
    item = None
    if tcfg.get("always_review"):
        item = review_queue.enqueue(
            type="rfq_extraction" if task == "rfq_extraction" else "vendor_bid" if task == "vendor_bid_parse" else "ai_low_confidence",
            module=task, ref=ref or {"collection": "ladder", "id": f"{task}:{hash(clean)}"},
            reason=f"answered by {tier}; reviewed until this task reaches 95% per field",
            payload={"task": task, "clean_input": clean[:4000], "attempts": attempts}, suggested=data if isinstance(data, dict) else None, bu=bu)
    return {"status": "review" if item else "ok", "data": data, "problems": [], "tier": tier,
            "attempts": attempts, "review_item": item, "job_id": None}


def _log(db, task, ref, a, now):
    try:
        db["ladder_jobs"].insert_one({"task": task, "ref": ref, "at": now or datetime.utcnow(),
                                      **{k: a.get(k) for k in ("tier", "status", "problems", "error", "tokens_in", "tokens_out",
                                                               "usd", "latency_s")}})
    except Exception:
        pass


def escalate_json(*, task: str, system: str, user: str, schema: Optional[Dict[str, Any]],
                  check: Callable[[Any], List[str]], local: Optional[Callable[[], Any]] = None,
                  tiers: Optional[List[str]] = None, db=None, cloud_transport=None) -> Tuple[Any, Optional[str], List[Dict[str, Any]]]:
    """For older modules that call the local model themselves (local_slm_client.chat_json)
    and validate the answer with their own check. Tries `local()` first, then the
    cloud rungs, each judged by `check(data) -> [problems]`. Returns
    (data or None, tier or None, attempts); never opens a review item -- the caller
    keeps its own fallback (template, task, no proposal)."""
    c = cfg()
    db = db if db is not None else qwen_gateway._gov_db()
    cloud_transport = cloud_transport or anthropic_transport
    attempts: List[Dict[str, Any]] = []
    if local is not None:
        try:
            data = local()
            probs = check(data) or []
        except Exception as e:
            data, probs = None, [f"local model: {str(e)[:160]}"]
        attempts.append({"tier": "qwen", "status": "ok" if not probs else "rejected", "problems": probs})
        if not probs:
            return data, "qwen", attempts
    ladder = [t for t in (tiers or (c.get("task_tiers") or {}).get(task) or c.get("default_tiers") or []) if t != "qwen"]
    if not c.get("enabled", True):
        ladder = []
    for tier in ladder:
        if tier not in (c.get("models") or {}):
            continue
        if _UNAVAILABLE.get(tier, 0) > time.time():
            attempts.append({"tier": tier, "status": "skipped", "problems": ["tier unavailable"]})
            continue
        budget = float(c.get("monthly_budget_usd") or 0)
        if budget and spent_this_month(db) >= budget:
            attempts.append({"tier": tier, "status": "skipped", "problems": ["monthly AI budget used"]})
            continue
        a = _cloud_attempt(tier, task=task, system=system, clean=user, schema=schema,
                           code_check=lambda d, _clean: check(d), c=c, db=db, transport=cloud_transport)
        _log(db, task, None, a, None)
        attempts.append({k: a.get(k) for k in ("tier", "status", "problems", "error", "usd")})
        if a["status"] == "ok":
            return a["data"], tier, attempts
    return None, None, attempts


def stats(db=None, days: int = 30) -> Dict[str, Any]:
    """Per task and tier: calls, accepted %, spend -- for the System Health dashboard."""
    from datetime import timedelta
    db = db if db is not None else qwen_gateway._gov_db()
    since = datetime.utcnow() - timedelta(days=days)
    out: Dict[str, Any] = {}
    for r in db["ladder_jobs"].aggregate([
            {"$match": {"at": {"$gte": since}}},
            {"$group": {"_id": {"task": "$task", "tier": "$tier", "status": "$status"}, "n": {"$sum": 1}, "usd": {"$sum": "$usd"}}}]):
        k = f"{r['_id']['task']}/{r['_id']['tier']}"
        row = out.setdefault(k, {"calls": 0, "accepted": 0, "usd": 0.0})
        row["calls"] += r["n"]
        row["usd"] = round(row["usd"] + float(r.get("usd") or 0), 4)
        if r["_id"]["status"] == "ok":
            row["accepted"] += r["n"]
    return {"by_task_tier": out, "spent_this_month_usd": round(spent_this_month(db), 4)}
