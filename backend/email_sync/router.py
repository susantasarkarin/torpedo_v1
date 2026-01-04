"""
EMAIL SYNC API ROUTER
=====================

FastAPI router for email sync endpoints.

Endpoints:
- Mailbox management (CRUD)
- Alias management
- Sync controls (trigger, pause, resume)
- Status and metrics
- Email retrieval
- Re-categorization of emails
- Background backfill
"""

import logging
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query, Path, BackgroundTasks
from pydantic import BaseModel, EmailStr, Field
from pymongo import MongoClient
import os

from .orchestrator import EmailSyncOrchestrator
from .models import ProviderType, SyncStatus, EmailCategory
from .storage import EmailStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email-sync", tags=["Email Sync"])

# Background task tracking
_background_tasks = {}

# =========================================================================
# DEPENDENCY
# =========================================================================

_orchestrator: Optional[EmailSyncOrchestrator] = None


def get_orchestrator() -> EmailSyncOrchestrator:
    """Get or create orchestrator instance"""
    global _orchestrator
    
    if _orchestrator is None:
        mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        db_name = os.getenv("MONGODB_DB", "email_automation")
        _orchestrator = EmailSyncOrchestrator(mongo_uri=mongo_uri, db_name=db_name)
    
    return _orchestrator


def get_storage(orch: EmailSyncOrchestrator = Depends(get_orchestrator)) -> EmailStorage:
    """Get storage instance"""
    return orch.storage


# =========================================================================
# REQUEST/RESPONSE MODELS
# =========================================================================

class MailboxCreateRequest(BaseModel):
    email: EmailStr
    provider: str = Field(..., description="Provider type: gmail or imap")
    display_name: Optional[str] = None
    credentials: Optional[Dict[str, Any]] = Field(default=None, description="Auth credentials")
    auto_start_backfill: bool = True
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "sales@company.com",
                "provider": "gmail",
                "display_name": "Sales Team",
                "credentials": {
                    "access_token": "ya29...",
                    "refresh_token": "1//...",
                },
                "auto_start_backfill": True
            }
        }


class MailboxUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    sync_enabled: Optional[bool] = None
    is_active: Optional[bool] = None
    credentials: Optional[Dict[str, Any]] = None


class AliasCreateRequest(BaseModel):
    alias_email: EmailStr
    display_name: Optional[str] = None
    is_primary: bool = False
    signature: Optional[str] = None  # HTML signature for this alias


class MailboxResponse(BaseModel):
    mailbox_id: str
    email: str
    display_name: Optional[str]
    provider: str
    sync_enabled: bool
    is_active: bool
    last_sync_at: Optional[datetime]
    sync_status: str
    email_count: Optional[int] = None


class MailboxDetailResponse(MailboxResponse):
    backfill_progress: Dict[str, Any]
    aliases: List[Dict[str, Any]]
    rate_limit: Dict[str, Any]
    error: Optional[str]


class HealthResponse(BaseModel):
    timestamp: str
    workers: Dict[str, Any]
    mailboxes: Dict[str, int]
    sync_states: Dict[str, int]
    emails: Dict[str, int]
    global_limits: Dict[str, Any]
    healthy: bool


class EmailResponse(BaseModel):
    id: str
    mailbox_id: str
    alias_id: Optional[str]
    provider_message_id: str
    from_email: str
    from_name: Optional[str]
    to_addresses: List[str]
    cc_addresses: List[str]
    subject: str
    body_preview: str
    received_at: datetime
    category: Optional[str]
    category_confidence: Optional[float]
    thread_id: Optional[str]
    has_attachments: bool
    is_processed: bool


class EmailListResponse(BaseModel):
    emails: List[EmailResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


# =========================================================================
# MAILBOX ENDPOINTS
# =========================================================================

@router.post("/mailboxes", response_model=Dict[str, Any])
async def create_mailbox(
    request: MailboxCreateRequest,
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """
    Register a new mailbox for email sync.
    
    The mailbox will be created and optionally trigger a historical backfill.
    """
    try:
        provider = ProviderType(request.provider)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider. Must be one of: {[p.value for p in ProviderType]}"
        )
    
    result = orch.register_mailbox(
        email=request.email,
        provider=provider,
        display_name=request.display_name,
        credentials=request.credentials,
        auto_start_backfill=request.auto_start_backfill
    )
    
    return result


@router.get("/mailboxes", response_model=List[MailboxResponse])
async def list_mailboxes(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    active_only: bool = Query(True),
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """List all registered mailboxes"""
    mailboxes = orch.list_mailboxes(skip=skip, limit=limit, active_only=active_only)
    return mailboxes


@router.get("/mailboxes/{mailbox_id}", response_model=MailboxDetailResponse)
async def get_mailbox(
    mailbox_id: str = Path(..., description="Mailbox ID"),
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """Get detailed status for a specific mailbox"""
    status = orch.get_mailbox_status(mailbox_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    
    return status


@router.patch("/mailboxes/{mailbox_id}")
async def update_mailbox(
    mailbox_id: str,
    request: MailboxUpdateRequest,
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """Update mailbox settings"""
    success = orch.update_mailbox(
        mailbox_id,
        **request.dict(exclude_none=True)
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Mailbox not found or no changes")
    
    return {"success": True, "message": "Mailbox updated"}


@router.delete("/mailboxes/{mailbox_id}")
async def delete_mailbox(
    mailbox_id: str,
    delete_emails: bool = Query(False, description="Also delete synced emails"),
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """Delete a mailbox"""
    success = orch.delete_mailbox(mailbox_id, delete_emails=delete_emails)
    
    if not success:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    
    return {"success": True, "message": "Mailbox deleted"}


# =========================================================================
# ALIAS ENDPOINTS
# =========================================================================

@router.post("/mailboxes/{mailbox_id}/aliases")
async def create_alias(
    mailbox_id: str,
    request: AliasCreateRequest,
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """Register an alias for a mailbox"""
    # Verify mailbox exists
    status = orch.get_mailbox_status(mailbox_id)
    if not status:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    
    result = orch.register_alias(
        mailbox_id=mailbox_id,
        alias_email=request.alias_email,
        is_primary=request.is_primary,
        display_name=request.display_name,
        signature=request.signature
    )
    
    return result


@router.get("/mailboxes/{mailbox_id}/aliases")
async def list_aliases(
    mailbox_id: str,
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """List aliases for a mailbox"""
    aliases = list(orch.aliases.find(
        {"mailbox_id": mailbox_id},
        {"_id": 1, "alias_email": 1, "display_name": 1, "is_primary": 1, "is_active": 1, "signature": 1}
    ))
    
    return [
        {
            "alias_id": str(a["_id"]),
            "alias_email": a["alias_email"],
            "display_name": a.get("display_name"),
            "is_primary": a.get("is_primary", False),
            "is_active": a.get("is_active", True),
            "signature": a.get("signature", "")
        }
        for a in aliases
    ]


@router.delete("/mailboxes/{mailbox_id}/aliases/{alias_id}")
async def delete_alias(
    mailbox_id: str,
    alias_id: str,
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """Delete an alias"""
    from bson import ObjectId
    
    result = orch.aliases.delete_one({
        "_id": ObjectId(alias_id),
        "mailbox_id": mailbox_id
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Alias not found")
    
    return {"success": True, "message": "Alias deleted"}


class AliasUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    signature: Optional[str] = None
    is_primary: Optional[bool] = None


@router.put("/mailboxes/{mailbox_id}/aliases/{alias_id}")
async def update_alias(
    mailbox_id: str,
    alias_id: str,
    request: AliasUpdateRequest,
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """Update an alias (display name, signature, etc.)"""
    from bson import ObjectId
    
    # Build update dict
    updates = {}
    if request.display_name is not None:
        updates["display_name"] = request.display_name
    if request.signature is not None:
        updates["signature"] = request.signature
    if request.is_primary is not None:
        updates["is_primary"] = request.is_primary
    
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    result = orch.aliases.update_one(
        {"_id": ObjectId(alias_id), "mailbox_id": mailbox_id},
        {"$set": updates}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Alias not found")
    
    return {"success": True, "message": "Alias updated"}


# =========================================================================
# SYNC CONTROL ENDPOINTS
# =========================================================================

@router.post("/mailboxes/{mailbox_id}/backfill")
async def trigger_backfill(
    mailbox_id: str,
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """Manually trigger a full historical backfill"""
    result = orch.trigger_backfill(mailbox_id)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    
    return result


@router.post("/mailboxes/{mailbox_id}/sync")
async def trigger_sync(
    mailbox_id: str,
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """Manually trigger an incremental sync"""
    result = orch.trigger_incremental_sync(mailbox_id)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    
    return result


@router.post("/mailboxes/{mailbox_id}/pause")
async def pause_sync(
    mailbox_id: str,
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """Pause sync for a mailbox"""
    success = orch.pause_sync(mailbox_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to pause sync")
    
    return {"success": True, "message": "Sync paused"}


@router.post("/mailboxes/{mailbox_id}/resume")
async def resume_sync(
    mailbox_id: str,
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """Resume sync for a mailbox"""
    success = orch.resume_sync(mailbox_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to resume sync")
    
    return {"success": True, "message": "Sync resumed"}


# =========================================================================
# EMAIL ENDPOINTS
# =========================================================================

@router.get("/mailboxes/{mailbox_id}/emails", response_model=EmailListResponse)
async def list_emails(
    mailbox_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    category: Optional[str] = Query(None, description="Filter by category"),
    unprocessed_only: bool = Query(False),
    search: Optional[str] = Query(None, description="Search in subject/body"),
    storage: EmailStorage = Depends(get_storage)
):
    """List emails for a mailbox"""
    skip = (page - 1) * page_size
    
    # Build query
    query: Dict[str, Any] = {"mailbox_id": mailbox_id}
    
    if category:
        query["category"] = category
    
    if unprocessed_only:
        query["is_processed"] = False
    
    if search:
        query["$or"] = [
            {"subject": {"$regex": search, "$options": "i"}},
            {"body_preview": {"$regex": search, "$options": "i"}}
        ]
    
    # Get emails
    emails = list(storage.emails.find(query)
        .sort("received_at", -1)
        .skip(skip)
        .limit(page_size + 1))  # +1 to check has_more
    
    has_more = len(emails) > page_size
    if has_more:
        emails = emails[:page_size]
    
    # Get total
    total = storage.emails.count_documents(query)
    
    # Transform
    result = []
    for e in emails:
        result.append(EmailResponse(
            id=str(e["_id"]),
            mailbox_id=e["mailbox_id"],
            alias_id=e.get("alias_id"),
            provider_message_id=e["provider_message_id"],
            from_email=e.get("from_email", ""),
            from_name=e.get("from_name"),
            to_addresses=e.get("to_addresses", []),
            cc_addresses=e.get("cc_addresses", []),
            subject=e.get("subject", ""),
            body_preview=e.get("body_preview", "")[:500],
            received_at=e.get("received_at", datetime.utcnow()),
            category=e.get("category"),
            category_confidence=e.get("category_confidence"),
            thread_id=e.get("thread_id"),
            has_attachments=e.get("has_attachments", False),
            is_processed=e.get("is_processed", False)
        ))
    
    return EmailListResponse(
        emails=result,
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more
    )


@router.get("/mailboxes/{mailbox_id}/emails/{email_id}")
async def get_email(
    mailbox_id: str,
    email_id: str,
    storage: EmailStorage = Depends(get_storage)
):
    """Get a single email by ID"""
    from bson import ObjectId
    
    email = storage.emails.find_one({
        "_id": ObjectId(email_id),
        "mailbox_id": mailbox_id
    })
    
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    
    # Return full email including body
    return {
        "id": str(email["_id"]),
        "mailbox_id": email["mailbox_id"],
        "alias_id": email.get("alias_id"),
        "provider_message_id": email["provider_message_id"],
        "from_email": email.get("from_email", ""),
        "from_name": email.get("from_name"),
        "to_addresses": email.get("to_addresses", []),
        "cc_addresses": email.get("cc_addresses", []),
        "bcc_addresses": email.get("bcc_addresses", []),
        "subject": email.get("subject", ""),
        "body_text": email.get("body_text", ""),
        "body_html": email.get("body_html", ""),
        "received_at": email.get("received_at"),
        "category": email.get("category"),
        "category_confidence": email.get("category_confidence"),
        "categorized_at": email.get("categorized_at"),
        "thread_id": email.get("thread_id"),
        "has_attachments": email.get("has_attachments", False),
        "attachments": email.get("attachments", []),
        "labels": email.get("labels", []),
        "is_read": email.get("is_read", False),
        "is_starred": email.get("is_starred", False),
        "raw_headers": email.get("raw_headers", {})
    }


@router.patch("/mailboxes/{mailbox_id}/emails/{email_id}/category")
async def update_email_category(
    mailbox_id: str,
    email_id: str,
    category: str = Query(..., description="New category"),
    confidence: float = Query(1.0, ge=0, le=1),
    storage: EmailStorage = Depends(get_storage)
):
    """Manually update email category"""
    # Validate category
    try:
        EmailCategory(category)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {[c.value for c in EmailCategory]}"
        )
    
    success = storage.update_categorization(
        email_id,
        category=category,
        confidence=confidence,
        model_version="manual"
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Email not found")
    
    return {"success": True, "message": "Category updated"}


# =========================================================================
# SYSTEM ENDPOINTS
# =========================================================================

@router.post("/sync-imap-accounts")
async def sync_imap_accounts(
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """
    Sync mailboxes from existing IMAP accounts in torpedo_gmail database.
    
    This bridges the existing email accounts (from Gmail & Rate Limits tab)
    with the Email Sync system.
    """
    result = orch.sync_from_imap_accounts()
    return result


@router.get("/health", response_model=HealthResponse)
async def get_health(
    auto_sync: bool = Query(True, description="Auto-sync from IMAP accounts if no mailboxes"),
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """Get system health and metrics"""
    health = orch.get_system_health()
    
    # Auto-sync from IMAP accounts if no mailboxes registered
    if auto_sync and health["mailboxes"]["total"] == 0:
        sync_result = orch.sync_from_imap_accounts()
        if sync_result["synced"] > 0:
            # Refresh health after sync
            health = orch.get_system_health()
            health["auto_synced"] = sync_result
    
    return health


@router.get("/errors")
async def get_errors(
    mailbox_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """Get recent sync errors"""
    errors = orch.get_sync_errors(mailbox_id=mailbox_id, limit=limit)
    return {"errors": errors}


@router.post("/start")
async def start_workers(
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """Start all sync workers"""
    orch.start()
    return {"success": True, "message": "Workers started"}


@router.post("/stop")
async def stop_workers(
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """Stop all sync workers"""
    orch.stop()
    return {"success": True, "message": "Workers stopped"}


# =========================================================================
# CATEGORIES ENDPOINT
# =========================================================================

@router.get("/categories")
async def list_categories():
    """List available email categories"""
    return {
        "categories": [
            {
                "value": c.value,
                "description": _get_category_description(c)
            }
            for c in EmailCategory
        ]
    }


def _get_category_description(category: EmailCategory) -> str:
    """Get human-readable category description"""
    descriptions = {
        EmailCategory.OUTREACH: "Cold outreach and partnership inquiries",
        EmailCategory.DISCOVERY: "Demo requests and evaluation emails",
        EmailCategory.RFQ_PRICING: "Request for quotes and pricing discussions",
        EmailCategory.NEGOTIATION: "Contract and deal negotiations",
        EmailCategory.INVOICE: "Invoices, billing, and payment communications",
        EmailCategory.BANKING: "Bank-related communications",
        EmailCategory.INTERNAL: "Internal team communications",
        EmailCategory.PROMOTIONAL: "Marketing and promotional emails",
        EmailCategory.OTHERS: "Other miscellaneous emails",
        EmailCategory.UNCATEGORIZED: "Not yet categorized"
    }
    return descriptions.get(category, "")


# =========================================================================
# RE-CATEGORIZATION ENDPOINTS
# =========================================================================

class RecategorizeRequest(BaseModel):
    """Request model for re-categorization"""
    use_ai: bool = True  # Whether to use AI-based categorization
    mailbox_id: Optional[str] = None  # Filter by mailbox (optional)
    category: Optional[str] = None  # Re-categorize only emails with this category
    limit: Optional[int] = None  # Limit number of emails to re-categorize


def _run_ai_recategorization(db, email_ids: List[str], task_id: str):
    """Background task to re-categorize emails using AI"""
    import json
    from leads.openai_wrapper import chat_completion
    
    emails_collection = db.emails
    
    _background_tasks[task_id]["status"] = "running"
    _background_tasks[task_id]["started_at"] = datetime.utcnow().isoformat()
    
    # AI Classification prompts (same as historical_classifier)
    SYSTEM_PROMPT = """You are an expert B2B email classifier. Analyze emails and categorize them for a sales/operations CRM system.

Output JSON only:
{
    "category": "<category>",
    "sub_category": "<optional sub-category>",
    "confidence": 0.0-1.0,
    "intent": "informational|action_required|response_expected|fyi",
    "priority": "critical|high|medium|low",
    "department": "sales|operations|finance|support|marketing|hr|other",
    "is_reply": true/false,
    "reply_sentiment": "positive|neutral|negative|null",
    "suggested_action": "<brief action or null>"
}

Categories:
- inbound_lead, meeting_request, demo_request, pricing_inquiry
- rfq_request, quote_response, negotiation, contract_discussion, purchase_order
- onboarding, support_request, complaint, feedback
- invoice, payment_confirmation, payment_reminder, billing_dispute
- interested, not_interested, out_of_office, bounce, unsubscribe, auto_reply
- delivery_update, vendor_communication, internal
- newsletter, promotional, spam, social_notification
- other"""

    USER_PROMPT = """Classify this email:

From: {from_email}
To: {to_email}
Subject: {subject}
Date: {date}

Body:
{body}

Respond with JSON only."""
    
    processed = 0
    errors = 0
    
    for email_id in email_ids:
        try:
            # Fetch email
            from bson import ObjectId
            email = emails_collection.find_one({"_id": ObjectId(email_id)})
            if not email:
                continue
            
            # Extract email details
            from_email = ""
            from_addr = email.get("from_address") or email.get("sender_email", "")
            if isinstance(from_addr, dict):
                from_email = from_addr.get("email", "")
            elif isinstance(from_addr, str):
                from_email = from_addr
            
            to_email = ""
            to_addrs = email.get("to_addresses", [])
            if to_addrs:
                if isinstance(to_addrs[0], dict):
                    to_email = to_addrs[0].get("email", "")
                elif isinstance(to_addrs[0], str):
                    to_email = to_addrs[0]
            
            subject = email.get("subject", "")
            body = (email.get("body_plain") or email.get("body", "") or email.get("snippet", ""))[:1500]
            timestamp = email.get("timestamp", "")
            
            # Build prompt
            user_prompt = USER_PROMPT.format(
                from_email=from_email,
                to_email=to_email,
                subject=subject,
                date=str(timestamp),
                body=body
            )
            
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ]
            
            # Call AI
            response = chat_completion(
                messages=messages,
                source="background",
                endpoint="recategorization",
                max_output_tokens=300,
                response_format={"type": "json_object"}
            )
            
            if response["success"]:
                try:
                    parsed = json.loads(response["content"])
                    
                    # Update email with new category
                    emails_collection.update_one(
                        {"_id": ObjectId(email_id)},
                        {
                            "$set": {
                                "category": parsed.get("category", "other"),
                                "b2b_category": parsed.get("category", "other"),
                                "b2b_sub_category": parsed.get("sub_category"),
                                "category_confidence": parsed.get("confidence", 0.8),
                                "category_intent": parsed.get("intent"),
                                "category_priority": parsed.get("priority"),
                                "category_department": parsed.get("department"),
                                "is_reply": parsed.get("is_reply", False),
                                "reply_sentiment": parsed.get("reply_sentiment"),
                                "suggested_action": parsed.get("suggested_action"),
                                "category_method": "ai",
                                "recategorized_at": datetime.utcnow(),
                                "recategorized_by": "ai"
                            }
                        }
                    )
                    processed += 1
                except json.JSONDecodeError:
                    errors += 1
            else:
                errors += 1
            
            _background_tasks[task_id]["processed"] = processed
            _background_tasks[task_id]["errors"] = errors
            
        except Exception as e:
            logger.error(f"Error re-categorizing email {email_id}: {e}")
            errors += 1
            _background_tasks[task_id]["errors"] = errors
    
    _background_tasks[task_id]["status"] = "completed"
    _background_tasks[task_id]["completed_at"] = datetime.utcnow().isoformat()
    _background_tasks[task_id]["message"] = f"Processed {processed} emails, {errors} errors"


def _run_keyword_recategorization(emails_collection, email_ids: List[str], task_id: str):
    """Background task to re-categorize emails using keywords"""
    from leads.imap_leads_service import classify_email_segment
    
    _background_tasks[task_id]["status"] = "running"
    _background_tasks[task_id]["started_at"] = datetime.utcnow().isoformat()
    
    processed = 0
    errors = 0
    
    for email_id in email_ids:
        try:
            from bson import ObjectId
            email = emails_collection.find_one({"_id": ObjectId(email_id)})
            if not email:
                continue
            
            # Prepare content for classification
            subject = email.get("subject", "")
            body = email.get("body", "") or email.get("body_plain", "")
            
            # Use keyword classifier
            category = classify_email_segment(subject, body)
            
            # Update email with new category
            emails_collection.update_one(
                {"_id": ObjectId(email_id)},
                {
                    "$set": {
                        "category": category,
                        "recategorized_at": datetime.utcnow(),
                        "recategorized_by": "keywords"
                    }
                }
            )
            processed += 1
            _background_tasks[task_id]["processed"] = processed
            
        except Exception as e:
            logger.error(f"Error re-categorizing email {email_id}: {e}")
            errors += 1
            _background_tasks[task_id]["errors"] = errors
    
    _background_tasks[task_id]["status"] = "completed"
    _background_tasks[task_id]["completed_at"] = datetime.utcnow().isoformat()
    _background_tasks[task_id]["message"] = f"Processed {processed} emails, {errors} errors"


@router.post("/recategorize-all")
async def recategorize_all_emails(
    request: RecategorizeRequest,
    background_tasks: BackgroundTasks,
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """
    Queue all emails for re-categorization.
    This runs as a background task and returns immediately.
    """
    import uuid
    
    # Get emails collection
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB_NAME", "email_automation")
    client = MongoClient(mongo_uri)
    db = client[db_name]
    emails_collection = db.emails
    
    # Build query
    query = {}
    if request.mailbox_id:
        query["mailbox_id"] = request.mailbox_id
    if request.category:
        query["category"] = request.category
    
    # Get email IDs to re-categorize
    cursor = emails_collection.find(query, {"_id": 1})
    if request.limit:
        cursor = cursor.limit(request.limit)
    
    email_ids = [str(doc["_id"]) for doc in cursor]
    total = len(email_ids)
    
    if total == 0:
        return {
            "success": False,
            "message": "No emails found matching criteria"
        }
    
    # Create task ID
    task_id = str(uuid.uuid4())
    
    # Initialize task tracking
    _background_tasks[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "total": total,
        "processed": 0,
        "errors": 0,
        "use_ai": request.use_ai,
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Start background task
    if request.use_ai:
        thread = threading.Thread(
            target=_run_ai_recategorization,
            args=(db, email_ids, task_id)
        )
    else:
        thread = threading.Thread(
            target=_run_keyword_recategorization,
            args=(emails_collection, email_ids, task_id)
        )
    
    thread.daemon = True
    thread.start()
    
    return {
        "success": True,
        "task_id": task_id,
        "total_emails": total,
        "message": f"Started re-categorization of {total} emails using {'AI' if request.use_ai else 'keywords'}",
        "check_status_url": f"/email-sync/recategorize-status/{task_id}"
    }


@router.get("/recategorize-status/{task_id}")
async def get_recategorize_status(task_id: str = Path(...)):
    """Get status of a re-categorization task"""
    if task_id not in _background_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return _background_tasks[task_id]


@router.get("/recategorize-tasks")
async def list_recategorize_tasks():
    """List all re-categorization tasks"""
    return {
        "tasks": list(_background_tasks.values())
    }


# =========================================================================
# BACKGROUND BACKFILL ENDPOINTS
# =========================================================================

def _run_background_backfill(orch: EmailSyncOrchestrator, mailbox_id: str, task_id: str, days_back: int = 30):
    """Run backfill in background thread"""
    import asyncio
    
    _background_tasks[task_id]["status"] = "running"
    _background_tasks[task_id]["started_at"] = datetime.utcnow().isoformat()
    
    try:
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run backfill
        result = loop.run_until_complete(
            orch.trigger_backfill(mailbox_id, days_back=days_back)
        )
        
        _background_tasks[task_id]["status"] = "completed"
        _background_tasks[task_id]["completed_at"] = datetime.utcnow().isoformat()
        _background_tasks[task_id]["result"] = result
        _background_tasks[task_id]["message"] = f"Backfill completed for mailbox {mailbox_id}"
        
    except Exception as e:
        logger.error(f"Backfill error for {mailbox_id}: {e}")
        _background_tasks[task_id]["status"] = "failed"
        _background_tasks[task_id]["error"] = str(e)
        _background_tasks[task_id]["completed_at"] = datetime.utcnow().isoformat()
    
    finally:
        loop.close()


@router.post("/mailboxes/{mailbox_id}/backfill-async")
async def trigger_async_backfill(
    mailbox_id: str = Path(...),
    days_back: int = Query(30, ge=1, le=365),
    orch: EmailSyncOrchestrator = Depends(get_orchestrator)
):
    """
    Trigger email backfill that runs in background.
    Returns immediately with a task ID for tracking progress.
    """
    import uuid
    
    # Verify mailbox exists
    mailbox = await orch.storage.get_mailbox(mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    
    # Create task ID
    task_id = str(uuid.uuid4())
    
    # Initialize task tracking
    _background_tasks[task_id] = {
        "task_id": task_id,
        "type": "backfill",
        "mailbox_id": mailbox_id,
        "days_back": days_back,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Start background thread
    thread = threading.Thread(
        target=_run_background_backfill,
        args=(orch, mailbox_id, task_id, days_back)
    )
    thread.daemon = True
    thread.start()
    
    return {
        "success": True,
        "task_id": task_id,
        "mailbox_id": mailbox_id,
        "days_back": days_back,
        "message": f"Backfill started in background for mailbox {mailbox_id}",
        "check_status_url": f"/email-sync/backfill-status/{task_id}"
    }


@router.get("/backfill-status/{task_id}")
async def get_backfill_status(task_id: str = Path(...)):
    """Get status of a backfill task"""
    if task_id not in _background_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return _background_tasks[task_id]


@router.get("/background-tasks")
async def list_background_tasks():
    """List all background tasks (backfill and re-categorization)"""
    return {
        "tasks": list(_background_tasks.values()),
        "total": len(_background_tasks)
    }
