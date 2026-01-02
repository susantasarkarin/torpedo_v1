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
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query, Path
from pydantic import BaseModel, EmailStr, Field
from pymongo import MongoClient
import os

from .orchestrator import EmailSyncOrchestrator
from .models import ProviderType, SyncStatus, EmailCategory
from .storage import EmailStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email-sync", tags=["Email Sync"])

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
        display_name=request.display_name
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
        {"_id": 1, "alias_email": 1, "display_name": 1, "is_primary": 1, "is_active": 1}
    ))
    
    return [
        {
            "alias_id": str(a["_id"]),
            "alias_email": a["alias_email"],
            "display_name": a.get("display_name"),
            "is_primary": a.get("is_primary", False),
            "is_active": a.get("is_active", True)
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
