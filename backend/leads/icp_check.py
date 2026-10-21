"""
Is this PERSON in the right campaign? Checked by the local model after the
company's industry is known (leads/company_fit.py), and nobody is mailed until
the two agree (owner, 2026-10-21: "get the industry of all the companies using
google search, then check if the icp is correct using qwen. if everything is
aligned and correct then only start sending mails. if in the past there were
errors then you need to put the contact in the correct bucket and resend it").

Per person (email address), torpedo.contact_icp_checks:
    expected   the campaign the company's type gives (sfw/cogentix/bimwave/none)
    qwen       the campaign the model picks from the company's own description
               and the person's title
    aligned    expected == qwen and expected != none

Then, for an aligned person (reconcile):
    - a live row in another campaign is retired ("moved_to_correct_bucket")
    - a row in the right campaign that was paused (duplicate-brand pause, or
      retired by the company gate) is resumed
    - no row in the right campaign -> a new one, from step 1. This is the
      "resend" for people who got the wrong campaign's mail before.
A person whose company fits no campaign has live rows retired. A person the
model disagrees on is held ("icp_review") for a person to look at -- never
mailed on a guess. A model outage is retried, never recorded as a verdict.

Never resent: anyone who replied, bounced, is suppressed, or whose address was
blocked for provenance/bounce risk, plus the rows the unauthenticated-endpoint
scanner enrolled (paused_unauthorized_enroll).

The send loop asks gate() before every step.
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from leads import company_fit as cf

logger = logging.getLogger(__name__)

CHECKS = "contact_icp_checks"
BUSINESS_FOR_TYPE = {v: k for k, v in cf.TYPE_FOR_BUSINESS.items()}  # mr_agency -> sfw ...
ACTIVE = cf.ACTIVE_STATUSES
BLOCKING_STATUSES = {"replied", "bounced", "suppressed", "needs_human_intervention",
                     "paused_unauthorized_enroll", "ai_rejected_paused", "skipped_unverified_provenance",
                     "skipped_high_bounce_risk", "skipped_gate", "error"}
RESUMABLE = {"paused_duplicate_brand", "skipped_icp_mismatch", "moved_to_correct_bucket", "icp_review"}
BASKET = {"sfw": "A", "cogentix": "B", "bimwave": "C"}
SERVICE = {"sfw": "data_services", "cogentix": "consumer_insights", "bimwave": "bimwave"}

_SCHEMA = {"type": "object", "additionalProperties": False,
           "properties": {"campaign": {"type": "string", "enum": ["sfw", "cogentix", "bimwave", "none"]},
                          "reason": {"type": "string", "maxLength": 160}},
           "required": ["campaign", "reason"]}

_ASK = """We run three businesses and must email each person about only ONE of them:
sfw = Survey Fieldwork: survey fieldwork, panel sample and data collection, sold to MARKET RESEARCH AGENCIES
cogentix = Cogentix Research: consumer and brand research studies, sold to BRANDS (consumer products, retail, banks, telecom, pharma, media)
bimwave = BIMwave: BIM modelling and CAD drafting outsourcing, sold to ARCHITECTURE, ENGINEERING and CONSTRUCTION firms
none = this person should get none of them

Company: {company}
What the company says about itself: {about}
Person's job title: {title}

Which one business fits this person's company and role?"""


def _tdb(client=None):
    if client is None:
        from database import get_client
        client = get_client()
    return client[os.getenv("MONGO_DB_NAME") or "torpedo"]


# ---------------------------------------------------------------------------
# the model's opinion on one person
# ---------------------------------------------------------------------------
def ask_model(company: str, about: str, title: str) -> Optional[Dict[str, str]]:
    """{'campaign', 'reason'} or None when the model is unavailable."""
    from leads.local_llm_gate import queue_wait
    from leads.local_slm_client import LocalSLMError, chat_json
    try:
        with queue_wait(120, priority="bulk"):
            got = chat_json(system="You decide which business should contact a person. Reply only with JSON.",
                            user=_ASK.format(company=company or "(unknown)", about=(about or "(none)")[:700],
                                             title=title or "(unknown)"),
                            max_tokens=80, json_schema=_SCHEMA, timeout=120)
    except (LocalSLMError, Exception) as e:
        logger.info("[ICPCheck] model unavailable: %s", e)
        return None
    if got.get("campaign") not in ("sfw", "cogentix", "bimwave", "none"):
        return None
    return {"campaign": got["campaign"], "reason": str(got.get("reason") or "")[:160]}


def company_about(doc: Dict[str, Any]) -> str:
    li = doc.get("linkedin_text") or ""
    site = (doc.get("website_text") or "").replace(" || ", " | ")
    return " | ".join(t for t in (li, site, doc.get("evidence") or "") if t)


# ---------------------------------------------------------------------------
# the send loop's question
# ---------------------------------------------------------------------------
def gate(email: str, business: str, company: str, title: str, client=None) -> Tuple[str, str]:
    """-> ('send' | 'hold' | 'stop', why). Every step, every campaign."""
    verdict, why = cf.check(business, company, email.split("@")[-1], title, client=client)
    if verdict in ("mismatch", "excluded"):
        return "stop", why
    if verdict == "unknown":
        return "hold", why
    rec = _tdb(client)[CHECKS].find_one({"_id": email.lower().strip()})
    if not rec or rec.get("company_type") != cf.TYPE_FOR_BUSINESS.get(business):
        return "hold", "waiting for the AI check of this person's campaign"
    if not rec.get("aligned"):
        return "stop", f"AI check disagrees: picked {rec.get('qwen')} ({rec.get('reason', '')})"
    return "send", "company and AI check agree"


# ---------------------------------------------------------------------------
# the job
# ---------------------------------------------------------------------------
def _people(tdb) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in tdb["outreach_leads_v2"].find({"email": {"$nin": [None, ""]}}, {
            "email": 1, "campaign_id": 1, "workflow_status": 1, "current_step": 1, "reply_received": 1,
            "company_name": 1, "title": 1, "updated_at": 1}):
        out.setdefault(r["email"].lower().strip(), []).append(r)
    return out


def _company_doc(types: Dict[str, Dict[str, Any]], email: str, company: str) -> Optional[Dict[str, Any]]:
    dom = email.split("@")[-1]
    dom = "" if dom in cf._WEBMAIL else dom
    for key in (cf.company_key(company, dom), cf.company_key(company)):
        if key and key in types:
            return types[key]
    st = cf.seed_type(company, dom)
    return {"type": st, "source": "seed"} if st else None


def plan(client=None) -> List[Dict[str, Any]]:
    """Everyone who needs a decision: live rows, or mail from the wrong
    campaign in the past. Live first, then the most recently mailed."""
    tdb = _tdb(client)
    ea = tdb.client["email_automation"]
    camps = {c["campaign_id"]: c.get("business") for c in tdb["outreach_campaigns_v2"].find(
        {}, {"campaign_id": 1, "business": 1})}
    types = {d["_id"]: d for d in ea[cf.COLLECTION].find({"type": {"$in": list(cf.TYPES)}})}
    rels = {r["key"].strip().lower() for r in ea["party_relationships"].find(
        {"relationship": {"$in": list(cf.EXCLUDED_RELATIONSHIPS)}, "key": {"$type": "string"}}, {"key": 1})}
    suppressed = {d["email"] for d in tdb["outreach_bounce_suppression"].find({}, {"email": 1})}
    checked = {d["_id"]: d for d in tdb[CHECKS].find({}, {"company_type": 1, "qwen": 1, "reconciled": 1})}
    todo = []
    for email, rows in _people(tdb).items():
        if email in suppressed or any(r.get("reply_received") or r.get("workflow_status") in BLOCKING_STATUSES
                                      for r in rows):
            blocked = True
        else:
            blocked = False
        company = next((r.get("company_name") for r in rows if r.get("company_name")), "") or ""
        title = next((r.get("title") for r in rows if r.get("title")), "") or ""
        doc = _company_doc(types, email, company)
        if not doc:
            continue  # company not typed yet; company_fit works on it
        dom = email.split("@")[-1]
        excluded = dom in rels or company.strip().lower() in rels
        expected = "none" if excluded else BUSINESS_FOR_TYPE.get(doc["type"], "none")
        live = [r for r in rows if r.get("workflow_status") in ACTIVE]
        # in the wrong campaign: mailed by it, or taken out of it by the gate
        wrong_mail = [r for r in rows if camps.get(r.get("campaign_id")) not in (expected, None)
                      and (int(r.get("current_step") or 0) > 0
                           or r.get("workflow_status") in ("skipped_icp_mismatch", "moved_to_correct_bucket"))]
        right = [r for r in rows if camps.get(r.get("campaign_id")) == expected]
        right_done = any(r.get("workflow_status") == "completed" or r.get("workflow_status") in ACTIVE
                         for r in right)
        # live rows can't send before a check; past wrong mail gets a resend
        needs = bool(live) or (not blocked and expected != "none" and not right_done and bool(wrong_mail))
        if not needs:
            continue
        prev = checked.get(email)
        if prev and prev.get("company_type") == doc["type"] and prev.get("reconciled"):
            continue
        last = max((r["updated_at"] for r in rows if isinstance(r.get("updated_at"), datetime)),
                   default=datetime.min)
        todo.append({"email": email, "rows": rows, "company": company, "title": title, "doc": doc,
                     "expected": expected, "blocked": blocked, "live": bool(live), "last": last,
                     "prev": prev})
    todo.sort(key=lambda p: (not p["live"], -(p["last"] - datetime.min).total_seconds()))
    return todo


def _campaign_for(tdb, business: str) -> Optional[Dict[str, Any]]:
    return tdb["outreach_campaigns_v2"].find_one({"business": business, "is_active": True})


def reconcile(tdb, p: Dict[str, Any], rec: Dict[str, Any], now: datetime, apply: bool = True) -> str:
    """Put the person's rows where the check says. -> what was done."""
    camps = {c["campaign_id"]: c.get("business") for c in tdb["outreach_campaigns_v2"].find(
        {}, {"campaign_id": 1, "business": 1})}
    ol = tdb["outreach_leads_v2"]
    rows = p["rows"]
    expected = p["expected"]

    def _retire(r, status, why):
        if apply:
            ol.update_one({"_id": r["_id"]}, {"$set": {
                "pre_icp_status": r.get("workflow_status"), "workflow_status": status,
                "last_send_error": why[:300], "updated_at": now}})

    if expected == "none":
        for r in rows:
            if r.get("workflow_status") in ACTIVE:
                _retire(r, "skipped_icp_mismatch", "company fits no campaign")
        return "retired_no_campaign"
    if not rec.get("aligned"):
        for r in rows:
            if r.get("workflow_status") in ACTIVE:
                _retire(r, "icp_review", f"AI picked {rec.get('qwen')}, company says {expected}")
        return "held_for_review"
    moved = 0
    for r in rows:
        if r.get("workflow_status") in ACTIVE and camps.get(r.get("campaign_id")) != expected:
            _retire(r, "moved_to_correct_bucket", f"company and AI say {expected}")
            moved += 1
    right = [r for r in rows if camps.get(r.get("campaign_id")) == expected]
    if any(r.get("workflow_status") in ACTIVE or r.get("workflow_status") == "completed" for r in right):
        return "moved" if moved else "already_right"
    if p["blocked"]:
        return "blocked_no_resend"
    resumable = [r for r in right if r.get("workflow_status") in RESUMABLE]
    if resumable:
        r = resumable[0]
        step = int(r.get("current_step") or 0)
        if apply:
            ol.update_one({"_id": r["_id"]}, {"$set": {
                "pre_icp_status": r.get("workflow_status"),
                "workflow_status": "in_sequence" if step else "not_started",
                "next_send_at": now, "updated_at": now, "icp_resumed_at": now}})
        return "resumed"
    camp = _campaign_for(tdb, expected)
    if not camp:
        return "no_active_campaign"
    if apply:
        src = rows[0]
        lead = tdb.client["email_automation"]["leads_enriched"].find_one(
            {"email": p["email"]}, {"name": 1, "first_name": 1, "company_name": 1, "title": 1,
                                   "company_industry": 1, "seniority_level": 1, "email_source": 1,
                                   "email_pattern_confidence": 1}) or {}
        name = lead.get("name") or ""
        ol.insert_one({
            "lead_id": str(lead.get("_id") or src.get("lead_id") or ""),
            "campaign_id": camp["campaign_id"], "email": p["email"], "name": name,
            "first_name": lead.get("first_name") or ((name.split() or [""])[0]),
            "company_name": lead.get("company_name") or p["company"], "title": lead.get("title") or p["title"],
            "company_industry": lead.get("company_industry", ""), "seniority_level": lead.get("seniority_level", ""),
            "classification_basket": BASKET[expected], "lead_service_type": SERVICE[expected],
            "personalization_level": "medium", "workflow_status": "not_started", "current_step": 0,
            "next_send_at": now, "enrolled_at": now, "created_at": now, "updated_at": now,
            "email_source": lead.get("email_source"),
            "email_pattern_confidence": lead.get("email_pattern_confidence"),
            "enrolled_by": "icp_reroute", "rerouted_from": [str(r["_id"]) for r in rows]})
    return "resend_new_row"


def run(client=None, limit: int = 4, apply: bool = True, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Check up to `limit` people with the model and put them in place."""
    tdb = _tdb(client)
    now = now or datetime.utcnow()
    stats: Dict[str, int] = {}
    calls = 0
    for p in plan(client):
        doc = p["doc"]
        prev = p["prev"]
        if p["expected"] == "none":
            rec = {"expected": "none", "qwen": None, "aligned": False}
        elif prev and prev.get("company_type") == doc["type"] and prev.get("qwen"):
            rec = {"qwen": prev["qwen"], "aligned": prev["qwen"] == p["expected"]}
        else:
            if calls >= limit:
                break
            calls += 1
            got = ask_model(p["company"], company_about(doc), p["title"])
            if got is None:
                stats["model_unavailable"] = stats.get("model_unavailable", 0) + 1
                if stats["model_unavailable"] >= 2:
                    break
                continue
            rec = {"qwen": got["campaign"], "reason": got["reason"], "aligned": got["campaign"] == p["expected"]}
        rec.update({"expected": p["expected"], "company_type": doc["type"], "company": p["company"],
                    "title": p["title"], "at": now})
        done = reconcile(tdb, p, rec, now, apply=apply)
        stats[done] = stats.get(done, 0) + 1
        if apply:
            tdb[CHECKS].update_one({"_id": p["email"]}, {"$set": {**rec, "reconciled": done}}, upsert=True)
    logger.info("[ICPCheck] %s", stats)
    return stats
