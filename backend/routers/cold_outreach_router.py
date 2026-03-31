"""
Cold Outreach Router
====================

Campaign management API for 3-business cold outreach system.

Baskets:
  A → Survey Fieldwork   (indira@surveyfieldwork.com)
  B → Cogentix Research  (meera@cogentixresearch.com)
  C → BIMwave            (susanta@bimwaveconsultants.com)
  D → Dual Fit           (all 3 businesses, score-ordered, 21-day gap between each)
  E → Nurture            (excluded — no outreach)

Collections used:
  outreach_campaigns_v2        — campaign definitions + step templates
  outreach_mailboxes           — SMTP mailbox records
  outreach_leads_v2            — enrolled leads + workflow state
  outreach_sends_v2            — per-send records (stats)
  outreach_bounce_suppression  — global bounce suppression list
  leads_enriched               — source of truth for leads to enroll
"""

import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, EmailStr
from pymongo import MongoClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cold-outreach", tags=["Cold Outreach"])

SEQUENCE_STEPS = [0, 3, 6, 11]   # Day offsets: Day 1, 4, 7, 12 (0-indexed)
DUAL_FIT_GAP_DAYS = 21           # Gap between sequences for Dual Fit leads
SEQUENCE_DURATION_DAYS = 12      # Last step offset → total sequence window

BASKET_BUSINESS = {
    "A": "sfw",
    "B": "cogentix",
    "C": "bimwave",
}

BUSINESS_LABEL = {
    "sfw": "Survey Fieldwork",
    "cogentix": "Cogentix Research",
    "bimwave": "BIMwave",
}

BUSINESS_BASKET = {v: k for k, v in BASKET_BUSINESS.items()}


# ── DB connection ─────────────────────────────────────────────────────────────

def get_db():
    uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017/"
    db_name = os.getenv("MONGO_DB_NAME") or "torpedo"
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return client[db_name]


# ── Request/response models ────────────────────────────────────────────────────

class StepTemplate(BaseModel):
    step_number: int          # 1–4
    day_offset: int           # 0, 3, 6, 11
    subject: str
    body_html: str
    body_text: str = ""


class CreateCampaignRequest(BaseModel):
    business: str             # "sfw" | "cogentix" | "bimwave"
    name: Optional[str] = None
    mailbox_ids: List[str] = []
    steps: List[StepTemplate] = []


class UpdateStepRequest(BaseModel):
    subject: str
    body_html: str
    body_text: str = ""


class AddMailboxRequest(BaseModel):
    business: str             # "sfw" | "cogentix" | "bimwave"
    email: str
    display_name: str
    smtp_host: str
    smtp_port: int = 587
    smtp_username: str
    smtp_password: str
    use_tls: bool = True
    daily_limit: int = 400
    hourly_limit: int = 60


class ManualSuppressionRequest(BaseModel):
    email: str
    reason: Optional[str] = "manual"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _oid(doc) -> str:
    return str(doc.get("_id", ""))


def _clean(doc: dict) -> dict:
    """Convert ObjectId → str for JSON serialisation."""
    doc["id"] = str(doc.pop("_id", ""))
    return doc


def _score_basket_for_lead(lead: dict, basket: str) -> float:
    """
    Return a rough affinity score (0–1) for a given basket using the lead's
    icp_tags and classification data already stored in leads_enriched.
    Used to order Dual Fit sequences.
    """
    tags = [t.lower() for t in (lead.get("icp_tags") or [])]
    basket_keywords = {
        "A": ["survey_fieldwork", "fieldwork", "data_services", "survey", "data"],
        "B": ["cogentix", "consumer_insights", "insights", "market_research"],
        "C": ["bimwave", "bim", "architecture", "construction", "aec"],
    }
    kws = basket_keywords.get(basket, [])
    hits = sum(1 for t in tags if any(k in t for k in kws))
    return hits / max(len(kws), 1)


# ══════════════════════════════════════════════════════════════════════════════
#  MAILBOX ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/mailboxes")
def list_mailboxes():
    db = get_db()
    mailboxes = list(db["outreach_mailboxes"].find({}, {"smtp_password": 0}))
    for m in mailboxes:
        m["id"] = str(m.pop("_id"))
    return {"mailboxes": mailboxes}


@router.post("/mailboxes", status_code=201)
def add_mailbox(req: AddMailboxRequest):
    db = get_db()
    if req.business not in BUSINESS_LABEL:
        raise HTTPException(400, f"Unknown business '{req.business}'. Use: sfw, cogentix, bimwave")

    existing = db["outreach_mailboxes"].find_one({"email_address": req.email})
    if existing:
        raise HTTPException(409, f"Mailbox {req.email} already exists")

    doc = {
        "mailbox_id": str(uuid.uuid4()),
        "business": req.business,
        "email_address": req.email,
        "display_name": req.display_name,
        "provider": "smtp",
        "smtp_host": req.smtp_host,
        "smtp_port": req.smtp_port,
        "smtp_username": req.smtp_username,
        "smtp_password": req.smtp_password,
        "use_tls": req.use_tls,
        "daily_limit": req.daily_limit,
        "hourly_limit": req.hourly_limit,
        "is_active": True,
        "health_status": "healthy",
        "daily_sent_count": 0,
        "hourly_sent_count": 0,
        "last_send_at": None,
        "created_at": datetime.utcnow(),
    }
    db["outreach_mailboxes"].insert_one(doc)
    doc["id"] = str(doc.pop("_id"))
    doc.pop("smtp_password", None)
    return {"mailbox": doc}


@router.delete("/mailboxes/{mailbox_id}")
def remove_mailbox(mailbox_id: str):
    db = get_db()
    res = db["outreach_mailboxes"].delete_one({"mailbox_id": mailbox_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Mailbox not found")
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
#  CAMPAIGN ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/campaigns")
def list_campaigns():
    db = get_db()
    campaigns = list(db["outreach_campaigns_v2"].find())
    # Attach live stats to each
    sends_col = db["outreach_sends_v2"]
    for c in campaigns:
        cid = c.get("campaign_id", "")
        c["id"] = str(c.pop("_id"))
        pipeline = [
            {"$match": {"campaign_id": cid}},
            {"$group": {
                "_id": None,
                "sent": {"$sum": 1},
                "opened": {"$sum": {"$cond": [{"$gt": ["$open_count", 0]}, 1, 0]}},
                "replied": {"$sum": {"$cond": [{"$eq": ["$reply_received", True]}, 1, 0]}},
                "bounced": {"$sum": {"$cond": [{"$eq": ["$status", "bounced"]}, 1, 0]}},
            }}
        ]
        agg = list(sends_col.aggregate(pipeline))
        if agg:
            c["stats"] = agg[0]
            c["stats"].pop("_id", None)
        else:
            c["stats"] = {"sent": 0, "opened": 0, "replied": 0, "bounced": 0}

        enrolled = db["outreach_leads_v2"].count_documents({"campaign_id": cid})
        c["stats"]["enrolled"] = enrolled

    return {"campaigns": campaigns}


@router.post("/campaigns", status_code=201)
def create_campaign(req: CreateCampaignRequest):
    db = get_db()
    if req.business not in BUSINESS_LABEL:
        raise HTTPException(400, f"Unknown business '{req.business}'. Use: sfw, cogentix, bimwave")

    basket = BUSINESS_BASKET[req.business]
    campaign_id = str(uuid.uuid4())
    default_steps = []
    for i, day_offset in enumerate(SEQUENCE_STEPS):
        default_steps.append({
            "step_number": i + 1,
            "day_offset": day_offset,
            "subject": "",
            "body_html": "",
            "body_text": "",
        })

    # Merge provided steps
    steps_map = {s.step_number: s.dict() for s in req.steps}
    final_steps = []
    for ds in default_steps:
        if ds["step_number"] in steps_map:
            final_steps.append(steps_map[ds["step_number"]])
        else:
            final_steps.append(ds)

    doc = {
        "campaign_id": campaign_id,
        "business": req.business,
        "business_label": BUSINESS_LABEL[req.business],
        "basket": basket,
        "name": req.name or f"{BUSINESS_LABEL[req.business]} Cold Outreach",
        "mailbox_ids": req.mailbox_ids,
        "steps": final_steps,
        "is_active": False,
        "tags": [req.business],
        "campaign_type": "cold_outreach",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    db["outreach_campaigns_v2"].insert_one(doc)
    doc["id"] = str(doc.pop("_id"))
    return {"campaign": doc}


@router.put("/campaigns/{campaign_id}/steps/{step_number}")
def update_step_template(campaign_id: str, step_number: int, req: UpdateStepRequest):
    db = get_db()
    campaign = db["outreach_campaigns_v2"].find_one({"campaign_id": campaign_id})
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    steps = campaign.get("steps", [])
    found = False
    for s in steps:
        if s["step_number"] == step_number:
            s["subject"] = req.subject
            s["body_html"] = req.body_html
            s["body_text"] = req.body_text
            found = True
            break

    if not found:
        raise HTTPException(404, f"Step {step_number} not found in campaign")

    db["outreach_campaigns_v2"].update_one(
        {"campaign_id": campaign_id},
        {"$set": {"steps": steps, "updated_at": datetime.utcnow()}},
    )
    return {"ok": True, "steps": steps}


@router.post("/campaigns/{campaign_id}/launch")
def launch_campaign(campaign_id: str, background_tasks: BackgroundTasks):
    db = get_db()
    campaign = db["outreach_campaigns_v2"].find_one({"campaign_id": campaign_id})
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    db["outreach_campaigns_v2"].update_one(
        {"campaign_id": campaign_id},
        {"$set": {"is_active": True, "launched_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )

    # Enroll leads in background so the response is fast
    background_tasks.add_task(_enroll_basket_leads, campaign_id, campaign["basket"])

    return {"ok": True, "message": "Campaign launched. Enrollment running in background."}


@router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str):
    db = get_db()
    res = db["outreach_campaigns_v2"].update_one(
        {"campaign_id": campaign_id},
        {"$set": {"is_active": False, "paused_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Campaign not found")
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/resume")
def resume_campaign(campaign_id: str):
    db = get_db()
    res = db["outreach_campaigns_v2"].update_one(
        {"campaign_id": campaign_id},
        {"$set": {"is_active": True, "resumed_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Campaign not found")
    return {"ok": True}


@router.get("/campaigns/{campaign_id}/stats")
def campaign_stats(campaign_id: str):
    db = get_db()
    campaign = db["outreach_campaigns_v2"].find_one({"campaign_id": campaign_id})
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    sends = db["outreach_sends_v2"]
    enrolled = db["outreach_leads_v2"].count_documents({"campaign_id": campaign_id})

    # Overall stats
    overall_pipeline = [
        {"$match": {"campaign_id": campaign_id}},
        {"$group": {
            "_id": None,
            "total_sent": {"$sum": 1},
            "total_opened": {"$sum": {"$cond": [{"$gt": ["$open_count", 0]}, 1, 0]}},
            "total_replied": {"$sum": {"$cond": [{"$eq": ["$reply_received", True]}, 1, 0]}},
            "total_bounced": {"$sum": {"$cond": [{"$eq": ["$status", "bounced"]}, 1, 0]}},
            "total_unsubscribed": {"$sum": {"$cond": [{"$eq": ["$unsubscribed", True]}, 1, 0]}},
        }},
    ]
    overall = list(sends.aggregate(overall_pipeline))
    overall_stats = overall[0] if overall else {
        "total_sent": 0, "total_opened": 0, "total_replied": 0,
        "total_bounced": 0, "total_unsubscribed": 0,
    }
    overall_stats.pop("_id", None)
    overall_stats["enrolled"] = enrolled

    # Per-step breakdown
    step_pipeline = [
        {"$match": {"campaign_id": campaign_id}},
        {"$group": {
            "_id": "$workflow_step",
            "sent": {"$sum": 1},
            "opened": {"$sum": {"$cond": [{"$gt": ["$open_count", 0]}, 1, 0]}},
            "replied": {"$sum": {"$cond": [{"$eq": ["$reply_received", True]}, 1, 0]}},
            "bounced": {"$sum": {"$cond": [{"$eq": ["$status", "bounced"]}, 1, 0]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    step_stats = []
    for row in sends.aggregate(step_pipeline):
        step_num = row.pop("_id")
        day_offset = SEQUENCE_STEPS[step_num] if step_num < len(SEQUENCE_STEPS) else step_num
        row["step_number"] = step_num + 1
        row["day_offset"] = day_offset
        row["open_rate"] = round(row["opened"] / max(row["sent"], 1) * 100, 1)
        row["reply_rate"] = round(row["replied"] / max(row["sent"], 1) * 100, 1)
        step_stats.append(row)

    # Rates
    sent = overall_stats.get("total_sent", 0)
    overall_stats["open_rate"] = round(overall_stats.get("total_opened", 0) / max(sent, 1) * 100, 1)
    overall_stats["reply_rate"] = round(overall_stats.get("total_replied", 0) / max(sent, 1) * 100, 1)
    overall_stats["bounce_rate"] = round(overall_stats.get("total_bounced", 0) / max(sent, 1) * 100, 1)

    return {"campaign_id": campaign_id, "overall": overall_stats, "by_step": step_stats}


# ══════════════════════════════════════════════════════════════════════════════
#  ENROLLMENT LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def _enroll_basket_leads(campaign_id: str, basket: str):
    """
    Background task: pull leads from leads_enriched matching the basket,
    filter out bounced/already-enrolled, and create outreach_leads_v2 records.
    For Dual Fit (basket D), all 3 business sequences are queued with staggered starts.
    """
    try:
        db = get_db()
        suppression = db["outreach_bounce_suppression"]
        outreach_leads = db["outreach_leads_v2"]
        leads_enriched = db["leads_enriched"]
        campaigns_col = db["outreach_campaigns_v2"]

        # Get all suppressed emails in a set for fast lookup
        suppressed_emails = {
            doc["email"] for doc in suppression.find({}, {"email": 1, "_id": 0})
        }

        if basket == "D":
            # Dual Fit: enroll into all 3 business campaigns in score order
            _enroll_dual_fit_leads(db, suppressed_emails)
            return

        # Regular basket: single campaign enrollment
        campaign = campaigns_col.find_one({"campaign_id": campaign_id})
        if not campaign:
            logger.error(f"Campaign {campaign_id} not found during enrollment")
            return

        # Already enrolled emails for this campaign
        enrolled_emails = {
            doc["email"] for doc in outreach_leads.find(
                {"campaign_id": campaign_id}, {"email": 1, "_id": 0}
            )
        }

        query = {"classification_basket": basket, "email": {"$exists": True, "$ne": ""}}
        cursor = leads_enriched.find(query)

        enrolled_count = 0
        skipped_suppressed = 0
        skipped_duplicate = 0

        for lead in cursor:
            email = (lead.get("email") or "").lower().strip()
            if not email:
                continue
            if email in suppressed_emails:
                skipped_suppressed += 1
                continue
            if email in enrolled_emails:
                skipped_duplicate += 1
                continue

            lead_id = str(lead.get("_id"))
            now = datetime.utcnow()
            outreach_lead_doc = {
                "lead_id": lead_id,
                "campaign_id": campaign_id,
                "email": email,
                "name": lead.get("name", ""),
                "first_name": lead.get("first_name") or (lead.get("name") or "").split()[0],
                "company_name": lead.get("company_name", ""),
                "title": lead.get("title", ""),
                "company_industry": lead.get("company_industry", ""),
                "seniority_level": lead.get("seniority_level", ""),
                "classification_basket": basket,
                "lead_service_type": {
                    "A": "data_services",
                    "B": "consumer_insights",
                    "C": "bimwave",
                }.get(basket, "data_services"),
                "personalization_level": "medium",
                "workflow_status": "not_started",
                "current_step": 0,
                "next_send_at": now,
                "enrolled_at": now,
                "created_at": now,
                "updated_at": now,
            }
            try:
                outreach_leads.insert_one(outreach_lead_doc)
                enrolled_emails.add(email)
                enrolled_count += 1
            except Exception as e:
                logger.warning(f"Could not enroll {email}: {e}")

        logger.info(
            f"Enrollment complete for campaign {campaign_id} (basket {basket}): "
            f"enrolled={enrolled_count}, skipped_suppressed={skipped_suppressed}, "
            f"skipped_duplicate={skipped_duplicate}"
        )
    except Exception as e:
        logger.error(f"Enrollment background task failed for campaign {campaign_id}: {e}", exc_info=True)


def _enroll_dual_fit_leads(db, suppressed_emails: set):
    """
    Enroll Dual Fit (basket D) leads into all 3 business campaigns,
    with staggered start dates ordered by ICP affinity score.
    Gap between sequences: SEQUENCE_DURATION_DAYS + DUAL_FIT_GAP_DAYS
    """
    try:
        campaigns_col = db["outreach_campaigns_v2"]
        outreach_leads = db["outreach_leads_v2"]
        leads_enriched = db["leads_enriched"]

        # Find active campaigns for all 3 businesses
        business_campaigns: Dict[str, Any] = {}
        for biz in ["sfw", "cogentix", "bimwave"]:
            c = campaigns_col.find_one({"business": biz, "is_active": True})
            if c:
                business_campaigns[biz] = c

        if not business_campaigns:
            logger.warning("No active campaigns found for any business — skipping Dual Fit enrollment")
            return

        cursor = leads_enriched.find(
            {"classification_basket": "D", "email": {"$exists": True, "$ne": ""}}
        )

        enrolled_count = 0
        now = datetime.utcnow()
        sequence_window = SEQUENCE_DURATION_DAYS + DUAL_FIT_GAP_DAYS  # days before next sequence starts

        for lead in cursor:
            email = (lead.get("email") or "").lower().strip()
            if not email or email in suppressed_emails:
                continue

            lead_id = str(lead.get("_id"))

            # Score lead against each basket to determine send order
            scored = []
            for biz, campaign in business_campaigns.items():
                basket = BUSINESS_BASKET.get(biz, "A")
                score = _score_basket_for_lead(lead, basket)
                scored.append((score, biz, campaign))

            # Sort descending: highest affinity goes first
            scored.sort(key=lambda x: x[0], reverse=True)

            dual_fit_queue = []
            for seq_index, (score, biz, campaign) in enumerate(scored):
                cid = campaign["campaign_id"]

                # Check if already enrolled in this campaign
                existing = outreach_leads.find_one({"lead_id": lead_id, "campaign_id": cid})
                if existing:
                    continue

                start_date = now + timedelta(days=seq_index * sequence_window)
                outreach_lead_doc = {
                    "lead_id": lead_id,
                    "campaign_id": cid,
                    "email": email,
                    "name": lead.get("name", ""),
                    "first_name": lead.get("first_name") or (lead.get("name") or "").split()[0],
                    "company_name": lead.get("company_name", ""),
                    "title": lead.get("title", ""),
                    "company_industry": lead.get("company_industry", ""),
                    "seniority_level": lead.get("seniority_level", ""),
                    "classification_basket": "D",
                    "dual_fit": True,
                    "dual_fit_sequence_index": seq_index + 1,
                    "lead_service_type": {"sfw": "data_services", "cogentix": "consumer_insights", "bimwave": "bimwave"}.get(biz),
                    "personalization_level": "medium",
                    "workflow_status": "not_started" if seq_index == 0 else "pending_scheduled",
                    "current_step": 0,
                    "next_send_at": start_date,
                    "enrolled_at": now,
                    "created_at": now,
                    "updated_at": now,
                }
                try:
                    outreach_leads.insert_one(outreach_lead_doc)
                    dual_fit_queue.append({
                        "campaign_id": cid,
                        "business": biz,
                        "sequence_index": seq_index + 1,
                        "scheduled_start": start_date,
                    })
                    enrolled_count += 1
                except Exception as e:
                    logger.warning(f"Could not enroll dual-fit lead {email} into {biz}: {e}")

        logger.info(f"Dual Fit enrollment complete: {enrolled_count} lead-campaign records created")
    except Exception as e:
        logger.error(f"Dual Fit enrollment failed: {e}", exc_info=True)


# ══════════════════════════════════════════════════════════════════════════════
#  SUPPRESSION LIST ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/suppression")
def list_suppression(page: int = 1, limit: int = 100, search: str = ""):
    db = get_db()
    query: Dict[str, Any] = {}
    if search:
        query["email"] = {"$regex": search, "$options": "i"}

    total = db["outreach_bounce_suppression"].count_documents(query)
    docs = list(
        db["outreach_bounce_suppression"]
        .find(query)
        .sort("created_at", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {"total": total, "page": page, "suppressed": docs}


@router.get("/suppression/stats")
def suppression_stats():
    db = get_db()
    total = db["outreach_bounce_suppression"].count_documents({})
    return {"total_suppressed": total}


@router.post("/suppression/manual", status_code=201)
def manual_suppress(req: ManualSuppressionRequest):
    db = get_db()
    email = req.email.lower().strip()
    now = datetime.utcnow()
    try:
        db["outreach_bounce_suppression"].update_one(
            {"email": email},
            {"$setOnInsert": {
                "email": email,
                "bounced_at": now,
                "reason": req.reason,
                "manual": True,
                "created_at": now,
            }},
            upsert=True,
        )
    except Exception as e:
        raise HTTPException(500, f"Could not add suppression: {e}")

    # Also mark in leads_enriched
    db["leads_enriched"].update_many(
        {"email": email},
        {"$set": {"email_status": "bounced", "bounce_suppressed": True, "bounced_at": now}},
    )
    return {"ok": True, "email": email}


@router.delete("/suppression/{email}")
def remove_suppression(email: str):
    """Remove an email from suppression list (use only if added by mistake)."""
    db = get_db()
    email = email.lower().strip()
    res = db["outreach_bounce_suppression"].delete_one({"email": email})
    if res.deleted_count == 0:
        raise HTTPException(404, "Email not found in suppression list")

    # Unmark in leads_enriched
    db["leads_enriched"].update_many(
        {"email": email},
        {"$unset": {"bounce_suppressed": ""}, "$set": {"email_status": "unknown"}},
    )
    return {"ok": True, "email": email}


# ══════════════════════════════════════════════════════════════════════════════
#  DUAL FIT — manual trigger for enrollment
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/dual-fit/enroll")
def enroll_dual_fit(background_tasks: BackgroundTasks):
    """Manually trigger Dual Fit enrollment across all active campaigns."""
    db = get_db()
    suppressed = {
        doc["email"] for doc in db["outreach_bounce_suppression"].find({}, {"email": 1, "_id": 0})
    }
    background_tasks.add_task(_enroll_dual_fit_leads, db, suppressed)
    return {"ok": True, "message": "Dual Fit enrollment started in background"}
