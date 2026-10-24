"""Scheduled mail pipeline run (every 5 minutes, CRM plan Section 6).

Picks inbound mail not yet decided (no row in email_automation.mail_decisions),
newest first, runs pipeline.process, stores the decision, and in live mode
applies the planned actions. Model calls per run are capped (config
mail_pipeline.max_model_calls_per_run) to keep the 4-vCPU VM responsive.
"""
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from . import pipeline

logger = logging.getLogger(__name__)

DEFAULTS = {"mode": "shadow", "batch": 50, "max_model_calls_per_run": 10, "lookback_days": 14, "max_seconds": 240}
_CTX = {"ctx": None, "at": 0.0}


def _client():
    from database import get_database
    return get_database


def settings(gd) -> Dict[str, Any]:
    doc = gd("torpedo_settings")["config"].find_one({"_id": "mail_pipeline"}) or {}
    return {**DEFAULTS, **{k: v for k, v in doc.items() if k in DEFAULTS}}


def _context():
    """mail_categorizer's client/vendor context; rebuilt at most hourly (it aggregates)."""
    if _CTX["ctx"] is None or time.time() - _CTX["at"] > 3600:
        from pymongo import MongoClient
        import os
        from app.services.mail_categorizer import build_context
        _CTX["ctx"] = build_context(MongoClient(os.environ.get("MONGO_URI", "mongodb://localhost:27017/")))
        _CTX["at"] = time.time()
    return _CTX["ctx"]


def _bounce_patterns():
    from routers.cold_outreach_router import _BOUNCE_FROM_PATTERN, _BOUNCE_SUBJECT_PATTERN, _OOO_SUBJECT_PATTERN
    return (_BOUNCE_FROM_PATTERN, _BOUNCE_SUBJECT_PATTERN, _OOO_SUBJECT_PATTERN)


class _CappedModel:
    def __init__(self, cap: int):
        self.cap, self.used = cap, 0

    def __call__(self, **kw):
        if self.used >= self.cap:
            return {"status": "deferred", "reason": "model call cap for this run"}
        self.used += 1
        from platform_core import qwen_gateway
        return qwen_gateway.run(**kw)


def apply_actions(decision: Dict[str, Any], gd) -> list:
    """Live mode only. Every action is audit-logged; mail is never sent here
    (drafts go to the Review Queue, events go to the modules that own them)."""
    from bson import ObjectId
    from platform_core import review_queue
    from platform_core.audit import log_action
    done = []
    torpedo, crm, ea = gd("torpedo"), gd("crm_db"), gd("email_automation")
    for a in decision["actions"]:
        t = a["type"]
        try:
            if t == "stop_sequence" and a.get("outreach_lead_id"):
                torpedo["outreach_leads_v2"].update_one(
                    {"_id": ObjectId(a["outreach_lead_id"]), "workflow_status": {"$in": ["in_sequence", "not_started", "pending_scheduled"]}},
                    {"$set": {"workflow_status": "replied", "replied_at": datetime.utcnow()}})
            elif t == "pause_sequence" and a.get("outreach_lead_id") and a.get("until"):
                torpedo["outreach_leads_v2"].update_one(
                    {"_id": ObjectId(a["outreach_lead_id"])},
                    {"$set": {"next_send_at": datetime.fromisoformat(a["until"]), "paused_reason": a["why"]}})
            elif t == "suppress" and a.get("email"):
                from messaging import suppression
                suppression.suppress(a["email"], a.get("reason", "manual"), source="mail_pipeline")
            elif t == "account_dnd" and a.get("domain"):
                crm["accounts"].update_many({"$or": [{"domain": a["domain"]}, {"root_domain": a["domain"]}]},
                                            {"$set": {"dnd": True, "dnd_reason": a["why"], "dnd_at": datetime.utcnow()}})
            elif t in ("skrapp_refind", "soft_bounce_retry"):
                ea["mail_followups"].insert_one({**a, "message_id": decision["message_id"], "status": "new",
                                                 "created_at": datetime.utcnow()})
            elif t == "event":
                ea["mail_events"].insert_one({"event": a["event"], "message_id": decision["message_id"],
                                              "gmail_thread_id": decision.get("gmail_thread_id"),
                                              "link": decision["link"], "status": "new", "created_at": datetime.utcnow()})
            elif t == "review":
                review_queue.enqueue(type=a.get("review_type", "other"), module="mail_pipeline",
                                     ref={"collection": "torpedo_gmail.email_metadata", "id": decision["message_id"]},
                                     reason=a["why"], payload={"decision": {k: decision[k] for k in ("link", "sender", "category")}})
            log_action(actor="system", action="update", entity_type="mail_action", entity_id=decision["message_id"],
                       reason=f"{t}: {a.get('why', '')}"[:200], source="mail_pipeline", metadata={"action": a})
            done.append(t)
        except Exception:
            logger.exception("mail action %s failed for %s", t, decision["message_id"])
    return done


def run_batch(now: Optional[datetime] = None) -> Dict[str, Any]:
    gd = _client()
    cfg = settings(gd)
    now = now or datetime.utcnow()
    decisions = gd("email_automation")["mail_decisions"]
    md = gd("torpedo_gmail")["email_metadata"]
    db = {"outreach_sends": gd("torpedo")["outreach_sends_v2"], "vendor_bids": gd("crm_db")["vendor_bids"],
          "threads": gd("crm_db")["threads"], "opportunities": gd("crm_db")["opportunities"],
          "leads": gd("crm_db")["leads"], "contacts": gd("crm_db")["contacts"], "accounts": gd("crm_db")["accounts"]}
    ctx, patterns = _context(), _bounce_patterns()
    model = _CappedModel(int(cfg["max_model_calls_per_run"]))
    since = now - timedelta(days=int(cfg["lookback_days"]))
    stats = {"seen": 0, "decided": 0, "applied": 0, "mode": cfg["mode"]}
    t_start = time.time()      # stay well inside the 5-minute interval
    for msg in md.find({"direction": "inbound", "timestamp": {"$gte": since}},
                       {"subject": 1, "body_plain": 1, "snippet": 1, "from_email": 1, "to_emails": 1, "cc_emails": 1,
                        "gmail_thread_id": 1, "gmail_message_id": 1, "timestamp": 1}).sort("timestamp", -1).limit(int(cfg["batch"]) * 4):
        if stats["decided"] >= int(cfg["batch"]) or time.time() - t_start > float(cfg["max_seconds"]):
            break
        stats["seen"] += 1
        if decisions.count_documents({"message_id": str(msg["_id"])}, limit=1):
            continue
        d = pipeline.process(msg, db, ctx, model, patterns)
        d.update(mode=cfg["mode"], decided_at=now, pipeline_version=1)
        if cfg["mode"] == "live":
            d["applied"] = apply_actions(d, gd)
            stats["applied"] += 1
        decisions.insert_one(d)
        stats["decided"] += 1
    stats["model_calls"] = model.used
    logger.info("mail pipeline: %s", stats)
    return stats
