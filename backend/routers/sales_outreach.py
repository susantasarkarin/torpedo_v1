"""
SALES OUTREACH ROUTER
======================
FastAPI router exposing all 6 modules of the lead generation and outreach system.

Endpoints:
  GET  /api/sales-outreach/validate            — Module 1: Full pipeline validation
  POST /api/sales-outreach/validate/csv        — Module 1: Validate + parse a CSV upload
  POST /api/sales-outreach/mail-pool/extract   — Module 2: Trigger mail pool extraction
  POST /api/sales-outreach/mail-pool/backfill  — Module 2: One-time full backfill
  POST /api/sales-outreach/enrich/{lead_id}    — Module 3: Trigger Gemini enrichment for a lead
  POST /api/sales-outreach/route/{lead_id}     — Module 4: BU routing via Gemini
  POST /api/sales-outreach/send/{lead_id}      — Module 5: Send initial outreach email
  POST /api/sales-outreach/event               — Module 6: Ingest email tracking event
  POST /api/sales-outreach/reply/{lead_id}     — Module 6: Manually trigger reply analysis
  GET  /api/sales-outreach/status/{lead_id}    — Get full outreach status for a lead
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sales-outreach", tags=["Sales Outreach"])


# ─────────────────────────────────────────────────────
#  AUTH DEPENDENCY  (reuse existing auth)
# ─────────────────────────────────────────────────────

def _require_auth():
    """Placeholder — will be replaced by existing auth dependency."""
    pass


# ─────────────────────────────────────────────────────
#  REQUEST MODELS
# ─────────────────────────────────────────────────────

class EmailEvent(BaseModel):
    type: str  # delivered | opened | bounced | reply_received
    lead_id: str
    email: Optional[str] = None
    reply_body: Optional[str] = None
    gmail_message_id: Optional[str] = None


class ReplyAnalysisRequest(BaseModel):
    reply_body: str
    gmail_message_id: Optional[str] = None


# ─────────────────────────────────────────────────────
#  MODULE 1: PIPELINE VALIDATION
# ─────────────────────────────────────────────────────

@router.get("/validate", summary="Run full pipeline health validation")
async def validate_pipeline():
    """
    Module 1: Runs all 8 pipeline health checks and returns a consolidated report.
    Checks: DB, AI leads, CSV pipeline, Gemini quota, Gmail API, Celery workers,
            enrichment health, email construction queue.
    """
    try:
        from sales.validation import run_full_validation
        result = run_full_validation()
        status_code = 200 if result["overall_ok"] else 207  # 207 = partial success
        return result
    except Exception as e:
        logger.error(f"[Validation] Endpoint failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate/csv", summary="Validate and parse a CSV upload")
async def validate_csv(file: UploadFile = File(...)):
    """
    Module 1: Parse a CSV file and validate its structure before import.
    Returns row count, valid rows, and any missing required columns.
    """
    try:
        content = await file.read()
        from sales.validation import check_csv_pipeline
        result = check_csv_pipeline(csv_bytes=content)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "CSV validation failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Validation/CSV] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────
#  MODULE 2: MAIL POOL EXTRACTION
# ─────────────────────────────────────────────────────

@router.post("/mail-pool/extract", summary="Extract leads from recent mail pool")
async def extract_mail_pool(since_hours: int = 24, limit: int = 500):
    """
    Module 2: Scan email_metadata for recent emails and extract leads using regex/code only.
    No AI used. Deduplicates against existing leads collection.
    """
    try:
        from sales.mail_pool_extractor import extract_leads_from_mail_pool
        task = extract_leads_from_mail_pool.delay(since_hours=since_hours, limit=limit)
        return {"status": "queued", "task_id": task.id, "since_hours": since_hours, "limit": limit}
    except Exception as e:
        logger.error(f"[MailPool/Extract] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mail-pool/backfill", summary="One-time backfill of all existing mail pool emails")
async def backfill_mail_pool(limit: int = 2000):
    """
    Module 2: Scan ALL existing email_metadata records for unprocessed leads.
    Use once to retroactively seed the leads collection from the full mail pool.
    """
    try:
        from sales.mail_pool_extractor import backfill_leads_from_mail_pool
        task = backfill_leads_from_mail_pool.delay(limit=limit)
        return {"status": "queued", "task_id": task.id, "limit": limit}
    except Exception as e:
        logger.error(f"[MailPool/Backfill] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────
#  MODULE 3: GEMINI ENRICHMENT
# ─────────────────────────────────────────────────────

@router.post("/enrich/{lead_id}", summary="Trigger Gemini enrichment for a lead")
async def enrich_lead(lead_id: str):
    """
    Module 3: Enrich a lead using Google Gemini only.
    Gathers company data via web scrape (code-only), then calls Gemini for
    company size, industry, role, seniority, pain points, and personalisation hook.
    """
    try:
        from sales.tasks import enrich_lead as _enrich_task
        task = _enrich_task.delay(lead_id)
        return {"status": "queued", "task_id": task.id, "lead_id": lead_id}
    except Exception as e:
        logger.error(f"[Enrich] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────
#  MODULE 4: BU ROUTING
# ─────────────────────────────────────────────────────

@router.post("/route/{lead_id}", summary="Route lead to best-fit business unit via Gemini")
async def route_lead(lead_id: str):
    """
    Module 4: Use Gemini to compare the enriched lead against all business unit
    descriptions, identify the gap, pick the best BU, and draft a personalised email.
    Stores result on the lead and triggers send_initial_outreach.
    """
    try:
        from sales.outreach_pipeline import route_lead_to_bu
        task = route_lead_to_bu.delay(lead_id)
        return {"status": "queued", "task_id": task.id, "lead_id": lead_id}
    except Exception as e:
        logger.error(f"[Route] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────
#  MODULE 5: GMAIL OUTREACH
# ─────────────────────────────────────────────────────

@router.post("/send/{lead_id}", summary="Send initial outreach email via Gmail")
async def send_outreach(lead_id: str):
    """
    Module 5: Manually trigger the initial outreach email for a lead.
    Uses the BU-routed draft or approved email_draft from the lead record.
    Sends via Susanta's Gmail account and schedules follow-ups automatically.
    """
    try:
        from sales.outreach_pipeline import send_initial_outreach
        task = send_initial_outreach.delay(lead_id)
        return {"status": "queued", "task_id": task.id, "lead_id": lead_id}
    except Exception as e:
        logger.error(f"[Send] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────
#  MODULE 6: EMAIL TRACKING + REPLY ANALYSIS
# ─────────────────────────────────────────────────────

@router.post("/event", summary="Ingest an email tracking event")
async def ingest_event(event: EmailEvent):
    """
    Module 6: Receive a tracking event (delivered, opened, bounced, reply_received).
    Bounced → suppresses and removes from sequence.
    reply_received → triggers Gemini sentiment analysis.
    """
    try:
        from sales.outreach_pipeline import handle_email_event
        handle_email_event.delay(event.dict())
        return {"status": "received", "type": event.type, "lead_id": event.lead_id}
    except Exception as e:
        logger.error(f"[Event] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reply/{lead_id}", summary="Trigger Gemini reply sentiment analysis")
async def analyze_reply_endpoint(lead_id: str, body: ReplyAnalysisRequest):
    """
    Module 6: Analyse a reply email using Gemini.
    positive → move to active CRM, negative → archive, neutral → flag for manual review.
    """
    try:
        from sales.outreach_pipeline import analyze_reply
        task = analyze_reply.delay(
            lead_id,
            body.reply_body,
            body.gmail_message_id or "",
        )
        return {"status": "queued", "task_id": task.id, "lead_id": lead_id}
    except Exception as e:
        logger.error(f"[Reply] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────
#  LEAD STATUS
# ─────────────────────────────────────────────────────

@router.get("/status/{lead_id}", summary="Get full outreach status for a lead")
async def get_lead_status(lead_id: str):
    """
    Get the current outreach status, routing result, email events, and reply analysis
    for a lead — all in one response.
    """
    try:
        from bson import ObjectId
        from db_pools import get_background_db
        db = get_background_db()

        lead = db["leads"].find_one({"_id": ObjectId(lead_id)})
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        events = list(db["email_events"].find(
            {"lead_id": lead_id},
            sort=[("sent_at", -1)],
            limit=20,
        ))
        for e in events:
            e["_id"] = str(e["_id"])

        return {
            "lead_id": lead_id,
            "name": lead.get("name"),
            "email": lead.get("email"),
            "company": lead.get("company"),
            "stage": lead.get("stage"),
            "outreach_step": lead.get("outreach_step"),
            "email_status": lead.get("email_status"),
            "engagement_status": lead.get("engagement_status"),
            "bu_routing": lead.get("bu_routing"),
            "enrichment": lead.get("enrichment"),
            "last_contacted": str(lead.get("last_contacted", "")),
            "last_reply": lead.get("last_reply"),
            "needs_manual_review": lead.get("needs_manual_review", False),
            "archived": lead.get("archived", False),
            "events": events,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Status] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────
#  BUSINESS UNIT CONFIG CRUD
# ─────────────────────────────────────────────────────

from pathlib import Path
from pydantic import BaseModel as _BaseModel

_BU_DIR = Path(__file__).resolve().parent.parent / "configs" / "business_units"


class BUConfigUpdate(_BaseModel):
    content: str


class BUConfigCreate(_BaseModel):
    slug: str
    content: str


@router.get("/bu-configs", summary="List all business unit config files")
async def list_bu_configs():
    """Return all BU config files with their slugs, names, and full content."""
    try:
        _BU_DIR.mkdir(parents=True, exist_ok=True)
        units = []
        for txt_file in sorted(_BU_DIR.glob("*.txt")):
            content = txt_file.read_text(encoding="utf-8")
            first_line = content.splitlines()[0] if content.splitlines() else txt_file.stem
            name = (
                first_line.replace("BUSINESS UNIT:", "").strip().split("—")[0].strip()
                if "BUSINESS UNIT:" in first_line
                else txt_file.stem
            )
            units.append({
                "slug": txt_file.stem,
                "name": name,
                "content": content,
                "filename": txt_file.name,
            })
        return {"business_units": units, "count": len(units)}
    except Exception as e:
        logger.error(f"[BU Config] List failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bu-configs/{slug}", summary="Get a single BU config file")
async def get_bu_config(slug: str):
    """Return the full content of a single BU config file by slug."""
    try:
        # Sanitize slug — only allow alphanumerics and underscores
        safe_slug = "".join(c for c in slug if c.isalnum() or c == "_")
        if safe_slug != slug:
            raise HTTPException(status_code=400, detail="Invalid slug characters")
        path = _BU_DIR / f"{safe_slug}.txt"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"BU config '{slug}' not found")
        content = path.read_text(encoding="utf-8")
        first_line = content.splitlines()[0] if content.splitlines() else slug
        name = (
            first_line.replace("BUSINESS UNIT:", "").strip().split("—")[0].strip()
            if "BUSINESS UNIT:" in first_line else slug
        )
        return {"slug": safe_slug, "name": name, "content": content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/bu-configs/{slug}", summary="Update a BU config file")
async def update_bu_config(slug: str, body: BUConfigUpdate):
    """Overwrite the content of an existing BU config file."""
    try:
        safe_slug = "".join(c for c in slug if c.isalnum() or c == "_")
        if safe_slug != slug:
            raise HTTPException(status_code=400, detail="Invalid slug characters")
        path = _BU_DIR / f"{safe_slug}.txt"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"BU config '{slug}' not found")
        path.write_text(body.content, encoding="utf-8")
        logger.info(f"[BU Config] Updated '{slug}'")
        return {"status": "updated", "slug": safe_slug}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bu-configs", summary="Create a new BU config file")
async def create_bu_config(body: BUConfigCreate):
    """Create a new BU config .txt file."""
    try:
        safe_slug = "".join(c for c in body.slug if c.isalnum() or c == "_")
        if not safe_slug:
            raise HTTPException(status_code=400, detail="Invalid slug")
        path = _BU_DIR / f"{safe_slug}.txt"
        if path.exists():
            raise HTTPException(status_code=409, detail=f"BU config '{safe_slug}' already exists")
        _BU_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(body.content, encoding="utf-8")
        logger.info(f"[BU Config] Created '{safe_slug}'")
        return {"status": "created", "slug": safe_slug}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/bu-configs/{slug}", summary="Delete a BU config file")
async def delete_bu_config(slug: str):
    """Delete a BU config file by slug."""
    try:
        safe_slug = "".join(c for c in slug if c.isalnum() or c == "_")
        if safe_slug != slug:
            raise HTTPException(status_code=400, detail="Invalid slug characters")
        path = _BU_DIR / f"{safe_slug}.txt"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"BU config '{slug}' not found")
        path.unlink()
        logger.info(f"[BU Config] Deleted '{slug}'")
        return {"status": "deleted", "slug": safe_slug}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
