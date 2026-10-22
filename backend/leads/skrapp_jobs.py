"""
Skrapp for bounced people and for the contacts already sitting in Skrapp lists
(owner, 2026-10-22: "use skrapp.io to find company details, mail id's which
has bounced, lead enrichment. if you get new mail ids or fresh ids then you
need to consider it as a fresh outreach").

refind_bounced  a person whose address bounced is looked up again by name +
                company domain. A DIFFERENT address Skrapp calls "valid" goes on
                the lead and starts a NEW outreach row from step 1 -- the old
                row stays bounced. 1 email credit per address found; nothing is
                asked while the account has no credits (checked first, free).
import_lists    every lead in every Skrapp list on the account (free) whose
                address Skrapp marked "valid" and that we have never had becomes
                a lead through the normal ingestion -- company check, basket,
                enrollment -- and its row is sendable: fresh outreach.

Company details come from Skrapp's free company card in leads/company_fit.py.
"""
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

STATE = "skrapp_refind"  # torpedo.<STATE>, one doc per bounced address
BOUNCED = ("bounced", "needs_human_intervention")
SERVICE = {"sfw": "data_services", "cogentix": "consumer_insights", "bimwave": "bimwave"}
BASKET = {"sfw": "A", "cogentix": "B", "bimwave": "C"}


def _client():
    from pymongo import MongoClient
    return MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/", serverSelectionTimeoutMS=8000)


def _names(row: Dict[str, Any], lead: Dict[str, Any]):
    from leads.email_builder import lead_names
    first, last = lead_names({**row, **{k: v for k, v in lead.items() if v}})
    return first, last


def _campaign_for(tdb, email: str, company: str, fallback_campaign: str) -> Optional[Dict[str, Any]]:
    """The campaign this person's company fits; the bounced row's campaign when
    the company is not typed yet (the send gate then holds it until it is)."""
    from leads import company_fit as cf
    doc = cf.lookup(company, email.split("@")[-1])
    biz = {"mr_agency": "sfw", "brand": "cogentix", "aec": "bimwave"}.get((doc or {}).get("type"))
    if biz:
        return tdb["outreach_campaigns_v2"].find_one({"business": biz, "is_active": True})
    if (doc or {}).get("type") == "other":
        return None
    return tdb["outreach_campaigns_v2"].find_one({"campaign_id": fallback_campaign, "is_active": True})


def refind_bounced(client=None, limit: int = 20, now: Optional[datetime] = None) -> Dict[str, Any]:
    from leads import skrapp_client
    from leads.icp_check import known_dead
    client = client or _client()
    now = now or datetime.utcnow()
    left = skrapp_client.email_credits_left(client)
    if left is not None and left <= 0:
        return {"skipped": "no Skrapp email credits left"}
    t, ea = client["torpedo"], client["email_automation"]
    state = t[STATE]
    done = {d["_id"] for d in state.find({}, {"_id": 1})}
    dead = known_dead(client)
    stats: Dict[str, int] = {}
    seen = set()
    for row in t["outreach_leads_v2"].find({"workflow_status": {"$in": list(BOUNCED)},
                                            "reply_received": {"$ne": True}}).sort("updated_at", -1):
        old = (row.get("email") or "").lower().strip()
        if not old or old in done or old in seen:
            continue
        seen.add(old)
        if len(seen) > limit:
            break
        lead = ea["leads_enriched"].find_one({"email": old}) or {}
        first, last = _names(row, lead)
        domain = (lead.get("company_domain") or "").lower() or old.split("@")[-1]
        from leads.email_pattern_system import company_email_domain
        domain = company_email_domain(domain) or old.split("@")[-1]
        r = skrapp_client.find(client, first, last, domain=domain, now=now)
        st = r.get("status")
        if st in ("monthly_limit", "not_configured", "key_rejected", "error"):
            stats[st] = stats.get(st, 0) + 1
            break  # out of credits / no key: not a verdict, try again later
        rec: Dict[str, Any] = {"at": now, "skrapp": st, "old_campaign": row.get("campaign_id")}
        new = (r.get("email") or "").lower()
        if st != "found":
            rec["result"] = "not_found"
        elif r.get("quality") not in skrapp_client.USABLE:
            rec.update(result="not_valid", candidate=new, quality=r.get("quality"))
        elif new == old or new in dead:
            rec.update(result="same_or_dead", candidate=new)
        elif t["outreach_leads_v2"].find_one({"email": new}):
            rec.update(result="already_enrolled", candidate=new)
        else:
            camp = _campaign_for(t, new, lead.get("company_name") or row.get("company_name") or "",
                                 row.get("campaign_id"))
            if not camp:
                rec.update(result="no_campaign", candidate=new)
            else:
                if lead:
                    ea["leads_enriched"].update_one({"_id": lead["_id"]}, {
                        "$set": {"email": new, "email_source": "skrapp", "email_status": "Valid",
                                 "email_pattern_confidence": 0.9, "updated_at": now},
                        "$addToSet": {"previous_emails": old}})
                name = lead.get("name") or row.get("name") or f"{first} {last}".strip()
                t["outreach_leads_v2"].insert_one({
                    "lead_id": str(lead.get("_id") or row.get("lead_id") or ""), "campaign_id": camp["campaign_id"],
                    "email": new, "name": name, "first_name": first.title() if first else "",
                    "company_name": lead.get("company_name") or row.get("company_name") or "",
                    "title": lead.get("title") or row.get("title") or "",
                    "company_industry": lead.get("company_industry", ""),
                    "classification_basket": BASKET[camp["business"]],
                    "lead_service_type": SERVICE[camp["business"]], "personalization_level": "medium",
                    "workflow_status": "not_started", "current_step": 0, "next_send_at": now,
                    "enrolled_at": now, "created_at": now, "updated_at": now,
                    "email_source": "skrapp", "email_pattern_confidence": 0.9,
                    "sendable": True, "verification_status": "skrapp:valid", "verified_at": now,
                    "enrolled_by": "skrapp_refind", "replaces_bounced": old})
                rec.update(result="fresh_outreach", candidate=new, campaign=camp["business"])
        state.update_one({"_id": old}, {"$set": rec}, upsert=True)
        stats[rec["result"]] = stats.get(rec["result"], 0) + 1
    logger.info("[SkrappRefind] %s", stats)
    return stats


def import_lists(client=None, now: Optional[datetime] = None) -> Dict[str, Any]:
    from leads import skrapp_client
    from leads.canonical_ingestion import ingest_lead
    from leads.icp_check import known_dead
    client = client or _client()
    now = now or datetime.utcnow()
    t, ea = client["torpedo"], client["email_automation"]
    dead = known_dead(client)
    have = {e.lower() for e in ea["leads_enriched"].distinct("email") if e}
    have |= {e.lower() for e in t["outreach_leads_v2"].distinct("email") if e}
    stats: Dict[str, int] = {}
    for lead in skrapp_client.list_leads(client):
        email = (lead.get("email") or "").strip().lower()
        if not email or (lead.get("email_status") or "").lower() != "valid":
            stats["not_valid"] = stats.get("not_valid", 0) + 1
            continue
        if email in have or email in dead:
            stats["already_known"] = stats.get("already_known", 0) + 1
            continue
        li = lead.get("linkedin_url") or ""
        payload = {"email": email, "first_name": lead.get("first_n") or "", "last_name": lead.get("last_n") or "",
                   "name": lead.get("name") or "", "company": lead.get("company") or "",
                   "company_domain": lead.get("domain") or "", "title": lead.get("title") or "",
                   "linkedin_url": ("https://www.linkedin.com/" + li.lstrip("/")) if li and "linkedin.com" not in li else li,
                   "location": lead.get("location") or ""}
        res = ingest_lead(payload, "csv", f"skrapp_list:{lead.get('list_name') or lead.get('list_id')}")
        if not res.get("success") or res.get("action") == "skipped":
            stats["ingest_skipped"] = stats.get("ingest_skipped", 0) + 1
            continue
        have.add(email)
        ea["leads_enriched"].update_one({"email": email}, {"$set": {
            "email_source": "skrapp_list", "email_status": "Valid", "email_pattern_confidence": 0.9,
            "company_industry": lead.get("company_industry") or None, "updated_at": now}})
        # rows the normal enrollment created for it are fresh outreach: sendable
        t["outreach_leads_v2"].update_many({"email": email, "workflow_status": "not_started"}, {"$set": {
            "sendable": True, "verification_status": "skrapp_list:valid", "verified_at": now,
            "email_source": "skrapp_list"}})
        stats["imported"] = stats.get("imported", 0) + 1
    logger.info("[SkrappLists] %s", stats)
    return stats
