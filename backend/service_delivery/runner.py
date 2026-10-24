"""Daily Service Delivery reminders (CRM plan 3.13 step 8, Section 6).

Shadow (default): planned reminders -> email_automation.service_delivery_decisions.
Live (owner, config service_delivery.mode): owner reminders become CRM tasks,
client reminders Review Queue drafts.
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId

from service_delivery import rules

logger = logging.getLogger(__name__)


def _gd():
    from database import get_database
    return get_database


def run(now: Optional[datetime] = None) -> Dict[str, Any]:
    from platform_core import config_store, review_queue
    gd = _gd()
    cfg = config_store.get("service_delivery")
    now = now or datetime.utcnow()
    crm = gd("crm_db")
    projects = list(crm["service_projects"].find({"status": {"$ne": "closed"}}))
    ids = []
    for p in projects:
        try:
            ids.append(ObjectId(str(p.get("contact_id"))))
        except Exception:
            pass
    emails = {str(c["_id"]): (c.get("email") or "").lower() for c in crm["contacts"].find({"_id": {"$in": ids}}, {"email": 1})}
    r = rules.reminders(projects, now, emails, cfg)
    if cfg["mode"] == "live":
        for o in r["owner"]:
            crm["tasks"].insert_one({"title": f"Milestone due: {o['project']} / {o['milestone']}", "assignee": o["to"],
                                     "due_date": o["due"], "status": "open", "source": "service_delivery", "created_at": now})
        for c in r["client"]:
            review_queue.enqueue(type="other", module="service_delivery",
                                 ref={"collection": "sd_client_mail", "id": f"{c['to']}:{now:%Y%m%d}"},
                                 reason="client review pending > 5 days: reminder drafted", suggested=c)
    stats = {"mode": cfg["mode"], "projects": len(projects), "owner_reminders": len(r["owner"]),
             "client_reminders": len(r["client"]), "on_hold_over_7d": len(r["on_hold_for_paused_digest"])}
    gd("email_automation")["service_delivery_decisions"].insert_one({"at": now, **stats})
    logger.info("service delivery: %s", stats)
    return stats
