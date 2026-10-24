"""Nightly dormant flagging + re-engagement plan (CRM plan 3.10, Section 6).

Shadow (default): statuses and planned mails go to
email_automation.reengagement_decisions only. Live (owner, config
reengagement.mode): crm_db.accounts.engagement_status is stamped and each
planned mail becomes a Review Queue draft (client-facing copy).
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from crm360.view import BU_OF_DOMAIN, WEBMAIL
from reengage import rules

logger = logging.getLogger(__name__)


def _gd():
    from database import get_database
    return get_database


def domain_last_seen(md) -> Dict[str, Dict[str, datetime]]:
    """One pass over the mail log: {domain: {'inbound': t, 'outbound': t}}."""
    out: Dict[str, Dict[str, datetime]] = {}
    for r in md.aggregate([
            {"$match": {"mail_counterparty": {"$type": "string"}, "direction": {"$in": ["inbound", "outbound"]}}},
            {"$project": {"direction": 1, "timestamp": 1,
                          "domain": {"$toLower": {"$arrayElemAt": [{"$split": ["$mail_counterparty", "@"]}, 1]}}}},
            {"$group": {"_id": {"d": "$domain", "dir": "$direction"}, "last": {"$max": "$timestamp"}}}],
            allowDiskUse=True):
        if r["_id"].get("d"):
            out.setdefault(r["_id"]["d"], {})[r["_id"]["dir"]] = r["last"]
    return out


def last_two_way(seen: Dict[str, Dict[str, datetime]], domains) -> Optional[datetime]:
    """Latest point at which both directions had happened (a one-way blast is
    not communication): min(last inbound, last outbound) over the domains."""
    inbound = [seen[d]["inbound"] for d in domains if d in seen and seen[d].get("inbound")]
    outbound = [seen[d]["outbound"] for d in domains if d in seen and seen[d].get("outbound")]
    return min(max(inbound), max(outbound)) if inbound and outbound else None


def run(now: Optional[datetime] = None) -> Dict[str, Any]:
    from platform_core import config_store, review_queue
    gd = _gd()
    cfg = config_store.get("reengagement")
    now = now or datetime.utcnow()
    crm, ea = gd("crm_db"), gd("email_automation")
    md = gd("torpedo_gmail")["email_metadata"]
    live_accounts = {str(p.get("customer_id")) for p in ea["projects"].find(
        {"status": "active", "is_deleted": {"$ne": True}}, {"customer_id": 1})}
    supp = ea["suppression"] if "suppression" in ea.list_collection_names() else None
    seen = domain_last_seen(md)
    cust_of = {str(c["crm_account_id"]): str(c["_id"]) for c in gd("finance_db")["customers"].find(
        {"crm_account_id": {"$nin": [None, ""]}}, {"crm_account_id": 1})}
    contact_domains: Dict[str, set] = {}
    for ct in crm["contacts"].find({"account_id": {"$nin": [None, ""]}, "email": {"$type": "string"}},
                                   {"account_id": 1, "email": 1}):
        dom = ct["email"].rsplit("@", 1)[-1].lower()
        contact_domains.setdefault(str(ct["account_id"]), set()).add(dom)
    counts: Dict[str, int] = {}
    candidates = []
    for a in crm["accounts"].find({}, {"name": 1, "domain": 1, "domains": 1, "dnd": 1, "reengagement": 1,
                                       "lifetime_revenue": 1}):
        raw = [a.get("domain")] + list(a.get("domains") or []) + sorted(contact_domains.get(str(a["_id"]), ()))
        domains = sorted({d.lower() for d in raw if d and d.lower() not in WEBMAIL and d.lower() not in BU_OF_DOMAIN})
        cust = cust_of.get(str(a["_id"]))
        dnd = bool(a.get("dnd")) or bool(supp is not None and domains and supp.find_one({"domain": {"$in": domains}}, {"_id": 1}))
        two_way = last_two_way(seen, domains)
        if not two_way and not cust and not dnd:
            counts["no_relationship"] = counts.get("no_relationship", 0) + 1     # a prospect, not ours to re-engage
            continue
        status = rules.engagement_status(dnd=dnd, has_live_project=bool(cust) and cust in live_accounts,
                                         last_two_way=two_way, now=now,
                                         sequence=a.get("reengagement"), cfg=cfg)
        counts[status] = counts.get(status, 0) + 1
        if status == "dormant":
            step = rules.next_step(a.get("reengagement"), now, cfg)
            if step:
                candidates.append({"account_id": str(a["_id"]), "name": a.get("name"), "step": step,
                                   "lifetime_revenue": a.get("lifetime_revenue")})
        if cfg["mode"] == "live":
            crm["accounts"].update_one({"_id": a["_id"]}, {"$set": {"engagement_status": status,
                                                                     "engagement_checked_at": now}})
    today = ea["reengagement_decisions"].count_documents({"kind": "planned", "mode": "live",
                                                          "at": {"$gte": now.replace(hour=0, minute=0, second=0)}})
    picked = rules.release(candidates, today, cfg)
    for c in picked:
        ea["reengagement_decisions"].insert_one({"kind": "planned", "mode": cfg["mode"], "at": now, **c})
        if cfg["mode"] == "live":
            d = rules.draft(c["step"], c.get("name") or "")
            review_queue.enqueue(type="other", module="reengagement",
                                 ref={"collection": "crm_db.accounts", "id": c["account_id"]},
                                 reason=f"dormant account: sequence step {c['step']}", suggested=d)
    stats = {"mode": cfg["mode"], **counts, "candidates": len(candidates), "planned": len(picked)}
    ea["reengagement_decisions"].insert_one({"kind": "summary", "at": now, **stats})
    logger.info("reengagement: %s", stats)
    return stats
