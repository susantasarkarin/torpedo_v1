"""The one door for Qwen calls (CRM plan 3.1).

    result = run(task="rfq_extraction", subject=..., body=..., attachments_text=[...],
                 system=PROMPT, schema=JSON_SCHEMA, code_check=fn, ref={...})

result["status"]:
    ok        output valid and the code checks passed -> the caller may act
    review    queued for a person (invalid twice, code checks failed, or the
              task is marked always_review) -> the caller must NOT act
    deferred  P3 work outside the night window -> retry later
    failed    transport failed after retries -> ai_governance.qwen_jobs status
              "failed" (visible in the UI with a retry button)

Every call is stored in ai_governance.qwen_jobs: task, model, content hash,
raw and cleaned input, raw output, parsed output, latency, status. The same
(task, model, cleaned input) is never processed twice: a finished job is
returned from that cache.

Self-reported confidence is NOT trusted (benchmark 2026-10-23): tasks pass a
code_check(data, clean_text) -> [problems] that decides instead.
"""
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

from . import config_store, review_queue
from .audit import log_action

logger = logging.getLogger(__name__)

PRIORITY_TO_GATE = {"P1": "rfq", "P2": "extraction", "P3": "bulk"}


# ------------------------------------------------------------------ cleaning
_QUOTE_SPLIT = re.compile(
    r"\n(?:-{2,}\s*Original Message\s*-{2,}|_{5,}|From:\s.+\nSent:|On .{5,120}wrote:|"
    r"Le .{5,120}a écrit|Am .{5,120}schrieb)", re.I)
_SIG_SPLIT = re.compile(r"\n(?:--\s*\n|Regards,|Best regards,|Kind regards,|Thanks(?: and| &) regards,|Warm regards,|Sent from my )", re.I)
_DISCLAIMER = re.compile(r"\n(?:DISCLAIMER|CONFIDENTIALITY NOTICE|This (?:e-?mail|communication|message) (?:and any|is) (?:confidential|intended)).*", re.I | re.S)
_TRACKING = re.compile(r"<https?://[^>]+>|\[(?:image|cid)[^\]]*\]|https?://\S*(?:utm_|track|click|open)\S*", re.I)


def strip_html(html_text: str) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_text or "", "html.parser")
        for t in soup(["script", "style", "img"]):
            t.decompose()
        return soup.get_text("\n")
    except Exception:
        return re.sub(r"<[^>]+>", " ", html_text or "")


def clean_input(subject: str = "", body: str = "", body_is_html: bool = False,
                attachments_text: Optional[List[Dict[str, str]]] = None, max_chars: int = 6000) -> str:
    """Newest message only + subject + labelled attachment blocks, capped."""
    text = strip_html(body) if body_is_html else (body or "")
    text = _QUOTE_SPLIT.split(text)[0]
    text = _DISCLAIMER.sub("", text)
    text = _SIG_SPLIT.split(text)[0]
    text = _TRACKING.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    parts = [f"SUBJECT: {subject.strip()}" if subject else "", f"MESSAGE:\n{text}"]
    budget = max_chars - sum(len(p) for p in parts)
    for att in attachments_text or []:
        if budget <= 200:
            break
        block = (att.get("text") or "")[: max(0, budget - 80)]
        parts.append(f"ATTACHMENT ({att.get('name', 'file')}):\n{block}")
        budget -= len(block) + 80
    out = "\n\n".join(p for p in parts if p)
    return out[:max_chars]


def content_hash(task: str, model: str, clean: str, system: str) -> str:
    return hashlib.sha256(f"{task}\x00{model}\x00{system}\x00{clean}".encode()).hexdigest()


# --------------------------------------------------------------- scheduling
def in_p3_window(now_utc: datetime, window=(22, 7)) -> bool:
    h = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Kolkata")).hour
    start, end = window
    return h >= start or h < end if start > end else start <= h < end


# ----------------------------------------------------------------- transport
def _endpoint_for(model: str) -> Dict[str, str]:
    slug = re.sub(r"[^A-Z0-9]+", "_", model.upper()).strip("_")
    base = (os.getenv(f"QWEN_ENDPOINT_{slug}") or os.getenv("SELF_HOSTED_BASE_URL") or "").rstrip("/")
    key = os.getenv(f"QWEN_KEY_{slug}") or os.getenv("SELF_HOSTED_API_KEY") or "not-required"
    return {"url": f"{base}/chat/completions", "key": key}


def http_transport(model: str, system: str, user: str, max_tokens: int, timeout: float,
                   priority: str, temperature: float = 0.0) -> str:
    ep = _endpoint_for(model)
    if not ep["url"].startswith("http"):
        raise RuntimeError(f"no endpoint configured for model {model}")
    body = {"model": model, "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    from leads.local_llm_gate import acquire_local_llm_slot
    with acquire_local_llm_slot(priority=PRIORITY_TO_GATE.get(priority, "bulk")):
        r = requests.post(ep["url"], json=body, headers={"Authorization": f"Bearer {ep['key']}"}, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _parse_json(raw: str) -> Any:
    s = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip()).strip()
    return json.loads(s)


def _validate(data: Any, schema: Optional[Dict[str, Any]]) -> Optional[str]:
    if not schema:
        return None
    try:
        import jsonschema
        jsonschema.validate(data, schema)
        return None
    except Exception as e:
        return str(e).split("\n")[0][:200]


def _few_shot(db, task: str, n: int = 3) -> str:
    try:
        ex = list(db["labelled_examples"].find({"task": task, "label": {"$ne": None}}).sort("at", -1).limit(n))
    except Exception:
        return ""
    if not ex:
        return ""
    lines = ["\nExamples corrected by a person (follow them):"]
    for e in ex:
        lines.append(f"INPUT:\n{(e.get('input') or '')[:800]}\nCORRECT OUTPUT:\n{json.dumps(e.get('label'))[:800]}")
    return "\n".join(lines)


def _gov_db():
    try:
        from database import get_database
    except ImportError:
        from ..database import get_database
    return get_database("ai_governance")


# ---------------------------------------------------------------------- run
def run(*, task: str, system: str, subject: str = "", body: str = "", body_is_html: bool = False,
        attachments_text: Optional[List[Dict[str, str]]] = None, schema: Optional[Dict[str, Any]] = None,
        code_check: Optional[Callable[[Any, str], List[str]]] = None, ref: Optional[Dict[str, Any]] = None,
        bu: Optional[str] = None, transport: Callable[..., str] = http_transport,
        now: Optional[datetime] = None, db=None, sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    cfg = config_store.get("qwen")
    tcfg = cfg["tasks"].get(task)
    if not tcfg:
        raise KeyError(f"no qwen task config for {task!r}")
    now = now or datetime.utcnow()
    db = db if db is not None else _gov_db()
    jobs = db["qwen_jobs"]
    model, priority = tcfg["model"], tcfg.get("priority", "P2")

    # the 1.5B server runs with a 2,048-token context: each task carries its own budget
    clean = clean_input(subject, body, body_is_html, attachments_text,
                        int(tcfg.get("max_input_chars") or cfg["max_input_chars"]))
    h = content_hash(task, model, clean, system)
    cached = jobs.find_one({"hash": h, "status": {"$in": ["ok", "review"]}})
    if cached:
        return {"status": cached["status"], "data": cached.get("output"), "job_id": str(cached["_id"]),
                "cached": True, "review_item": cached.get("review_item")}

    if priority == "P3" and not in_p3_window(now, tuple(cfg["p3_window_ist"])):
        return {"status": "deferred", "reason": "P3 runs 22:00-07:00 IST"}

    job = {"task": task, "model": model, "priority": priority, "hash": h, "raw_input": {"subject": subject,
           "body": (body or "")[:20000]}, "clean_input": clean, "ref": ref, "bu": bu, "created_at": now,
           "attempts": 0, "status": "running"}
    job_id = jobs.insert_one(job).inserted_id
    sys_prompt = system + _few_shot(db, task)

    raw, err, latency = None, None, None
    backoff = list(cfg.get("retry_backoff_seconds") or [10, 60, 300])
    for attempt in range(int(cfg.get("retries", 3)) + 1):
        t0 = time.time()
        try:
            raw = transport(model, sys_prompt, clean, tcfg.get("max_tokens", 600), tcfg.get("timeout_s", 60), priority)
            latency = round(time.time() - t0, 2)
            err = None
            break
        except Exception as e:
            err = str(e)[:300]
            jobs.update_one({"_id": job_id}, {"$inc": {"attempts": 1}, "$set": {"last_error": err}})
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status is not None and 400 <= int(status) < 500:
                break           # a bad request fails the same way every time: no retry, no backoff
            if attempt < int(cfg.get("retries", 3)):
                sleep(backoff[min(attempt, len(backoff) - 1)])
    if err is not None:
        jobs.update_one({"_id": job_id}, {"$set": {"status": "failed", "failed_at": datetime.utcnow()}})
        log_action(actor="system", action="update", entity_type="qwen_job", entity_id=str(job_id),
                   reason=f"failed after retries: {err}", source="qwen_gateway")
        return {"status": "failed", "error": err, "job_id": str(job_id)}

    data, problem = None, None
    for retry in (False, True):
        try:
            data = _parse_json(raw)
            problem = _validate(data, schema)
        except Exception as e:
            data, problem = None, f"invalid JSON: {str(e)[:120]}"
        if not problem or retry:
            break
        try:     # one retry at temperature 0 with an explicit reminder
            raw = transport(model, sys_prompt + "\nReturn ONLY valid JSON that matches the schema.", clean,
                            tcfg.get("max_tokens", 600), tcfg.get("timeout_s", 60), priority)
        except Exception as e:
            problem = f"retry failed: {e}"
            break

    problems: List[str] = [problem] if problem else []
    if not problem and code_check:
        problems += code_check(data, clean) or []
    needs_review = bool(problems) or bool(tcfg.get("always_review"))
    update = {"raw_output": (raw or "")[:20000], "output": data, "latency_s": latency,
              "problems": problems, "finished_at": datetime.utcnow(),
              "status": "review" if needs_review else "ok"}
    item_id = None
    if needs_review:
        rtype = "ai_invalid_output" if problem else (
            "rfq_extraction" if task == "rfq_extraction" else
            "vendor_bid" if task == "vendor_bid_parse" else "ai_low_confidence")
        item_id = review_queue.enqueue(
            type=rtype, module=task, ref=ref or {"collection": "ai_governance.qwen_jobs", "id": str(job_id)},
            reason="; ".join(problems) or "always reviewed until the model reaches 95% per field",
            payload={"task": task, "input_hash": h, "clean_input": clean, "job_id": str(job_id)},
            suggested=data if isinstance(data, dict) else {"value": data},
            resume={"handler": f"qwen:{task}", "ref": ref}, bu=bu)
        update["review_item"] = item_id
    jobs.update_one({"_id": job_id}, {"$set": update})
    return {"status": update["status"], "data": data, "problems": problems, "job_id": str(job_id),
            "review_item": item_id, "cached": False}


_RUNNERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}


def register_runner(task: str, fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
    """A task's own entry point, fn(ref) -> run(...) result. Used by the retry button."""
    _RUNNERS[task] = fn


def retry_failed(job_id: str, db=None) -> Dict[str, Any]:
    """UI retry button: re-run a failed job through its task's registered runner
    (the runner holds the prompt, schema and code checks)."""
    from bson import ObjectId
    db = db if db is not None else _gov_db()
    job = db["qwen_jobs"].find_one({"_id": ObjectId(job_id), "status": "failed"})
    if not job:
        return {"ok": False, "error": "no failed job with that id"}
    runner = _RUNNERS.get(job["task"])
    if not runner:
        return {"ok": False, "error": f"no runner registered for task {job['task']}"}
    db["qwen_jobs"].update_one({"_id": job["_id"]}, {"$set": {"status": "retried", "retried_at": datetime.utcnow()}})
    return {"ok": True, "result": runner(job.get("ref") or {})}


def failed_jobs(limit: int = 100, db=None) -> List[Dict[str, Any]]:
    db = db if db is not None else _gov_db()
    out = []
    for j in db["qwen_jobs"].find({"status": "failed"}, {"raw_input": 0, "clean_input": 0}).sort("created_at", -1).limit(limit):
        j["_id"] = str(j["_id"])
        out.append(j)
    return out
