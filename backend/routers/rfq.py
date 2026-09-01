"""
RFQ Router - Request for Quotation Management

Provides endpoints for:
- RFQ CRUD operations
- RFQ listing with filters
- Value override/update
- Link to leads
- Email thread association
- Convert to Estimate/Invoice
"""

import os
import re
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field
from pymongo import MongoClient, DESCENDING
from bson import ObjectId
from dotenv import load_dotenv


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    try:
        from ..database import get_client
    except ImportError:
        from database import get_client
    return get_client()


load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/rfq",
    tags=["rfq"]
)

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
mongo_client = _get_pooled_client()
db = mongo_client["email_automation"]
rfqs_collection = db["rfqs"]
email_leads_collection = db["email_leads"]
mail_sender_analysis_collection = db["mail_sender_analysis"]

# Gmail API database (torpedo_gmail)
gmail_db = mongo_client["torpedo_gmail"]
email_metadata_collection = gmail_db["email_metadata"]

# Finance database for estimates and invoices
finance_db = mongo_client["finance_db"]
customers_collection = finance_db["customers"]
estimates_collection = finance_db["estimates"]
invoices_collection = finance_db["invoices"]

# Contacts collection for CRM
contacts_collection = db["contacts"]

# CRM spine read model. RFQs live in crm_db.opportunities — mail_pool_ai writes
# them there every 10 min; email_automation.rfqs is legacy and read-only now.
try:
    from ..app.services import spine_rfq
except ImportError:  # pragma: no cover - flat import when run from backend/
    from app.services import spine_rfq


# ============== PYDANTIC MODELS ==============

class RFQCreate(BaseModel):
    """Request model for creating RFQ manually"""
    # Inbound (a client asking us for a quote): contact_email identifies the
    # lead. Outbound (we're asking a vendor for pricing/feasibility):
    # vendor_name identifies the counterparty instead — there's often no
    # specific contact email on hand yet, so contact_email is optional and
    # validated against `direction` in the create_rfq handler below.
    direction: str = Field("inbound", description="inbound (client -> us) or outbound (us -> vendor)")
    contact_email: Optional[str] = Field(None, description="Lead's email address (inbound RFQs)")
    vendor_name: Optional[str] = Field(None, description="Vendor being asked for pricing (outbound RFQs)")
    client_name: Optional[str] = Field(None, description="Underlying client this outbound sourcing is for")
    lead_id: Optional[str] = Field(None, description="ObjectId reference to lead")
    title: str = Field(..., description="RFQ title")
    description: str = Field("", description="RFQ description")
    manual_value: Optional[float] = Field(None, description="Manual value override")
    manual_currency: str = Field("USD", description="Currency code (USD, INR, EUR, GBP)")
    priority: str = Field("medium", description="Priority: low, medium, high")
    due_date: Optional[str] = Field(None, description="Due date ISO string")
    # New fields for enhanced RFQ
    methodology: Optional[str] = Field(None, description="Research methodology (CATI, CAWI, F2F, etc.)")
    loi: Optional[int] = Field(None, description="Length of Interview in minutes")
    ir: Optional[float] = Field(None, description="Incidence Rate percentage")
    country: Optional[str] = Field(None, description="Target country for the study")
    sample_size: Optional[int] = Field(None, description="Required sample size")


class RFQUpdate(BaseModel):
    """Request model for updating RFQ"""
    title: Optional[str] = None
    description: Optional[str] = None
    manual_value: Optional[float] = None
    manual_currency: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    # Required by the spine when moving an RFQ to "lost", so losses stay analyzable.
    loss_reason: Optional[str] = None
    direction: Optional[str] = None
    # New fields for enhanced RFQ
    methodology: Optional[str] = None
    loi: Optional[int] = None
    ir: Optional[float] = None
    country: Optional[str] = None
    sample_size: Optional[int] = None
    target_audience: Optional[str] = None
    timeline: Optional[str] = None
    study_type: Optional[str] = None
    budget: Optional[float] = None
    additional_requirements: Optional[str] = None
    client_name: Optional[str] = None


class RFQResponse(BaseModel):
    """Response model for RFQ"""
    rfq_id: str
    contact_email: str
    lead_id: Optional[str] = None
    lead_name: Optional[str] = None
    title: str
    description: str = ""
    extracted_value: Optional[float] = None
    extracted_currency: str = "USD"
    manual_value: Optional[float] = None
    manual_currency: Optional[str] = None
    final_value: Optional[float] = None
    final_currency: str = "USD"
    source_emails_count: int = 0
    status: str = "pending"
    priority: str = "medium"
    received_date: Optional[str] = None
    due_date: Optional[str] = None
    summary: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # New fields for enhanced RFQ (AI extracted)
    methodology: Optional[str] = None
    loi: Optional[int] = None
    ir: Optional[float] = None
    country: Optional[str] = None
    sample_size: Optional[int] = None
    target_audience: Optional[str] = None
    timeline: Optional[str] = None
    study_type: Optional[str] = None
    budget: Optional[float] = None
    additional_requirements: Optional[str] = None
    ai_summary: Optional[str] = None
    # Email body and sender details
    email_body: Optional[str] = None
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    sender_company: Optional[str] = None
    sender_title: Optional[str] = None


# ============== HELPER FUNCTIONS ==============

def generate_rfq_id() -> str:
    """
    Generate the next RFQ-YYYY-NNNN id.

    Counts against the spine (crm_db.opportunities), which is where RFQs live
    now — numbering off the legacy collection would restart at 0001 and collide
    with every migrated RFQ.
    """
    try:
        from ..app.services import crm_service
    except ImportError:  # pragma: no cover
        from app.services import crm_service

    year = datetime.utcnow().year
    prefix = f"RFQ-{year}-"

    latest = crm_service._col("opportunities").find_one(
        {"metadata.rfq.rfq_id": {"$regex": f"^{prefix}"}},
        sort=[("metadata.rfq.rfq_id", DESCENDING)],
    )

    new_num = 1
    if latest:
        existing = (latest.get("metadata") or {}).get("rfq", {}).get("rfq_id", "")
        try:
            new_num = int(existing.split("-")[-1]) + 1
        except (ValueError, IndexError):
            new_num = 1

    return f"{prefix}{new_num:04d}"


@router.get("/")
async def list_rfqs(
    state: Optional[str] = Query(None, description="Coarse state: open | won | lost | closed"),
    status: Optional[str] = Query(None, description="Detailed status: pending/quoted/negotiating/won/lost"),
    account_id: Optional[str] = Query(None, description="Filter to one spine account"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    search: Optional[str] = Query(None, description="Search in title/description"),
    direction: Optional[str] = Query(
        None, description="inbound (client -> us, default) | outbound (us -> vendor)"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Items per page")
) -> Dict[str, Any]:
    """
    List RFQs, read from crm_db.opportunities (the CRM spine).

    The spine is the single source of truth: backend/sales/mail_pool_ai.py logs
    every mailbox-detected RFQ there every 10 minutes. This endpoint used to read
    email_automation.rfqs, which that pipeline never wrote to — which is why
    mailbox RFQs never showed up on the Sales page.
    """
    result = spine_rfq.list_rfqs(
        state=state,
        status=status,
        account_id=account_id,
        search=search,
        direction=direction,
        page=page,
        limit=limit,
    )

    # `priority` is not a spine field; filter the page in memory rather than
    # pretending the query engine handled it.
    if priority:
        result["rfqs"] = [r for r in result["rfqs"] if r.get("priority") == priority]

    return result


@router.get("/stats")
async def get_rfq_stats(
    direction: Optional[str] = Query(
        None, description="inbound (client -> us, default) | outbound (us -> vendor)"
    )
) -> Dict[str, Any]:
    """
    RFQ counts and pipeline value, grouped by both the coarse open/won/lost/closed
    state and the detailed pipeline stage.
    """
    spine_stats = spine_rfq.get_stats(direction=direction)

    # Keep the legacy per-status shape the existing RFQ page renders, alongside
    # the new state rollup.
    legacy = {
        "pending": {"count": 0, "total_value": 0},
        "quoted": {"count": 0, "total_value": 0},
        "negotiating": {"count": 0, "total_value": 0},
        "won": {"count": 0, "total_value": 0},
        "lost": {"count": 0, "total_value": 0},
    }
    stage_to_status = {
        "new": "pending", "rfq": "pending", "qualified": "pending",
        "proposal": "quoted", "negotiation": "negotiating",
        "won": "won", "lost": "lost",
    }
    for stage, count in spine_stats["by_stage"].items():
        status = stage_to_status.get(stage)
        if status:
            legacy[status]["count"] += count

    return {
        "success": True,
        "stats": legacy,
        "by_state": spine_stats["by_state"],
        "by_stage": spine_stats["by_stage"],
        "pipeline_value": spine_stats["pipeline_value"],
        "won_value": spine_stats["won_value"],
        "total_count": spine_stats["total"],
        "total_value": spine_stats["pipeline_value"] + spine_stats["won_value"],
    }


@router.post("/sync-from-gmail")
async def sync_rfqs_from_gmail(
    limit: int = Query(100, description="Unused; kept so old clients still parse"),
    categories: List[str] = Query(["client", "rfq"], description="Unused")
) -> Dict[str, Any]:
    """
    RETIRED. RFQ creation from mail is owned by backend/sales/mail_pool_ai.py.

    This endpoint used to scan torpedo_gmail.email_metadata and write into
    email_automation.rfqs. It was one of three competing RFQ writers with three
    different dedup keys, and it wrote to a collection the live pipeline never
    reads. mail_pool_ai runs every 10 minutes over the same mailbox, does real
    AI extraction, and logs RFQs onto the CRM spine — that is the only writer now.

    Kept as a 410 rather than deleted so any scheduled caller fails loudly with
    a pointer instead of silently doing nothing.
    """
    raise HTTPException(
        status_code=410,
        detail=(
            "Retired. RFQs are created from mail by the mail_pool_ai pipeline "
            "(celery beat 'mail-pool-ai-sender-batch', every 10 min) and stored "
            "on the CRM spine. Use POST /rfq/resync to force a pass."
        ),
    )


@router.post("/resync")
async def resync_rfqs_from_mail(
    limit: int = Query(50, ge=1, le=500, description="Senders to process this pass")
) -> Dict[str, Any]:
    """
    Force an immediate mail-pool AI pass instead of waiting for the 10-minute beat.

    Queues the same Celery task the scheduler runs, so there is exactly one code
    path that turns mail into RFQs.
    """
    try:
        from ..tasks.mail_pool_ai_tasks import process_mail_pool_sender_batch
    except ImportError:  # pragma: no cover
        from tasks.mail_pool_ai_tasks import process_mail_pool_sender_batch

    try:
        task = process_mail_pool_sender_batch.delay(limit=limit)
        return {
            "success": True,
            "message": f"Mail-pool AI pass queued for {limit} senders",
            "task_id": task.id,
        }
    except Exception as e:
        logger.error(f"Failed to queue mail-pool AI pass: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Could not queue the sync task (is the Celery worker up?): {e}",
        )


@router.post("/resync-all")
async def resync_all_rfqs_from_mail_pool(
    limit: int = Query(50, ge=1, le=200, description="Senders to (re)scan this pass")
) -> Dict[str, Any]:
    """
    One-time RFQ rebuild backfill: re-scans every sender whose rfq_scan
    ledger is empty (via deep_scan_sender_rfqs), instead of only newly
    arriving mail like POST /rfq/resync does.

    Intended to run after scripts/clear_rfq_data.py, which deletes inbound
    RFQ-tagged opportunities and resets the affected senders' rfq_scan
    ledgers. Resumable and rate-limited — call repeatedly with a small
    `limit`; check GET /rfq/rebuild-status for how many senders remain.
    """
    try:
        from ..tasks.mail_pool_ai_tasks import rebuild_rfqs_all_senders_batch
    except ImportError:  # pragma: no cover
        from tasks.mail_pool_ai_tasks import rebuild_rfqs_all_senders_batch

    try:
        task = rebuild_rfqs_all_senders_batch.delay(limit=limit)
        return {
            "success": True,
            "message": f"RFQ rebuild pass queued for up to {limit} senders",
            "task_id": task.id,
        }
    except Exception as e:
        logger.error(f"Failed to queue RFQ rebuild pass: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Could not queue the sync task (is the Celery worker up?): {e}",
        )


@router.get("/rebuild-status")
async def get_rebuild_status() -> Dict[str, Any]:
    """
    Cheap poll for the POST /rfq/resync-all backfill: how many senders still
    need a rebuild scan. No AI calls — just counts against mail_sender_analysis.
    """
    try:
        from ..sales.mail_pool_ai import _REBUILD_CANDIDATE_QUERY
    except ImportError:  # pragma: no cover
        from sales.mail_pool_ai import _REBUILD_CANDIDATE_QUERY

    remaining = mail_sender_analysis_collection.count_documents(_REBUILD_CANDIDATE_QUERY)
    done = mail_sender_analysis_collection.count_documents({"rfq_rebuild_done": True})
    return {
        "success": True,
        "senders_remaining": remaining,
        "senders_rebuilt": done,
    }


@router.get("/sync-status")
async def get_sync_status() -> Dict[str, Any]:
    """
    Mail-pool -> RFQ ingestion status.

    Reports how much of the Gmail pool the AI pipeline has chewed through and
    how many RFQs that has produced on the spine, so an empty RFQ list can be
    told apart from a stalled worker.
    """
    try:
        from ..app.services import crm_service
    except ImportError:  # pragma: no cover
        from app.services import crm_service

    try:
        # Exact count, not estimated_document_count(): the estimate is derived
        # from collection metadata and drifts by a few documents, which made
        # `processed` (an exact count) come out HIGHER than the total.
        total_emails = email_metadata_collection.count_documents({})
        # mail_pool_ai stamps each analyzed email with `ai_analysis` — that is
        # the field its own sender query filters on, so count the same one.
        processed = email_metadata_collection.count_documents(
            {"ai_analysis": {"$exists": True}}
        )
        # Internal mail is skipped by design and can never become an RFQ, so
        # excluding it keeps "pending" from permanently overstating the backlog.
        pending = email_metadata_collection.count_documents({
            "ai_analysis": {"$exists": False},
            "internal": {"$ne": True},
            "from_email": {"$exists": True, "$nin": [None, ""]},
        })
        rfq_flagged = email_metadata_collection.count_documents(
            {"ai_category": "rfq"}
        )

        opportunities = crm_service._col("opportunities")
        spine_rfqs = opportunities.count_documents({
            "$or": [
                {"stage": "rfq"},
                {"metadata.source": "rfq"},
                {"metadata.rfq": {"$exists": True}},
            ]
        })

        # Only rows still awaiting migration. scripts/backfill_spine_rfqs.py
        # stamps migrated_to_spine on each row it moves, so counting every
        # non-deleted row reported 1018 "unmigrated" long after all 1018 had
        # in fact been migrated.
        legacy_rfqs = rfqs_collection.count_documents({
            "is_deleted": {"$ne": True},
            "migrated_to_spine": {"$ne": True},
        })

        return {
            "success": True,
            "stats": {
                "mail_pool_total": total_emails,
                "mail_pool_ai_processed": processed,
                "mail_pool_pending": pending,
                "emails_classified_rfq": rfq_flagged,
                "rfqs_on_spine": spine_rfqs,
                "legacy_rfqs_unmigrated": legacy_rfqs,
            },
            "source": "crm_db.opportunities via backend/sales/mail_pool_ai.py",
        }

    except Exception as e:
        logger.error(f"Error getting sync status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{rfq_id}")
async def get_rfq(rfq_id: str) -> Dict[str, Any]:
    """
    Get a single RFQ by spine opportunity _id or by its RFQ-YYYY-XXXXXX id.
    """
    rfq = spine_rfq.get_rfq(rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    return {
        "success": True,
        "rfq": rfq
    }


def mirror_rfq_to_spine(rfq_id: str, contact_email: Optional[str], title: Optional[str],
                        budget: Optional[float]) -> Optional[Dict[str, str]]:
    """
    Mirror a legacy RFQ into the canonical CRM spine: ensures a canonical Contact
    (by email) and creates a linked Opportunity + Project stub via
    crm_service.create_rfq. Touches only crm_db (testable in isolation).
    Returns {opportunity_id, project_id}.
    """
    try:
        from ..app.services import crm_service
    except ImportError:  # pragma: no cover
        from app.services import crm_service

    contact_id = None
    account_id = None
    if contact_email:
        contact, _ = crm_service.get_or_create_contact(
            contact_email, defaults={"metadata": {"source": "rfq"}}
        )
        contact_id = contact["_id"]
        account_id = contact.get("account_id")

    spine = crm_service.create_rfq({
        "title": title or rfq_id,
        "budget": budget or 0,
        "contact_id": contact_id,
        "account_id": account_id,
        "rfq_id": rfq_id,
    })
    return {
        "opportunity_id": spine["opportunity"]["_id"],
        "project_id": spine["project"]["_id"],
    }


@router.post("/")
async def create_rfq(rfq_data: RFQCreate) -> Dict[str, Any]:
    """
    Create an RFQ manually, directly on the CRM spine.

    This used to insert into email_automation.rfqs and then best-effort mirror
    to the spine. Now that the list reads the spine, writing the legacy row
    first would just recreate the drift this refactor removed — so the spine
    opportunity IS the RFQ, and there is no second copy to keep in step.
    """
    try:
        from ..app.services import crm_service
    except ImportError:  # pragma: no cover
        from app.services import crm_service

    rfq_id = generate_rfq_id()
    direction = (rfq_data.direction or "inbound").strip().lower()
    if direction not in ("inbound", "outbound"):
        raise HTTPException(status_code=400, detail="direction must be 'inbound' or 'outbound'")

    due_date = None
    if rfq_data.due_date:
        try:
            due_date = datetime.fromisoformat(rfq_data.due_date.replace("Z", "+00:00"))
        except ValueError:
            logger.warning(f"RFQ {rfq_id}: unparseable due_date {rfq_data.due_date!r}")

    # Resolve (or create) the counterparty this RFQ belongs to, so it lands on
    # the Account 360 page rather than floating unattached. Inbound: the
    # counterparty is the client lead (contact_email). Outbound: it's the
    # vendor we're asking for pricing (vendor_name) — there's often no
    # specific contact email on hand yet, only a vendor/company name.
    account_id = None
    contact_id = None
    contact_email = (rfq_data.contact_email or "").strip().lower()
    vendor_name = (rfq_data.vendor_name or "").strip()

    if direction == "outbound":
        if not vendor_name:
            raise HTTPException(
                status_code=400,
                detail="vendor_name is required for an outbound RFQ",
            )
        account, _ = crm_service.get_or_create_account(
            vendor_name,
            defaults={"account_type": "vendor", "metadata": {"source": "manual_rfq"}},
        )
        account_id = account["_id"]
        if contact_email:
            contact, _ = crm_service.get_or_create_contact(
                contact_email,
                defaults={"account_id": account_id, "metadata": {"source": "manual_rfq"}},
            )
            contact_id = contact["_id"]
    else:
        if not contact_email:
            raise HTTPException(
                status_code=400,
                detail="contact_email is required for an inbound RFQ",
            )
        contact, _ = crm_service.get_or_create_contact(
            contact_email,
            defaults={"metadata": {"source": "manual_rfq"}},
        )
        contact_id = contact["_id"]
        account_id = contact.get("account_id")

    spine = crm_service.create_rfq({
        "title": rfq_data.title,
        "account_id": account_id,
        "contact_id": contact_id,
        "budget": rfq_data.manual_value or 0,
        "description": rfq_data.description,
        "deadline": due_date,
        # Everything spine_rfq surfaces from metadata.rfq.
        "rfq_id": rfq_id,
        "direction": direction,
        "client_name": rfq_data.client_name,
        "currency": rfq_data.manual_currency,
        "priority": rfq_data.priority,
        "methodology": rfq_data.methodology,
        "loi": rfq_data.loi,
        "ir": rfq_data.ir,
        "country": rfq_data.country,
        "sample_size": rfq_data.sample_size,
        "created_by": "manual",
    })

    opportunity_id = spine["opportunity"]["_id"]

    # Keep the lead's rfq_ids back-reference working for the Leads page.
    if contact_email:
        email_leads_collection.update_one(
            {"email": contact_email},
            {"$addToSet": {"rfq_ids": rfq_id}}
        )

    return {
        "success": True,
        "message": f"RFQ {rfq_id} created successfully",
        "rfq": spine_rfq.get_rfq(opportunity_id),
        "opportunity_id": opportunity_id,
        "project_id": spine["project"]["_id"],
    }


@router.put("/{rfq_id}")
async def update_rfq(rfq_id: str, rfq_data: RFQUpdate) -> Dict[str, Any]:
    """
    Update an RFQ on the CRM spine.

    Status changes go through crm_service.set_opportunity_stage, so the spine's
    own rules apply: "won" activates the linked project and opens an invoice
    stub, "lost" requires a loss_reason, and every move lands on the account
    timeline. The old local VALID_STATUS_TRANSITIONS table is no longer the
    authority — the spine is.
    """
    try:
        from ..app.services import crm_service
    except ImportError:  # pragma: no cover
        from app.services import crm_service

    existing = spine_rfq.get_rfq(rfq_id)
    if not existing:
        raise HTTPException(status_code=404, detail="RFQ not found")

    opportunity_id = existing["opportunity_id"]
    current_status = existing.get("status", "pending")

    # --- scalar fields live on the opportunity -----------------------------
    update_doc: Dict[str, Any] = {}
    if rfq_data.title is not None:
        update_doc["title"] = rfq_data.title
    if rfq_data.description is not None:
        update_doc["description"] = rfq_data.description
    if rfq_data.manual_value is not None:
        update_doc["amount"] = rfq_data.manual_value
    if rfq_data.manual_currency is not None:
        update_doc["currency"] = rfq_data.manual_currency
    if rfq_data.priority is not None:
        update_doc["priority"] = rfq_data.priority
    if rfq_data.due_date is not None:
        try:
            update_doc["due_date"] = datetime.fromisoformat(
                rfq_data.due_date.replace("Z", "+00:00")
            )
        except ValueError:
            logger.warning(f"RFQ {rfq_id}: unparseable due_date {rfq_data.due_date!r}")

    # --- research-brief fields live under metadata.rfq ---------------------
    brief_fields = {
        "methodology": rfq_data.methodology,
        "loi": rfq_data.loi,
        "ir": rfq_data.ir,
        "country": rfq_data.country,
        "sample_size": rfq_data.sample_size,
        "target_audience": rfq_data.target_audience,
        "timeline": rfq_data.timeline,
        "study_type": rfq_data.study_type,
        "budget": rfq_data.budget,
        "additional_requirements": rfq_data.additional_requirements,
        "direction": rfq_data.direction,
        "client_name": rfq_data.client_name,
    }
    brief_updates = {
        f"metadata.rfq.{k}": v for k, v in brief_fields.items() if v is not None
    }

    if update_doc or brief_updates:
        crm_service._col("opportunities").update_one(
            {"_id": ObjectId(opportunity_id)},
            {"$set": {**update_doc, **brief_updates, "updated_at": datetime.utcnow()}},
        )

    # --- status change goes through the spine state machine ----------------
    stage_result = None
    if rfq_data.status is not None and rfq_data.status != current_status:
        stage = spine_rfq.legacy_status_to_stage(rfq_data.status)
        if not stage:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown status '{rfq_data.status}'. "
                       f"Valid: pending, quoted, negotiating, won, lost",
            )
        try:
            stage_result = crm_service.set_opportunity_stage(
                opportunity_id,
                stage,
                loss_reason=rfq_data.loss_reason,
            )
        except ValueError as e:
            # Raised for an unknown stage or a "lost" move with no reason given.
            raise HTTPException(status_code=400, detail=str(e))

    updated = spine_rfq.get_rfq(opportunity_id)

    response: Dict[str, Any] = {
        "success": True,
        "message": "RFQ updated successfully",
        "rfq": updated,
    }

    # mark_opportunity_won activates the project and opens an invoice stub;
    # surface those ids so the UI can link straight to them.
    if stage_result and rfq_data.status == "won":
        if stage_result.get("project"):
            response["project_activated"] = True
            response["project_id"] = stage_result["project"].get("_id")
        if stage_result.get("invoice"):
            response["invoice_created"] = True
            response["invoice_id"] = stage_result["invoice"].get("_id")
        response["message"] = "RFQ won — project activated"

    return response


@router.delete("/{rfq_id}")
async def delete_rfq(rfq_id: str) -> Dict[str, Any]:
    """
    Soft delete an RFQ (spine opportunity).

    Guards against deletion when the RFQ has already produced an estimate or an
    invoice — those are financial records, and orphaning them loses the audit
    trail. Deletion is always soft: the opportunity anchors historical
    activities on the account timeline.
    """
    try:
        from ..app.services import crm_service
    except ImportError:  # pragma: no cover
        from app.services import crm_service

    rfq = spine_rfq.get_rfq(rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    blocker = _deletion_blocker(rfq)
    if blocker:
        raise HTTPException(status_code=400, detail=blocker)

    if rfq.get("contact_email"):
        email_leads_collection.update_one(
            {"email": rfq["contact_email"]},
            {"$pull": {"rfq_ids": rfq["rfq_id"]}}
        )

    crm_service._col("opportunities").update_one(
        {"_id": ObjectId(rfq["opportunity_id"])},
        {"$set": {
            "is_deleted": True,
            "deleted_at": datetime.utcnow(),
            "deleted_by": "api_user",  # TODO: Replace with actual user from auth
        }}
    )

    logger.info(f"Soft deleted RFQ {rfq['rfq_id']} (opportunity {rfq['opportunity_id']})")

    return {
        "success": True,
        "message": f"RFQ {rfq['rfq_id']} deleted successfully"
    }


def _deletion_blocker(rfq: Dict[str, Any]) -> Optional[str]:
    """Return a human-readable reason this RFQ must not be deleted, or None."""
    estimate_id = rfq.get("estimate_id")
    if estimate_id:
        try:
            linked = estimates_collection.find_one({"_id": ObjectId(estimate_id)})
        except Exception:
            linked = None
        if linked:
            return (
                f"Cannot delete RFQ: linked to estimate "
                f"{linked.get('estimate_number', estimate_id)}. Delete the estimate first."
            )

    invoice_id = rfq.get("invoice_id")
    if invoice_id:
        try:
            linked = invoices_collection.find_one({"_id": ObjectId(invoice_id)})
        except Exception:
            linked = None
        if linked:
            return (
                f"Cannot delete RFQ: linked to invoice "
                f"{linked.get('invoice_number', invoice_id)}. Delete the invoice first."
            )

    return None


@router.post("/bulk-delete")
async def bulk_delete_rfqs(data: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Soft delete multiple RFQs, skipping any with linked estimates or invoices."""
    try:
        from ..app.services import crm_service
    except ImportError:  # pragma: no cover
        from app.services import crm_service

    ids = data.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs provided")

    deleted_count = 0
    skipped = []

    for rfq_ref in ids:
        rfq = spine_rfq.get_rfq(rfq_ref)
        if not rfq:
            skipped.append({"rfq_id": rfq_ref, "reason": "not found"})
            continue

        blocker = _deletion_blocker(rfq)
        if blocker:
            skipped.append({"rfq_id": rfq["rfq_id"], "reason": blocker})
            continue

        if rfq.get("contact_email"):
            email_leads_collection.update_one(
                {"email": rfq["contact_email"]},
                {"$pull": {"rfq_ids": rfq["rfq_id"]}}
            )

        crm_service._col("opportunities").update_one(
            {"_id": ObjectId(rfq["opportunity_id"])},
            {"$set": {
                "is_deleted": True,
                "deleted_at": datetime.utcnow(),
                "deleted_by": "api_user",
            }}
        )
        deleted_count += 1

    response = {
        "success": True,
        "message": f"Successfully deleted {deleted_count} RFQs",
        "deleted_count": deleted_count,
    }
    if skipped:
        response["skipped"] = skipped
        response["message"] += f" ({len(skipped)} skipped)"

    return response


@router.get("/by-lead/{lead_id}")
async def get_rfqs_by_lead(lead_id: str) -> Dict[str, Any]:
    """
    Get all RFQs for a lead, by spine contact id or by email address.

    Reads the spine: opportunities carry contact_id, so resolve the lead to a
    canonical contact and query on that.
    """
    try:
        from ..app.services import crm_service
    except ImportError:  # pragma: no cover
        from app.services import crm_service

    contact_id = None
    email = lead_id if "@" in lead_id else None

    if not email:
        # Could already be a spine contact id...
        contact = crm_service.get("contacts", lead_id) if len(lead_id) == 24 else None
        if contact:
            contact_id = contact["_id"]
        else:
            # ...otherwise a legacy lead id; resolve it to an email.
            try:
                lead = email_leads_collection.find_one({"_id": ObjectId(lead_id)})
                if lead:
                    email = lead.get("email")
            except Exception:
                pass

    if not contact_id and email:
        contact = crm_service.find_contact_by_email(email)
        if contact:
            contact_id = contact["_id"]

    if not contact_id:
        return {"success": True, "rfqs": [], "count": 0}

    opportunities = list(
        crm_service._col("opportunities").find({
            "contact_id": contact_id,
            "is_deleted": {"$ne": True},
            "$or": [
                {"stage": "rfq"},
                {"metadata.source": "rfq"},
                {"metadata.rfq": {"$exists": True}},
            ],
        }).sort("created_at", DESCENDING)
    )

    rfqs = [spine_rfq.opportunity_to_rfq(o) for o in opportunities]

    return {
        "success": True,
        "rfqs": rfqs,
        "count": len(rfqs)
    }


@router.post("/{rfq_id}/link-email")
async def link_email_to_rfq(
    rfq_id: str,
    message_id: str = Body(..., embed=True),
    subject: str = Body("", embed=True),
    inbox: str = Body("", embed=True)
) -> Dict[str, Any]:
    """
    Link an email to an existing RFQ.
    """
    try:
        from ..app.services import crm_service
    except ImportError:  # pragma: no cover
        from app.services import crm_service

    rfq = spine_rfq.get_rfq(rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    source_email = {
        "message_id": message_id,
        "subject": subject,
        "inbox": inbox,
        "date": datetime.utcnow(),
        "extracted_amount": None
    }

    # Provenance lives under metadata.rfq alongside the AI-extracted brief.
    crm_service._col("opportunities").update_one(
        {"_id": ObjectId(rfq["opportunity_id"])},
        {
            "$push": {"metadata.rfq.source_emails": source_email},
            "$set": {"updated_at": datetime.utcnow()}
        }
    )

    return {
        "success": True,
        "message": "Email linked to RFQ successfully"
    }


# =============================================================================
# RFQ Conversion Endpoints - Convert RFQ to Estimate or Invoice
# =============================================================================

class RFQConversionRequest(BaseModel):
    """Request model for RFQ conversion."""
    customer_id: Optional[str] = Field(None, description="Customer ID to bill. If not provided, will try to match from RFQ client info")
    unit_price: Optional[float] = Field(None, description="Price per complete. If not provided, calculated from RFQ value / sample_size")
    discount_percent: float = Field(0, description="Discount percentage to apply")
    tax_percent: float = Field(18, description="Tax/GST percentage")
    notes: Optional[str] = Field(None, description="Additional notes for estimate/invoice")
    due_days: int = Field(30, description="Payment due in days")
    line_items: Optional[List[Dict[str, Any]]] = Field(None, description="Custom line items. If not provided, auto-generated from RFQ")


class ConversionResponse(BaseModel):
    """Response model for RFQ conversion."""
    success: bool
    message: str
    document_type: str
    document_id: str
    document_number: str
    rfq_id: str
    total_amount: float


def _generate_line_items_from_rfq(rfq: Dict[str, Any], unit_price: Optional[float] = None) -> List[Dict[str, Any]]:
    """Generate invoice line items from RFQ data."""
    sample_size = rfq.get("sample_size", 0) or 0
    rfq_value = rfq.get("manual_value") or rfq.get("extracted_value") or 0
    
    # Calculate unit price if not provided
    if unit_price is None and sample_size > 0:
        unit_price = rfq_value / sample_size
    elif unit_price is None:
        unit_price = rfq_value
    
    items = []
    
    # Main survey line item
    methodology = rfq.get("methodology", "Online Survey")
    country = rfq.get("country", "")
    loi = rfq.get("loi", 0)
    ir = rfq.get("ir", 0)
    
    description = f"{methodology}"
    if country:
        description += f" - {country}"
    if loi:
        description += f" | LOI: {loi} mins"
    if ir:
        description += f" | IR: {ir}%"
    
    items.append({
        "description": description,
        "quantity": sample_size if sample_size > 0 else 1,
        "unit": "completes" if sample_size > 0 else "project",
        "unit_price": round(unit_price, 2),
        "amount": round(unit_price * (sample_size if sample_size > 0 else 1), 2)
    })
    
    return items


def _find_or_create_customer(rfq: Dict[str, Any]) -> Optional[str]:
    """
    Resolve the finance customer for an RFQ, or None if there is no match.

    Reads account_name/contact_email — the fields the spine adapter actually
    populates. It previously read client_name/client_email, which no RFQ
    document has ever carried, so it always returned None and every conversion
    without an explicit customer_id failed with "Customer not found".
    """
    account_name = (rfq.get("account_name") or rfq.get("sender_company") or "").strip()
    contact_email = (rfq.get("contact_email") or "").strip()

    if not account_name and not contact_email:
        return None

    if contact_email:
        customer = customers_collection.find_one(
            {"email": {"$regex": f"^{re.escape(contact_email)}$", "$options": "i"}}
        )
        if customer:
            return str(customer["_id"])

    if account_name:
        customer = customers_collection.find_one(
            {"name": {"$regex": f"^{re.escape(account_name)}$", "$options": "i"}}
        )
        if customer:
            return str(customer["_id"])

    return None


def _get_next_document_number(collection, prefix: str) -> str:
    """Generate next document number."""
    today = datetime.utcnow()
    year_month = today.strftime("%Y%m")
    
    # Find the highest number for this month
    pattern = f"^{prefix}-{year_month}-"
    last_doc = collection.find_one(
        {"document_number": {"$regex": pattern}},
        sort=[("document_number", DESCENDING)]
    )
    
    if last_doc:
        try:
            last_num = int(last_doc["document_number"].split("-")[-1])
            next_num = last_num + 1
        except:
            next_num = 1
    else:
        next_num = 1
    
    return f"{prefix}-{year_month}-{next_num:04d}"


@router.post("/{rfq_id}/convert-to-estimate", response_model=ConversionResponse)
async def convert_rfq_to_estimate(
    rfq_id: str,
    request: RFQConversionRequest
) -> ConversionResponse:
    """
    Convert an RFQ to an Estimate.
    
    This creates an estimate document in the finance system based on the RFQ details.
    The RFQ status is updated to 'quoted'.
    """
    rfq = spine_rfq.get_rfq(rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    # Determine customer
    customer_id = request.customer_id
    if not customer_id:
        customer_id = _find_or_create_customer(rfq)
    
    if not customer_id:
        raise HTTPException(
            status_code=400, 
            detail="Customer not found. Please provide customer_id or ensure RFQ has valid client information."
        )
    
    # Verify customer exists
    try:
        customer = customers_collection.find_one({"_id": ObjectId(customer_id)})
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
    except:
        raise HTTPException(status_code=400, detail="Invalid customer_id format")
    
    # Generate line items
    if request.line_items:
        line_items = request.line_items
    else:
        line_items = _generate_line_items_from_rfq(rfq, request.unit_price)
    
    # Calculate totals
    subtotal = sum(item.get("amount", 0) for item in line_items)
    discount_amount = subtotal * (request.discount_percent / 100)
    taxable_amount = subtotal - discount_amount
    tax_amount = taxable_amount * (request.tax_percent / 100)
    total = taxable_amount + tax_amount
    
    # Generate estimate number
    estimate_number = _get_next_document_number(estimates_collection, "EST")
    
    # Create estimate document
    now = datetime.utcnow()
    estimate = {
        "document_number": estimate_number,
        "estimate_number": estimate_number,
        "customer_id": customer_id,
        "customer_name": customer.get("name", ""),
        "rfq_id": rfq["rfq_id"],
        "rfq_object_id": rfq["opportunity_id"],
        "opportunity_id": rfq["opportunity_id"],
        "project_name": rfq.get("project_name", ""),
        "status": "draft",
        "date": now,
        "expiry_date": now + timedelta(days=request.due_days),
        "line_items": line_items,
        "subtotal": round(subtotal, 2),
        "discount_percent": request.discount_percent,
        "discount_amount": round(discount_amount, 2),
        "tax_percent": request.tax_percent,
        "tax_amount": round(tax_amount, 2),
        "total": round(total, 2),
        "notes": request.notes or f"Estimate generated from RFQ: {rfq.get('project_name', rfq_id)}",
        "terms": f"Valid for {request.due_days} days from date of issue.",
        "created_at": now,
        "updated_at": now
    }
    
    result = estimates_collection.insert_one(estimate)
    estimate_id = str(result.inserted_id)
    
    # Move the spine opportunity to "proposal" and cross-link the estimate.
    try:
        from ..app.services import crm_service
    except ImportError:  # pragma: no cover
        from app.services import crm_service

    crm_service._col("opportunities").update_one(
        {"_id": ObjectId(rfq["opportunity_id"])},
        {
            "$set": {
                "stage": "proposal",
                "amount": round(total, 2),
                "quoted_at": now,
                "updated_at": now,
                "metadata.rfq.estimate_id": estimate_id,
                "metadata.rfq.estimate_number": estimate_number,
            }
        }
    )
    
    logger.info(f"Converted RFQ {rfq_id} to Estimate {estimate_number}")
    
    return ConversionResponse(
        success=True,
        message=f"RFQ converted to estimate successfully",
        document_type="estimate",
        document_id=estimate_id,
        document_number=estimate_number,
        rfq_id=rfq["rfq_id"],
        total_amount=round(total, 2)
    )


@router.post("/{rfq_id}/convert-to-invoice", response_model=ConversionResponse)
async def convert_rfq_to_invoice(
    rfq_id: str,
    request: RFQConversionRequest
) -> ConversionResponse:
    """
    Convert an RFQ directly to an Invoice.
    
    This creates an invoice document in the finance system based on the RFQ details.
    The RFQ status is updated to 'won'.
    Use this when a deal is confirmed and you want to skip the estimate stage.
    """
    rfq = spine_rfq.get_rfq(rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    # Determine customer
    customer_id = request.customer_id
    if not customer_id:
        customer_id = _find_or_create_customer(rfq)
    
    if not customer_id:
        raise HTTPException(
            status_code=400, 
            detail="Customer not found. Please provide customer_id or ensure RFQ has valid client information."
        )
    
    # Verify customer exists
    try:
        customer = customers_collection.find_one({"_id": ObjectId(customer_id)})
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
    except:
        raise HTTPException(status_code=400, detail="Invalid customer_id format")
    
    # Generate line items
    if request.line_items:
        line_items = request.line_items
    else:
        line_items = _generate_line_items_from_rfq(rfq, request.unit_price)
    
    # Calculate totals
    subtotal = sum(item.get("amount", 0) for item in line_items)
    discount_amount = subtotal * (request.discount_percent / 100)
    taxable_amount = subtotal - discount_amount
    tax_amount = taxable_amount * (request.tax_percent / 100)
    total = taxable_amount + tax_amount
    
    # Generate invoice number
    invoice_number = _get_next_document_number(invoices_collection, "INV")
    
    # Create invoice document
    now = datetime.utcnow()
    invoice = {
        "invoice_number": invoice_number,
        "customer_id": customer_id,
        "customer_name": customer.get("name", ""),
        "rfq_id": rfq["rfq_id"],
        "rfq_object_id": rfq["opportunity_id"],
        "opportunity_id": rfq["opportunity_id"],
        "project_name": rfq.get("project_name", ""),
        "project_id": rfq.get("project_id"),  # Link to project if exists
        "status": "pending",
        "date": now,
        "due_date": now + timedelta(days=request.due_days),
        "line_items": line_items,
        "subtotal": round(subtotal, 2),
        "discount_percent": request.discount_percent,
        "discount_amount": round(discount_amount, 2),
        "tax_percent": request.tax_percent,
        "tax_amount": round(tax_amount, 2),
        "total": round(total, 2),
        "amount_paid": 0,
        "balance_due": round(total, 2),
        "notes": request.notes or f"Invoice generated from RFQ: {rfq.get('project_name', rfq_id)}",
        "terms": f"Payment due within {request.due_days} days.",
        "created_at": now,
        "updated_at": now
    }
    
    result = invoices_collection.insert_one(invoice)
    invoice_id = str(result.inserted_id)
    
    # Update customer receivables
    customers_collection.update_one(
        {"_id": ObjectId(customer_id)},
        {
            "$inc": {"total_receivables": round(total, 2)},
            "$set": {"updated_at": now}
        }
    )
    
    # Invoicing an RFQ means the deal is won. Go through the spine so the linked
    # project is activated and the win lands on the account timeline, then
    # cross-link the finance invoice.
    try:
        from ..app.services import crm_service
    except ImportError:  # pragma: no cover
        from app.services import crm_service

    try:
        crm_service.set_opportunity_stage(rfq["opportunity_id"], "won")
    except Exception as e:
        logger.warning(
            f"RFQ {rfq_id}: invoice created but spine win transition failed: {e}"
        )

    crm_service._col("opportunities").update_one(
        {"_id": ObjectId(rfq["opportunity_id"])},
        {
            "$set": {
                "amount": round(total, 2),
                "invoice_id": invoice_id,
                "invoiced_at": now,
                "updated_at": now,
                "metadata.rfq.invoice_id": invoice_id,
                "metadata.rfq.invoice_number": invoice_number,
            }
        }
    )
    
    logger.info(f"Converted RFQ {rfq_id} to Invoice {invoice_number}")
    
    return ConversionResponse(
        success=True,
        message=f"RFQ converted to invoice successfully",
        document_type="invoice",
        document_id=invoice_id,
        document_number=invoice_number,
        rfq_id=rfq["rfq_id"],
        total_amount=round(total, 2)
    )


@router.post("/estimate/{estimate_id}/convert-to-invoice", response_model=ConversionResponse)
async def convert_estimate_to_invoice(
    estimate_id: str,
    due_days: int = Query(30, description="Payment due in days")
) -> ConversionResponse:
    """
    Convert an Estimate to an Invoice.
    
    This creates an invoice from an existing estimate and updates the linked RFQ status to 'won'.
    """
    # Find the estimate
    try:
        estimate = estimates_collection.find_one({"_id": ObjectId(estimate_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid estimate_id format")
    
    if not estimate:
        raise HTTPException(status_code=404, detail="Estimate not found")
    
    # Generate invoice number
    invoice_number = _get_next_document_number(invoices_collection, "INV")
    
    now = datetime.utcnow()
    
    # Create invoice from estimate
    invoice = {
        "invoice_number": invoice_number,
        "customer_id": estimate.get("customer_id"),
        "customer_name": estimate.get("customer_name", ""),
        "rfq_id": estimate.get("rfq_id"),
        "rfq_object_id": estimate.get("rfq_object_id"),
        "estimate_id": estimate_id,
        "estimate_number": estimate.get("estimate_number"),
        "project_name": estimate.get("project_name", ""),
        "status": "pending",
        "date": now,
        "due_date": now + timedelta(days=due_days),
        "line_items": estimate.get("line_items", []),
        "subtotal": estimate.get("subtotal", 0),
        "discount_percent": estimate.get("discount_percent", 0),
        "discount_amount": estimate.get("discount_amount", 0),
        "tax_percent": estimate.get("tax_percent", 18),
        "tax_amount": estimate.get("tax_amount", 0),
        "total": estimate.get("total", 0),
        "amount_paid": 0,
        "balance_due": estimate.get("total", 0),
        "notes": estimate.get("notes", ""),
        "terms": f"Payment due within {due_days} days.",
        "created_at": now,
        "updated_at": now
    }
    
    result = invoices_collection.insert_one(invoice)
    invoice_id = str(result.inserted_id)
    total = estimate.get("total", 0)
    
    # Update estimate status
    estimates_collection.update_one(
        {"_id": ObjectId(estimate_id)},
        {
            "$set": {
                "status": "accepted",
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "converted_at": now,
                "updated_at": now
            }
        }
    )
    
    # Update customer receivables
    customer_id = estimate.get("customer_id")
    if customer_id:
        try:
            customers_collection.update_one(
                {"_id": ObjectId(customer_id)},
                {
                    "$inc": {"total_receivables": round(total, 2)},
                    "$set": {"updated_at": now}
                }
            )
        except:
            pass
    
    # Estimate -> invoice means the deal is won. rfq_object_id now holds the
    # spine opportunity id (older estimates hold a legacy rfqs _id, which no
    # longer resolves — those simply skip the transition rather than erroring).
    opportunity_id = estimate.get("opportunity_id") or estimate.get("rfq_object_id")
    if opportunity_id:
        try:
            from ..app.services import crm_service
        except ImportError:  # pragma: no cover
            from app.services import crm_service

        try:
            crm_service.set_opportunity_stage(opportunity_id, "won")
            crm_service._col("opportunities").update_one(
                {"_id": ObjectId(opportunity_id)},
                {
                    "$set": {
                        "amount": round(total, 2),
                        "invoice_id": invoice_id,
                        "invoiced_at": now,
                        "updated_at": now,
                        "metadata.rfq.invoice_id": invoice_id,
                        "metadata.rfq.invoice_number": invoice_number,
                    }
                }
            )
        except Exception as e:
            logger.warning(
                f"Estimate {estimate.get('estimate_number')}: invoice created but "
                f"spine opportunity {opportunity_id} not updated: {e}"
            )

    logger.info(f"Converted Estimate {estimate_id} to Invoice {invoice_number}")
    
    return ConversionResponse(
        success=True,
        message=f"Estimate converted to invoice successfully",
        document_type="invoice",
        document_id=invoice_id,
        document_number=invoice_number,
        rfq_id=estimate.get("rfq_id", ""),
        total_amount=round(total, 2)
    )


# =============================================================================
# Gmail Email to RFQ Sync - Convert classified Gmail emails to RFQs
# =============================================================================

def extract_rfq_details_from_summary(summary: str, subject: str) -> Dict[str, Any]:
    """Extract RFQ details from AI summary and subject"""
    import re
    
    details = {
        "loi": None,
        "ir": None,
        "sample_size": None,
        "country": None,
        "methodology": None,
        "study_type": None
    }
    
    text = f"{subject} {summary}".lower()
    
    # Extract LOI
    loi_patterns = [
        r'(\d+)\s*(?:min(?:ute)?s?)\s*(?:loi|interview)',
        r'loi[:\s]+(\d+)',
        r'(\d+)\s*min\b'
    ]
    for pattern in loi_patterns:
        match = re.search(pattern, text)
        if match:
            details["loi"] = int(match.group(1))
            break
    
    # Extract IR
    ir_patterns = [
        r'(\d+(?:\.\d+)?)\s*%\s*(?:ir|incidence)',
        r'ir[:\s]+(\d+(?:\.\d+)?)',
        r'incidence[:\s]+(\d+(?:\.\d+)?)'
    ]
    for pattern in ir_patterns:
        match = re.search(pattern, text)
        if match:
            details["ir"] = float(match.group(1))
            break
    
    # Extract sample size
    n_patterns = [
        r'n\s*[=:]\s*(\d+)',
        r'(\d+)\s*(?:completes?|respondents?|sample)',
        r'sample\s*(?:size)?[:\s]*(\d+)'
    ]
    for pattern in n_patterns:
        match = re.search(pattern, text)
        if match:
            details["sample_size"] = int(match.group(1))
            break
    
    # Extract country
    countries = ["us", "usa", "uk", "india", "germany", "france", "brazil", "canada", "australia", "japan", "china", "global", "multi-country", "apac", "emea", "latam"]
    for country in countries:
        if country in text:
            details["country"] = country.upper()
            break
    
    # Extract methodology
    methodologies = ["cati", "cawi", "f2f", "face to face", "online", "phone", "web", "panel", "idi", "focus group"]
    for method in methodologies:
        if method in text:
            details["methodology"] = method.upper()
            break
    
    # Extract study type
    if "healthcare" in text or "hcp" in text or "physician" in text:
        details["study_type"] = "Healthcare"
    elif "b2b" in text or "business" in text:
        details["study_type"] = "B2B"
    elif "it " in text or "technology" in text:
        details["study_type"] = "IT"
    elif "consumer" in text or "b2c" in text:
        details["study_type"] = "Consumer"
    
    return details
