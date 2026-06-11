"""
Unified Leads Router
Single leads collection with stage-based pipeline, inbound webhook,
Google Search prospecting, draft management, and stage state machine.

Steps covered: 4, 6, 11 (backend), 14, 15.
"""

import os
import re
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel
from pymongo import MongoClient, DESCENDING
from bson import ObjectId
from dotenv import load_dotenv

from .models import (
    LeadSource, LeadStage, EmailStatus, LeadTrack,
    LeadCreate, LeadUpdate, StageTransition,
    InboundLeadPayload, ProspectRequest,
    DraftApproval, DraftRegenerate,
    ICPSegmentCreate, LeadICPUpdate, BulkICPTag,
)

load_dotenv()
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leads", tags=["Sales Leads"])

# ── MongoDB ──
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
_client = MongoClient(MONGO_URI)
_db = _client["email_automation"]
leads_col = _db["leads"]
rfqs_col = _db["rfqs"]
contacts_col = _db["contacts"]
events_col = _db["email_events"]
icp_segments_col = _db["icp_segments"]

# Finance DB for post-won webhook
FINANCE_WEBHOOK_URL = os.getenv("FINANCE_WEBHOOK_URL", "")

# ── Helpers ──
def _serialize(doc):
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    if "rfq_id" in doc and doc["rfq_id"]:
        doc["rfq_id"] = str(doc["rfq_id"])
    return doc


def _extract_domain(email: str) -> str:
    """Extract domain from email address."""
    if "@" in email:
        return email.split("@")[1].lower().strip()
    return ""


# ══════════════════════════════════════════════
#  STAGE TRANSITION STATE MACHINE  (Step 14)
# ══════════════════════════════════════════════

ALLOWED_TRANSITIONS: Dict[str, List[str]] = {
    "new":                 ["email_construction", "verified"],
    "email_construction":  ["verified", "new"],
    "verified":            ["enriched"],
    "enriched":            ["outreach_sent"],
    "outreach_sent":       ["replied", "bounced", "enriched"],
    "replied":             ["discovery", "lost"],
    "discovery":           ["rfq", "lost"],
    "rfq":                 ["negotiation", "lost"],
    "negotiation":         ["won", "lost"],
    "won":                 [],
    "lost":                [],
}


def _handle_won(lead_id: str):
    """
    Post-won trigger (Step 15). Called automatically on stage → won.
    1. Create Contact record
    2. Notify Finance module (webhook)
    3. Update linked RFQ
    """
    lead = leads_col.find_one({"_id": ObjectId(lead_id)})
    if not lead:
        logger.error(f"handle_won: lead {lead_id} not found")
        return

    now = datetime.utcnow()

    # Action 1 — Create Contact record
    contact_doc = {
        "source": "won_deal",
        "linked_lead_id": lead_id,
        "name": lead.get("name", ""),
        "email": lead.get("email", ""),
        "company": lead.get("company", ""),
        "domain": lead.get("domain", ""),
        "rfq_id": str(lead["rfq_id"]) if lead.get("rfq_id") else None,
        "created_at": now,
    }
    contacts_col.insert_one(contact_doc)
    logger.info(f"Contact created for won lead {lead_id}")

    # Action 3 — Update RFQ
    if lead.get("rfq_id"):
        rfqs_col.update_one(
            {"_id": ObjectId(lead["rfq_id"]) if isinstance(lead["rfq_id"], str) else lead["rfq_id"]},
            {"$set": {"status": "won", "won_at": now}},
        )
        logger.info(f"RFQ {lead['rfq_id']} marked won")

    # Action 2 — Notify Finance (best-effort)
    if FINANCE_WEBHOOK_URL:
        import httpx
        rfq_doc = None
        if lead.get("rfq_id"):
            rfq_doc = rfqs_col.find_one({"_id": ObjectId(lead["rfq_id"]) if isinstance(lead["rfq_id"], str) else lead["rfq_id"]})

        deal_value = 0
        currency = "USD"
        if rfq_doc and rfq_doc.get("versions"):
            latest = rfq_doc["versions"][-1]
            deal_value = latest.get("amount", 0)
            currency = latest.get("currency", "USD")

        payload = {
            "contact_name": lead.get("name", ""),
            "company": lead.get("company", ""),
            "email": lead.get("email", ""),
            "deal_value": deal_value,
            "currency": currency,
            "won_at": now.isoformat(),
            "lead_id": lead_id,
            "rfq_id": str(lead["rfq_id"]) if lead.get("rfq_id") else None,
        }
        try:
            resp = httpx.post(
                f"{FINANCE_WEBHOOK_URL}/api/deals/won",
                json=payload,
                timeout=10,
            )
            logger.info(f"Finance webhook response: {resp.status_code}")
        except Exception as e:
            logger.error(f"Finance webhook failed for lead {lead_id}: {e}")


# ══════════════════════════════════════════════
#  CRUD ENDPOINTS
# ══════════════════════════════════════════════

@router.get("")
async def list_leads(
    stage: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    track: Optional[str] = Query(None),
    archived: bool = Query(False),
    search: Optional[str] = Query(None),
    draft_status: Optional[str] = Query(None),
    # ── Classification filters ──────────────────────────────────────────
    seniority_level: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    persona: Optional[str] = Query(None),
    persona_label: Optional[str] = Query(None),
    company_size: Optional[str] = Query(None),
    title: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    fit_tier: Optional[int] = Query(None),
    basket: Optional[str] = Query(None),
    icp_tag: Optional[str] = Query(None),
    # ── Pagination ─────────────────────────────────────────────────────
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """List leads with filters, pagination, and sorting."""
    query: Dict[str, Any] = {"archived": archived}
    if stage:
        query["stage"] = stage
    if source:
        query["source"] = source
    if track:
        query["track"] = track
    if draft_status:
        query["email_draft.status"] = draft_status
    # Classification / enrichment field filters
    if seniority_level:
        query["seniority_level"] = {"$regex": seniority_level, "$options": "i"}
    if department:
        query["department"] = {"$regex": department, "$options": "i"}
    if persona:
        query["$or"] = query.get("$or", []) + [
            {"persona": {"$regex": persona, "$options": "i"}},
            {"buying_role": {"$regex": persona, "$options": "i"}},
        ]
    if persona_label:
        query["persona_label"] = {"$regex": persona_label, "$options": "i"}
    if company_size:
        query["$or"] = query.get("$or", []) + [
            {"company_employee_count_range": {"$regex": company_size, "$options": "i"}},
            {"company_size": {"$regex": company_size, "$options": "i"}},
        ]
    if title:
        query["title"] = {"$regex": title, "$options": "i"}
    if location:
        query["$or"] = query.get("$or", []) + [
            {"location": {"$regex": location, "$options": "i"}},
            {"company_headquarters": {"$regex": location, "$options": "i"}},
        ]
    if industry:
        query["company_industry"] = {"$regex": industry, "$options": "i"}
    if fit_tier is not None:
        query["fit_tier"] = fit_tier
    if basket:
        query["classification_basket"] = basket.upper()
    if icp_tag:
        query["icp_tags"] = icp_tag
    if search:
        search_or = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"company": {"$regex": search, "$options": "i"}},
            {"company_name": {"$regex": search, "$options": "i"}},
            {"title": {"$regex": search, "$options": "i"}},
        ]
        if "$or" in query:
            query["$and"] = [{"$or": query.pop("$or")}, {"$or": search_or}]
        else:
            query["$or"] = search_or

    total = leads_col.count_documents(query)
    skip = (page - 1) * limit
    docs = list(
        leads_col.find(query)
        .sort("created_at", DESCENDING)
        .skip(skip)
        .limit(limit)
    )
    return {
        "leads": [_serialize(d) for d in docs],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
    }


@router.get("/icps")
async def list_icp_segments_alias():
    """List all ICP segments — static route must precede /{lead_id}."""
    return await _get_icps()


@router.get("/{lead_id}")
async def get_lead(lead_id: str):
    """Get a single lead by ID."""
    doc = leads_col.find_one({"_id": ObjectId(lead_id)})
    if not doc:
        raise HTTPException(404, "Lead not found")
    return _serialize(doc)


@router.post("")
async def create_lead(payload: LeadCreate):
    """Create a new lead."""
    now = datetime.utcnow()
    domain = payload.domain
    if not domain and payload.email:
        domain = _extract_domain(payload.email)

    # Deduplicate by email
    if payload.email:
        existing = leads_col.find_one({"email": payload.email.lower().strip()})
        if existing:
            raise HTTPException(409, f"Lead with email {payload.email} already exists")

    doc = {
        "source": payload.source.value,
        "stage": LeadStage.NEW.value,
        "name": payload.name,
        "email": payload.email.lower().strip() if payload.email else None,
        "email_status": EmailStatus.PENDING.value,
        "company": payload.company,
        "domain": domain,
        "last_contacted": None,
        "intent_score": None,
        "enrichment": {"status": "pending"},
        "mail_thread_ids": payload.mail_thread_ids,
        "contactus_message": payload.contactus_message,
        "track": payload.track.value,
        "rfq_id": None,
        "archived": False,
        "reengagement_eligible_at": None,
        "email_draft": None,
        "created_at": now,
        "updated_at": now,
    }
    result = leads_col.insert_one(doc)
    return {"_id": str(result.inserted_id), "stage": doc["stage"]}


@router.put("/{lead_id}")
async def update_lead(lead_id: str, payload: LeadUpdate):
    """Update lead fields (not stage — use /stage endpoint)."""
    update_data = {k: v for k, v in payload.dict(exclude_none=True).items()}
    if not update_data:
        raise HTTPException(400, "No fields to update")

    update_data["updated_at"] = datetime.utcnow()

    # Serialize nested Pydantic models
    if "enrichment" in update_data and hasattr(update_data["enrichment"], "dict"):
        update_data["enrichment"] = update_data["enrichment"].dict()
    if "email_draft" in update_data and hasattr(update_data["email_draft"], "dict"):
        update_data["email_draft"] = update_data["email_draft"].dict()

    result = leads_col.update_one(
        {"_id": ObjectId(lead_id)},
        {"$set": update_data},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Lead not found")
    return {"updated": True}


@router.delete("/{lead_id}")
async def archive_lead(lead_id: str):
    """Soft-delete (archive) a lead."""
    result = leads_col.update_one(
        {"_id": ObjectId(lead_id)},
        {"$set": {"archived": True, "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Lead not found")
    return {"archived": True}


# ══════════════════════════════════════════════
#  STAGE TRANSITION  (Step 14)
# ══════════════════════════════════════════════

@router.put("/{lead_id}/stage")
async def transition_stage(lead_id: str, payload: StageTransition):
    """
    Server-side validated stage transition.
    All stage changes MUST go through this endpoint.
    """
    lead = leads_col.find_one({"_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(404, "Lead not found")

    current = lead["stage"]
    new = payload.new_stage.value
    allowed = ALLOWED_TRANSITIONS.get(current, [])

    if new not in allowed:
        raise HTTPException(
            400,
            f"Transition from '{current}' to '{new}' is not permitted. Allowed: {allowed}",
        )

    if new == "lost" and not payload.reason:
        raise HTTPException(400, "Reason is required when marking as lost")

    update: Dict[str, Any] = {
        "stage": new,
        "updated_at": datetime.utcnow(),
    }

    if new == "lost":
        update["reengagement_eligible_at"] = datetime.utcnow() + timedelta(days=180)
        update["loss_reason"] = payload.reason

    leads_col.update_one({"_id": ObjectId(lead_id)}, {"$set": update})

    # Post-won triggers (Step 15)
    if new == "won":
        try:
            _handle_won(lead_id)
        except Exception as e:
            logger.error(f"Post-won trigger failed for {lead_id}: {e}")

    return {"stage": new, "lead_id": lead_id}


# ══════════════════════════════════════════════
#  INBOUND WEBHOOK  (Step 4)
# ══════════════════════════════════════════════

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


@router.post("/inbound", status_code=201)
async def inbound_lead(payload: InboundLeadPayload):
    """
    Contact Us form submission handler.
    Creates or updates a lead with high intent baseline.
    """
    email = payload.email.lower().strip()
    domain = _extract_domain(email)
    now = datetime.utcnow()

    existing = leads_col.find_one({"email": email})
    if existing:
        leads_col.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {"last_contacted": now, "updated_at": now},
                "$push": {"contactus_messages": payload.message},
            },
        )
        lead_id = str(existing["_id"])
    else:
        doc = {
            "source": LeadSource.FORM.value,
            "stage": LeadStage.VERIFIED.value,
            "name": payload.name,
            "email": email,
            "email_status": EmailStatus.VERIFIED.value,
            "company": payload.company,
            "domain": domain,
            "last_contacted": now,
            "intent_score": 80,
            "enrichment": {"status": "pending"},
            "mail_thread_ids": [],
            "contactus_message": payload.message,
            "contactus_messages": [payload.message],
            "track": LeadTrack.INBOUND.value,
            "rfq_id": None,
            "archived": False,
            "reengagement_eligible_at": None,
            "email_draft": None,
            "created_at": now,
            "updated_at": now,
        }
        result = leads_col.insert_one(doc)
        lead_id = str(result.inserted_id)

    # Notify
    _send_inbound_notification(payload.name, payload.company, payload.message[:200])

    return {"lead_id": lead_id}


def _send_inbound_notification(name: str, company: str, message_preview: str):
    """Send Slack or in-app notification for new inbound lead."""
    if SLACK_WEBHOOK_URL:
        import httpx
        try:
            httpx.post(
                SLACK_WEBHOOK_URL,
                json={
                    "text": f"🔔 New inbound lead: *{name}* at *{company}*\n>{message_preview}",
                },
                timeout=5,
            )
        except Exception as e:
            logger.error(f"Slack notification failed: {e}")
    else:
        _db["notifications"].insert_one({
            "type": "inbound_lead",
            "title": f"New inbound lead: {name} at {company}",
            "message": message_preview,
            "read": False,
            "created_at": datetime.utcnow(),
        })


# ══════════════════════════════════════════════
#  GOOGLE SEARCH PROSPECTING  (Step 6)
# ══════════════════════════════════════════════

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID", "")


@router.post("/prospect")
async def prospect_leads(payload: ProspectRequest):
    """
    Google Custom Search API prospecting.
    Finds leads via LinkedIn search results and creates them as stage=email_construction.
    """
    if not GOOGLE_API_KEY or not SEARCH_ENGINE_ID:
        raise HTTPException(500, "Google API key or Search Engine ID not configured")

    query = f"{payload.job_title} {payload.industry} {payload.location} site:linkedin.com"
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://customsearch.googleapis.com/customsearch/v1",
            params={
                "key": GOOGLE_API_KEY,
                "cx": SEARCH_ENGINE_ID,
                "q": query,
                "num": min(payload.max_results, 10),
            },
            timeout=15,
        )

    if resp.status_code != 200:
        raise HTTPException(502, f"Google Search API error: {resp.status_code}")

    data = resp.json()
    items = data.get("items", [])

    created = []
    skipped = 0
    now = datetime.utcnow()

    for item in items:
        title = item.get("title", "")
        link = item.get("link", "")
        snippet = item.get("snippet", "")

        # Parse "Name - Title at Company" pattern
        parsed = _parse_linkedin_title(title)
        if not parsed:
            skipped += 1
            continue

        name = parsed["name"]
        company = parsed.get("company", "")
        domain = _extract_domain_from_url(link) if link else ""

        # Deduplicate
        dedup_hash = hashlib.md5(f"{domain}:{name.lower()}".encode()).hexdigest()
        existing = leads_col.find_one({
            "$or": [
                {"_dedup_hash": dedup_hash},
                {"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}, "domain": domain},
            ]
        })
        if existing:
            skipped += 1
            continue

        doc = {
            "source": LeadSource.GOOGLE_SEARCH.value,
            "stage": LeadStage.EMAIL_CONSTRUCTION.value,
            "name": name,
            "email": None,
            "email_status": EmailStatus.PENDING.value,
            "company": company,
            "domain": domain,
            "last_contacted": None,
            "intent_score": None,
            "enrichment": {"status": "pending"},
            "mail_thread_ids": [],
            "contactus_message": None,
            "track": LeadTrack.COLD.value,
            "rfq_id": None,
            "archived": False,
            "reengagement_eligible_at": None,
            "email_draft": None,
            "_dedup_hash": dedup_hash,
            "_linkedin_url": link,
            "_snippet": snippet,
            "created_at": now,
            "updated_at": now,
        }
        result = leads_col.insert_one(doc)
        created.append(str(result.inserted_id))

    # Enqueue for email construction (Celery)
    if created:
        try:
            from tasks.sales_tasks import enqueue_email_construction
            for lid in created:
                enqueue_email_construction.delay(lid)
        except Exception as e:
            logger.warning(f"Could not enqueue email construction: {e}")

    return {"created": len(created), "skipped": skipped, "lead_ids": created}


def _parse_linkedin_title(title: str) -> Optional[Dict[str, str]]:
    """Parse 'Name - Title at Company | LinkedIn' pattern."""
    title = title.replace(" | LinkedIn", "").replace("| LinkedIn", "").strip()
    # Pattern: "John Smith - VP Sales at Acme Corp"
    match = re.match(r"^(.+?)\s*[-–—]\s*(.+?)(?:\s+at\s+(.+))?$", title)
    if match:
        name = match.group(1).strip()
        company = (match.group(3) or "").strip()
        return {"name": name, "company": company}
    # Fallback: just take the first part
    parts = title.split("-")
    if parts:
        return {"name": parts[0].strip(), "company": ""}
    return None


def _extract_domain_from_url(url: str) -> str:
    """Extract root domain from a URL."""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        # For LinkedIn URLs, domain is not useful — leave empty
        if "linkedin.com" in host:
            return ""
        parts = host.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return host
    except Exception:
        return ""


# ══════════════════════════════════════════════
#  DRAFT MANAGEMENT  (Step 11 backend)
# ══════════════════════════════════════════════

@router.put("/{lead_id}/draft/approve")
async def approve_draft(lead_id: str, payload: DraftApproval = Body(default=None)):
    """Approve email draft — optionally override subject/body. Triggers send job."""
    lead = leads_col.find_one({"_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(404, "Lead not found")

    draft = lead.get("email_draft")
    if not draft or draft.get("status") != "pending_review":
        raise HTTPException(400, "No pending draft to approve")

    update = {
        "email_draft.status": "approved",
        "email_draft.approved_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    if payload and payload.subject:
        update["email_draft.subject"] = payload.subject
    if payload and payload.body:
        update["email_draft.body"] = payload.body

    leads_col.update_one({"_id": ObjectId(lead_id)}, {"$set": update})

    # Enqueue send job
    try:
        from tasks.sales_tasks import send_approved_email
        send_approved_email.delay(lead_id)
    except Exception as e:
        logger.warning(f"Could not enqueue send job: {e}")

    return {"approved": True, "lead_id": lead_id}


@router.post("/{lead_id}/draft/regenerate")
async def regenerate_draft(lead_id: str, payload: DraftRegenerate = Body(default=None)):
    """Re-run draft generation with optional instruction and optional ICP override."""
    lead = leads_col.find_one({"_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(404, "Lead not found")

    leads_col.update_one(
        {"_id": ObjectId(lead_id)},
        {"$set": {"email_draft.status": "pending_review", "updated_at": datetime.utcnow()}},
    )

    try:
        from tasks.sales_tasks import generate_email_draft
        instruction = payload.instruction if payload else None
        icp_slug = getattr(payload, "icp_slug", None) if payload else None
        generate_email_draft.delay(lead_id, instruction=instruction, icp_slug=icp_slug)
    except Exception as e:
        logger.warning(f"Could not enqueue draft regen: {e}")

    return {"regenerating": True, "lead_id": lead_id}


@router.put("/{lead_id}/draft/discard")
async def discard_draft(lead_id: str):
    """Discard the pending draft."""
    result = leads_col.update_one(
        {"_id": ObjectId(lead_id), "email_draft.status": "pending_review"},
        {"$set": {"email_draft.status": "discarded", "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "No pending draft found")
    return {"discarded": True}


@router.post("/drafts/bulk-approve")
async def bulk_approve_drafts(lead_ids: List[str] = Body(...)):
    """Bulk approve pending drafts."""
    now = datetime.utcnow()
    oids = [ObjectId(lid) for lid in lead_ids]
    result = leads_col.update_many(
        {"_id": {"$in": oids}, "email_draft.status": "pending_review"},
        {"$set": {"email_draft.status": "approved", "email_draft.approved_at": now, "updated_at": now}},
    )

    # Enqueue send jobs
    try:
        from tasks.sales_tasks import send_approved_email
        for lid in lead_ids:
            send_approved_email.delay(lid)
    except Exception as e:
        logger.warning(f"Could not enqueue bulk send: {e}")

    return {"approved_count": result.modified_count}


# ══════════════════════════════════════════════
#  ICP SEGMENT MANAGEMENT
# ══════════════════════════════════════════════

async def _get_icps():
    """
    Shared logic: return all ICP segments, seeding defaults if collection is empty.
    """
    docs = list(icp_segments_col.find({}, {"_id": 0}).sort("slug", 1))
    if not docs:
        try:
            from .schemas import setup_icp_segments_collection
        except ImportError:
            from schemas import setup_icp_segments_collection
        setup_icp_segments_collection(_db)
        docs = list(icp_segments_col.find({}, {"_id": 0}).sort("slug", 1))
    return {"icps": docs}


@router.post("/icps", status_code=201)
async def create_icp_segment(payload: ICPSegmentCreate):
    """Create a new ICP segment definition."""
    existing = icp_segments_col.find_one({"slug": payload.slug})
    if existing:
        raise HTTPException(409, f"ICP segment '{payload.slug}' already exists")
    now = datetime.utcnow()
    doc = {
        "slug": payload.slug,
        "name": payload.name,
        "description": payload.description,
        "criteria": payload.criteria or {},
        "color": payload.color or "#6b7280",
        "created_at": now,
    }
    icp_segments_col.insert_one(doc)
    return {"slug": payload.slug, "created": True}


@router.put("/{lead_id}/icps")
async def set_lead_icps(lead_id: str, payload: LeadICPUpdate):
    """
    Replace the full icp_tags list for a single lead.
    Use an empty list to clear all ICP tags.
    """
    result = leads_col.update_one(
        {"_id": ObjectId(lead_id)},
        {"$set": {"icp_tags": payload.icp_tags, "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Lead not found")
    return {"lead_id": lead_id, "icp_tags": payload.icp_tags}


@router.post("/bulk-icp-tag")
async def bulk_icp_tag(payload: BulkICPTag):
    """
    Append an ICP tag to multiple leads without overwriting existing tags.
    Idempotent — calling twice with the same slug won't duplicate the tag.
    """
    if not payload.lead_ids:
        raise HTTPException(400, "lead_ids must not be empty")
    slug = payload.icp_segment.strip().lower()
    if not slug:
        raise HTTPException(400, "icp_segment must not be empty")

    oids = [ObjectId(lid) for lid in payload.lead_ids]
    result = leads_col.update_many(
        {"_id": {"$in": oids}},
        {
            "$addToSet": {"icp_tags": slug},
            "$set": {"updated_at": datetime.utcnow()},
        },
    )
    return {"updated_count": result.modified_count, "icp_segment": slug}


@router.delete("/{lead_id}/icps/{slug}")
async def remove_lead_icp(lead_id: str, slug: str):
    """Remove a single ICP tag from a lead."""
    result = leads_col.update_one(
        {"_id": ObjectId(lead_id)},
        {
            "$pull": {"icp_tags": slug},
            "$set": {"updated_at": datetime.utcnow()},
        },
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Lead not found")
    return {"lead_id": lead_id, "removed_icp": slug}


@router.post("/icps/{slug}/launch-outreach")
async def launch_icp_outreach(slug: str, limit: int = Query(50, ge=1, le=500)):
    """
    Bulk-enqueue draft generation for all enriched leads tagged with a given ICP slug.
    Only processes leads at stage=enriched without an existing pending/approved draft.
    Returns the number of jobs queued.
    """
    seg = icp_segments_col.find_one({"slug": slug})
    if not seg:
        raise HTTPException(404, f"ICP segment '{slug}' not found")

    # Find eligible leads
    query = {
        "icp_tags": slug,
        "stage": "enriched",
        "archived": False,
        "$or": [
            {"email_draft": None},
            {"email_draft": {"$exists": False}},
            {"email_draft.status": "discarded"},
        ],
    }
    leads = list(leads_col.find(query, {"_id": 1}).limit(limit))
    if not leads:
        return {"queued": 0, "icp_slug": slug, "message": "No eligible leads found"}

    queued = 0
    try:
        from tasks.sales_tasks import generate_email_draft
        for lead in leads:
            generate_email_draft.delay(str(lead["_id"]), icp_slug=slug)
            queued += 1
    except Exception as e:
        logger.warning(f"Could not enqueue ICP outreach jobs: {e}")
        return {"queued": queued, "icp_slug": slug, "warning": str(e)}

    return {"queued": queued, "icp_slug": slug, "segment_name": seg.get("name", slug)}
