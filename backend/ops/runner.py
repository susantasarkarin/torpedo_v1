"""Daily Operations run (CRM plan 3.6, Section 6), 18:00 IST.

Plans, per client contact: one consolidated field update for live projects,
the Monday paused-projects digest, and reconciliation requests / reminders.
Also flags soft-launch variance (CPI revision) and filled projects (field
close). Shadow (default): everything is written to email_automation.
ops_decisions only. Live (owner, config ops.mode): lifecycle moves are
applied and each mail becomes a Review Queue draft for the PM to send; the
mails go out automatically once the owner approves the BU templates
(Checkpoint 3).
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId

from ops import lifecycle, mails

logger = logging.getLogger(__name__)


def _gd():
    from database import get_database
    return get_database


def _contact_email(crm, p) -> Optional[str]:
    oid = p.get("opportunity_id") or p.get("rfqId")
    try:
        opp = crm["opportunities"].find_one({"_id": ObjectId(str(oid))}, {"contact_id": 1, "metadata.rfq.from_email": 1}) if oid else None
    except Exception:
        opp = None
    if not opp:
        return None
    try:
        c = crm["contacts"].find_one({"_id": ObjectId(str(opp.get("contact_id")))}, {"email": 1})
    except Exception:
        c = None
    return ((c or {}).get("email") or ((opp.get("metadata") or {}).get("rfq") or {}).get("from_email") or "").lower() or None


def plan(projects, now: datetime, cfg: Dict[str, Any]) -> Dict[str, Any]:
    by_status: Dict[str, list] = {}
    for p in projects:
        by_status.setdefault(lifecycle.legacy_status(p), []).append(p)
    live = by_status.get("live", []) + by_status.get("soft_launch", [])
    out: Dict[str, Any] = {"counts": {k: len(v) for k, v in by_status.items()}, "moves": [], "review": []}
    for p in live:
        need = float(p.get("totalCompletesRequired") or 0)
        if need and float(p.get("actualCompletes") or 0) >= need:
            out["moves"].append({"project_id": str(p["_id"]), "to": "field_closed", "reason": "target reached"})
    for p in by_status.get("soft_launch", []):
        if mails.soft_launch_reached(p, cfg):
            v = mails.soft_launch_variance(p, cfg)
            if v:
                out["review"].append({"project_id": str(p["_id"]), "type": "unusual_price",
                                      "reason": "soft launch off quote: " + "; ".join(v) + " -> CPI revision"})
    out["field_updates"] = mails.field_updates([p for p in live if p.get("_contact_email")])
    pd = mails.paused_digests(by_status.get("paused", []), now, cfg)
    out["paused_digests"] = pd["mails"]
    out["review"] += [{"project_id": str(p["_id"]), "type": "other",
                       "reason": f"paused, {cfg['paused_mail_cap']} client mails unanswered"} for p in pd["review"]]
    rc = mails.reconciliation_mails(by_status.get("reconciliation", []), now, cfg)
    out["reconciliation"] = rc["mails"]
    out["moves"] += [{"project_id": str(p["_id"]), "to": "closed", "reason": "no IDs after "
                      f"{cfg['recon_bill_on_our_count_after_days']} days: bill on our count"} for p in rc["bill_on_our_count"]]
    return out


def run(now: Optional[datetime] = None) -> Dict[str, Any]:
    from platform_core import config_store, review_queue
    gd = _gd()
    cfg = config_store.get("ops")
    now = now or datetime.utcnow()
    col, crm = gd("email_automation")["projects"], gd("crm_db")
    projects = list(col.find({"is_deleted": {"$ne": True}, "status": {"$ne": "completed"}}))
    for p in projects:
        p["_contact_email"] = _contact_email(crm, p)
    d = plan(projects, now, cfg)
    d.update(mode=cfg["mode"], decided_at=now)
    if cfg["mode"] == "live":
        byid = {str(p["_id"]): p for p in projects}
        for m in d["moves"]:
            try:
                lifecycle.transition(col, byid[m["project_id"]], m["to"], actor="system", reason=m["reason"], now=now)
            except lifecycle.TransitionError as e:
                d["review"].append({"project_id": m["project_id"], "type": "other", "reason": str(e)})
        for r in d["review"]:
            review_queue.enqueue(type=r["type"], module="ops", ref={"collection": "email_automation.projects",
                                 "id": r["project_id"]}, reason=r["reason"])
        for m in d["field_updates"] + d["paused_digests"] + d["reconciliation"]:
            review_queue.enqueue(type="other", module="ops", ref={"collection": "ops_mail", "id": f"{m['kind']}:{m['to']}:{now:%Y%m%d}"},
                                 reason=f"{m['kind']} draft for {len(m['project_ids'])} project(s)",
                                 suggested={"to": m["to"], "subject": m["subject"], "body": m["body"]}, payload={"project_ids": m["project_ids"]})
    for k in ("field_updates", "paused_digests", "reconciliation"):     # masked in the stored decision
        for m in d[k]:
            m["to"] = m["to"][:2] + "***@" + m["to"].split("@")[-1]
    gd("email_automation")["ops_decisions"].insert_one(dict(d))
    stats = {"mode": d["mode"], **d["counts"], "moves": len(d["moves"]), "review": len(d["review"]),
             "mails": len(d["field_updates"]) + len(d["paused_digests"]) + len(d["reconciliation"])}
    logger.info("ops run: %s", stats)
    return stats
