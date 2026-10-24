"""Daily check that the tracker is receiving data from every company site
(owner 2026-10-24). A site that has sent data before and then goes silent for
web.site_silence_alert_hours shows in "Needs attention" (kpi.compute)."""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


def _gd():
    from database import get_database
    return get_database


def run(now: Optional[datetime] = None, gd=None) -> Dict[str, Any]:
    from platform_core import config_store
    gd = gd or _gd()
    cfg = config_store.get("web")
    now = now or datetime.utcnow()
    ev = gd("email_automation")["web_events"]
    hours = int(cfg.get("site_silence_alert_hours") or 24)
    sites = []
    for s in cfg.get("sites") or []:
        last = ev.find_one({"host": s["domain"]}, {"at": 1}, sort=[("at", -1)])
        n24 = ev.count_documents({"host": s["domain"], "at": {"$gte": now - timedelta(hours=24)}})
        forms = ev.count_documents({"host": s["domain"], "type": "form_submit", "at": {"$gte": now - timedelta(hours=24)}})
        state = ("not_installed" if not last else
                 "ok" if now - last["at"] <= timedelta(hours=hours) else "silent")
        sites.append({"domain": s["domain"], "bu": s["bu"], "events_24h": n24, "form_submits_24h": forms,
                      "last_event_at": (last or {}).get("at"), "status": state})
    doc = {"at": now, "sites": sites}
    gd("email_automation")["web_site_checks"].insert_one(dict(doc))
    return doc
