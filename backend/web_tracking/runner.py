"""Visit scoring + follow-ups (every 30 min) and retargeting audiences (daily),
CRM plan 3.12 / Section 6.

Shadow (default): decisions -> email_automation.web_decisions. Live (owner,
config web.mode): follow-ups become Review Queue items (mail copy is
client-facing) and visits are stamped on the contact for the 360 timeline.
Audience sync to ad platforms needs the owner's ad account IDs and API
access; until then the audience sizes are recorded only.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from bson import ObjectId

from web_tracking import rules

logger = logging.getLogger(__name__)


def _gd():
    from database import get_database
    return get_database


def run(now: Optional[datetime] = None) -> Dict[str, Any]:
    from platform_core import config_store, review_queue
    gd = _gd()
    cfg = config_store.get("web")
    now = now or datetime.utcnow()
    ea, crm = gd("email_automation"), gd("crm_db")
    out = ea["web_decisions"]
    stats: Dict[str, Any] = {"mode": cfg["mode"], "visitors": 0, "follow_ups": 0}
    for v in ea["web_visitors"].find({"last_seen": {"$gte": now - timedelta(minutes=45)}}).limit(2000):
        stats["visitors"] += 1
        events = list(ea["web_events"].find({"visitor_id": v["visitor_id"], "at": {"$gte": now - timedelta(days=7)}}))
        ctx = {"contact_id": v.get("contact_id"), "company_match": v.get("company_match"), "dnd": False}
        if v.get("contact_id"):
            try:
                c = crm["contacts"].find_one({"_id": ObjectId(v["contact_id"])}, {"email": 1, "dnd": 1})
            except Exception:
                c = None
            email = ((c or {}).get("email") or "").lower()
            ctx["dnd"] = bool((c or {}).get("dnd"))
            if email:
                ctx["in_active_sequence"] = bool(gd("torpedo")["outreach_leads_v2"].find_one(
                    {"email": email, "workflow_status": "in_sequence"}, {"_id": 1}))
        act = rules.follow_up(ctx, events, now, cfg)
        sc = rules.score(events, now, cfg)
        ea["web_visitors"].update_one({"_id": v["_id"]}, {"$set": {"score": sc["score"], "level": sc["level"],
                                                                     "high_intent": sc["level"] == "high"}})
        if not act:
            continue
        key = f"{v['visitor_id']}:{act['action']}:{now:%Y%m%d}"
        if out.count_documents({"key": key}, limit=1):
            continue
        out.insert_one({"key": key, "at": now, "mode": cfg["mode"], "visitor_id": v["visitor_id"], **act})
        stats["follow_ups"] += 1
        if cfg["mode"] == "live":
            review_queue.enqueue(type="other", module="web", ref={"collection": "web_visitors", "id": key},
                                 reason=f"website visit: {act['action']} (score {sc['score']}: {', '.join(sc['why'])})",
                                 payload=act)
    logger.info("web scoring: %s", stats)
    return stats


def audience_sync(now: Optional[datetime] = None) -> Dict[str, Any]:
    from platform_core import config_store
    gd = _gd()
    cfg = config_store.get("web")
    now = now or datetime.utcnow()
    ea = gd("email_automation")
    vis = list(ea["web_visitors"].find({"last_seen": {"$gte": now - timedelta(days=cfg["audience_window_days"])}},
                                       {"visitor_id": 1, "bus": 1, "consent": 1, "last_seen": 1, "high_intent": 1,
                                        "form_email": 1, "contact_id": 1}))
    for v in vis:
        v["form_abandoned"] = bool(v.get("form_email")) and not v.get("contact_id")
    aud = rules.audiences(vis, now, cfg)
    sizes = {bu: {k: len(x) for k, x in a.items()} for bu, a in aud.items()}
    ea["web_audiences"].insert_one({"at": now, "sizes": sizes, "synced": False,
                                    "reason": "ad account IDs / API access not configured (owner)"})
    return sizes
