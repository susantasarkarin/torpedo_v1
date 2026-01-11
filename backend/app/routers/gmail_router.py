"""
GMAIL API ROUTER
================

FastAPI router for Gmail API endpoints.

Endpoints:
- OAuth authentication flow
- Mailbox management
- Email sync (trigger, status)
- Email retrieval with filters
- Email content (on-demand)
- Send email
- AI classification
- Statistics
"""

import os
import logging
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from pydantic import BaseModel, EmailStr, Field
from google_auth_oauthlib.flow import Flow

from ..services.gmail_service import GmailService
from ..services.ai_classification_service import AIClassificationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail", tags=["Gmail API"])


# =========================================================================
# DEPENDENCIES
# =========================================================================

_gmail_service: Optional[GmailService] = None
_ai_service: Optional[AIClassificationService] = None


def get_gmail_service() -> GmailService:
    """Get or create Gmail service instance"""
    global _gmail_service
    
    if _gmail_service is None:
        mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        _gmail_service = GmailService(mongo_uri=mongo_uri)
    
    return _gmail_service


def get_ai_service() -> AIClassificationService:
    """Get or create AI service instance"""
    global _ai_service
    
    if _ai_service is None:
        _ai_service = AIClassificationService()
    
    return _ai_service


# =========================================================================
# REQUEST/RESPONSE MODELS
# =========================================================================

class OAuthCallbackRequest(BaseModel):
    """OAuth callback with authorization code"""
    code: str
    redirect_uri: str


class MailboxCreateRequest(BaseModel):
    """Create mailbox with OAuth tokens"""
    email: EmailStr
    access_token: str
    refresh_token: str
    display_name: Optional[str] = None
    token_expiry: Optional[datetime] = None


class MailboxResponse(BaseModel):
    """Mailbox response"""
    id: str
    email: str
    display_name: str
    is_active: bool
    last_sync_at: Optional[datetime]
    sync_error: Optional[str]


class EmailMetadataResponse(BaseModel):
    """Email metadata response"""
    id: str
    gmail_message_id: str
    gmail_thread_id: str
    from_email: str
    from_name: Optional[str]
    to_emails: List[str]
    subject: str
    snippet: str
    timestamp: datetime
    direction: str
    has_attachments: bool
    is_read: bool
    is_starred: bool
    ai_category: Optional[str]
    ai_priority: Optional[str]
    ai_department: Optional[str]
    ai_summary: Optional[str]


class EmailListResponse(BaseModel):
    """Paginated email list response"""
    emails: List[EmailMetadataResponse]
    total: int
    page: int
    limit: int
    total_pages: int


class EmailContentResponse(BaseModel):
    """Full email content response"""
    gmail_message_id: str
    body_plain: str
    body_html: str
    attachments: List[dict]


class SendEmailRequest(BaseModel):
    """Send email request"""
    mailbox_id: str
    to: List[EmailStr]
    subject: str
    body_html: str
    body_plain: Optional[str] = None
    cc: Optional[List[EmailStr]] = None
    bcc: Optional[List[EmailStr]] = None
    reply_to_message_id: Optional[str] = None
    thread_id: Optional[str] = None


class SyncResponse(BaseModel):
    """Sync result response"""
    success: bool
    new_emails: int
    updated_emails: int
    message: str


class StatsResponse(BaseModel):
    """Statistics response"""
    total: int
    unread: int
    unclassified: int
    today: int
    by_category: dict
    by_department: dict


class ClassifyRequest(BaseModel):
    """Manual classification request"""
    email_id: str


class ColdEmailRequest(BaseModel):
    """Cold email generation request"""
    prospect_name: str
    prospect_title: str
    prospect_company: str
    prospect_industry: str
    personalization_hooks: List[str]
    pain_points: List[str]
    sender_name: str


# =========================================================================
# OAUTH ENDPOINTS
# =========================================================================

@router.get("/oauth/url")
async def get_oauth_url(redirect_uri: str = Query(...)):
    """
    Get OAuth authorization URL for Gmail.
    
    Returns:
        OAuth URL to redirect user to
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        raise HTTPException(500, "Google OAuth not configured")
    
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.modify"
        ],
        redirect_uri=redirect_uri
    )
    
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    
    return {"url": auth_url}


@router.post("/oauth/callback")
async def oauth_callback(
    request: OAuthCallbackRequest,
    gmail: GmailService = Depends(get_gmail_service)
):
    """
    Handle OAuth callback and create mailbox.
    
    Exchanges authorization code for tokens and creates mailbox.
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        raise HTTPException(500, "Google OAuth not configured")
    
    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            },
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.modify"
            ],
            redirect_uri=request.redirect_uri
        )
        
        flow.fetch_token(code=request.code)
        credentials = flow.credentials
        
        # Get user email
        from googleapiclient.discovery import build
        service = build("gmail", "v1", credentials=credentials)
        profile = service.users().getProfile(userId="me").execute()
        email = profile["emailAddress"]
        
        # Check if mailbox exists
        existing = gmail.get_mailbox_by_email(email)
        if existing:
            # Update tokens
            gmail.update_mailbox_tokens(
                str(existing["_id"]),
                credentials.token,
                credentials.refresh_token,
                credentials.expiry
            )
            mailbox_id = str(existing["_id"])
        else:
            # Create new mailbox
            mailbox_id = gmail.add_mailbox(
                email=email,
                access_token=credentials.token,
                refresh_token=credentials.refresh_token,
                token_expiry=credentials.expiry
            )
        
        return {
            "success": True,
            "mailbox_id": mailbox_id,
            "email": email
        }
        
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        raise HTTPException(400, f"OAuth error: {str(e)}")


# =========================================================================
# MAILBOX ENDPOINTS
# =========================================================================

@router.get("/mailboxes", response_model=List[MailboxResponse])
async def list_mailboxes(
    active_only: bool = True,
    gmail: GmailService = Depends(get_gmail_service)
):
    """List all Gmail mailboxes"""
    mailboxes = gmail.list_mailboxes(active_only=active_only)
    
    return [
        MailboxResponse(
            id=str(m["_id"]),
            email=m["email"],
            display_name=m.get("display_name", ""),
            is_active=m.get("is_active", True),
            last_sync_at=m.get("last_sync_at"),
            sync_error=m.get("sync_error")
        )
        for m in mailboxes
    ]


@router.get("/mailboxes/{mailbox_id}", response_model=MailboxResponse)
async def get_mailbox(
    mailbox_id: str,
    gmail: GmailService = Depends(get_gmail_service)
):
    """Get mailbox by ID"""
    mailbox = gmail.get_mailbox(mailbox_id)
    if not mailbox:
        raise HTTPException(404, "Mailbox not found")
    
    return MailboxResponse(
        id=str(mailbox["_id"]),
        email=mailbox["email"],
        display_name=mailbox.get("display_name", ""),
        is_active=mailbox.get("is_active", True),
        last_sync_at=mailbox.get("last_sync_at"),
        sync_error=mailbox.get("sync_error")
    )


@router.delete("/mailboxes/{mailbox_id}")
async def deactivate_mailbox(
    mailbox_id: str,
    gmail: GmailService = Depends(get_gmail_service)
):
    """Deactivate a mailbox"""
    gmail.deactivate_mailbox(mailbox_id)
    return {"success": True}


# =========================================================================
# SYNC ENDPOINTS
# =========================================================================

@router.post("/mailboxes/{mailbox_id}/sync", response_model=SyncResponse)
async def sync_mailbox(
    mailbox_id: str,
    max_results: int = Query(500, ge=1, le=5000),
    days_back: int = Query(30, ge=1, le=365),
    gmail: GmailService = Depends(get_gmail_service)
):
    """
    Trigger email sync for a mailbox.
    
    Uses History API for incremental sync after first sync.
    """
    try:
        new_count, updated_count = gmail.sync_mailbox(
            mailbox_id=mailbox_id,
            max_results=max_results,
            days_back=days_back
        )
        
        return SyncResponse(
            success=True,
            new_emails=new_count,
            updated_emails=updated_count,
            message=f"Synced {new_count} new emails, {updated_count} updates"
        )
        
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Sync error: {e}")
        raise HTTPException(500, f"Sync failed: {str(e)}")


@router.post("/sync/all", response_model=dict)
async def sync_all_mailboxes(
    background_tasks: BackgroundTasks,
    gmail: GmailService = Depends(get_gmail_service)
):
    """Trigger sync for all active mailboxes (background)"""
    mailboxes = gmail.list_mailboxes(active_only=True)
    
    def sync_all():
        for mailbox in mailboxes:
            try:
                gmail.sync_mailbox(str(mailbox["_id"]))
            except Exception as e:
                logger.error(f"Sync failed for {mailbox['email']}: {e}")
    
    background_tasks.add_task(sync_all)
    
    return {
        "success": True,
        "message": f"Sync started for {len(mailboxes)} mailboxes",
        "mailbox_count": len(mailboxes)
    }


# =========================================================================
# EMAIL ENDPOINTS
# =========================================================================

@router.get("/emails", response_model=EmailListResponse)
async def list_emails(
    mailbox_id: Optional[str] = None,
    direction: Optional[str] = Query(None, regex="^(inbound|outbound)$"),
    category: Optional[str] = None,
    department: Optional[str] = None,
    search: Optional[str] = None,
    is_read: Optional[bool] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    gmail: GmailService = Depends(get_gmail_service)
):
    """
    List emails with filters and pagination.
    
    Returns metadata only (use /emails/{id}/content for full body).
    """
    skip = (page - 1) * limit
    
    emails, total = gmail.get_emails(
        mailbox_id=mailbox_id,
        direction=direction,
        category=category,
        department=department,
        search=search,
        is_read=is_read,
        skip=skip,
        limit=limit
    )
    
    return EmailListResponse(
        emails=[
            EmailMetadataResponse(
                id=e["_id"],
                gmail_message_id=e["gmail_message_id"],
                gmail_thread_id=e["gmail_thread_id"],
                from_email=e["from_email"],
                from_name=e.get("from_name"),
                to_emails=e.get("to_emails", []),
                subject=e.get("subject", ""),
                snippet=e.get("snippet", ""),
                timestamp=e["timestamp"],
                direction=e["direction"],
                has_attachments=e.get("has_attachments", False),
                is_read=e.get("is_read", True),
                is_starred=e.get("is_starred", False),
                ai_category=e.get("ai_category"),
                ai_priority=e.get("ai_priority"),
                ai_department=e.get("ai_department"),
                ai_summary=e.get("ai_summary")
            )
            for e in emails
        ],
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit
    )


@router.get("/emails/{email_id}")
async def get_email(
    email_id: str,
    gmail: GmailService = Depends(get_gmail_service)
):
    """Get email metadata by ID"""
    email = gmail.get_email_by_id(email_id)
    if not email:
        raise HTTPException(404, "Email not found")
    
    return email


@router.get("/emails/{email_id}/content", response_model=EmailContentResponse)
async def get_email_content(
    email_id: str,
    gmail: GmailService = Depends(get_gmail_service)
):
    """
    Get full email content from Gmail API.
    
    Fetches body and attachments on-demand.
    """
    # Get metadata first
    email = gmail.get_email_by_id(email_id)
    if not email:
        raise HTTPException(404, "Email not found")
    
    # Fetch content from Gmail
    content = gmail.get_email_content(
        email["mailbox_id"],
        email["gmail_message_id"]
    )
    
    if not content:
        raise HTTPException(404, "Email content not found in Gmail")
    
    return EmailContentResponse(
        gmail_message_id=content["gmail_message_id"],
        body_plain=content.get("body_plain", ""),
        body_html=content.get("body_html", ""),
        attachments=content.get("attachments", [])
    )


@router.get("/emails/{email_id}/attachment/{attachment_id}")
async def download_attachment(
    email_id: str,
    attachment_id: str,
    gmail: GmailService = Depends(get_gmail_service)
):
    """Download email attachment"""
    email = gmail.get_email_by_id(email_id)
    if not email:
        raise HTTPException(404, "Email not found")
    
    data = gmail.download_attachment(
        email["mailbox_id"],
        email["gmail_message_id"],
        attachment_id
    )
    
    if not data:
        raise HTTPException(404, "Attachment not found")
    
    from fastapi.responses import Response
    return Response(
        content=data,
        media_type="application/octet-stream"
    )


# =========================================================================
# THREAD ENDPOINTS
# =========================================================================

@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    mailbox_id: str = Query(...),
    gmail: GmailService = Depends(get_gmail_service)
):
    """Get all emails in a thread"""
    emails = gmail.get_thread(mailbox_id, thread_id)
    return {"thread_id": thread_id, "emails": emails}


@router.get("/threads/{thread_id}/content")
async def get_thread_content(
    thread_id: str,
    mailbox_id: str = Query(...),
    gmail: GmailService = Depends(get_gmail_service)
):
    """Get full content for all emails in a thread"""
    messages = gmail.get_thread_content(mailbox_id, thread_id)
    return {"thread_id": thread_id, "messages": messages}


# =========================================================================
# SEND EMAIL
# =========================================================================

@router.post("/send")
async def send_email(
    request: SendEmailRequest,
    gmail: GmailService = Depends(get_gmail_service)
):
    """Send email via Gmail API"""
    message_id = gmail.send_email(
        mailbox_id=request.mailbox_id,
        to=request.to,
        subject=request.subject,
        body_html=request.body_html,
        body_plain=request.body_plain,
        cc=request.cc,
        bcc=request.bcc,
        reply_to_message_id=request.reply_to_message_id,
        thread_id=request.thread_id
    )
    
    if not message_id:
        raise HTTPException(500, "Failed to send email")
    
    return {"success": True, "message_id": message_id}


# =========================================================================
# STATISTICS
# =========================================================================

@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    mailbox_id: Optional[str] = None,
    gmail: GmailService = Depends(get_gmail_service)
):
    """Get email statistics"""
    stats = gmail.get_stats(mailbox_id)
    return StatsResponse(**stats)


# =========================================================================
# AI CLASSIFICATION
# =========================================================================

@router.post("/classify/{email_id}")
async def classify_email(
    email_id: str,
    gmail: GmailService = Depends(get_gmail_service),
    ai: AIClassificationService = Depends(get_ai_service)
):
    """Classify a single email using AI"""
    # Get email metadata
    email = gmail.get_email_by_id(email_id)
    if not email:
        raise HTTPException(404, "Email not found")
    
    # Get full content for better classification
    content = gmail.get_email_content(
        email["mailbox_id"],
        email["gmail_message_id"]
    )
    
    body = ""
    if content:
        body = content.get("body_plain") or content.get("body_html", "")
    else:
        body = email.get("snippet", "")
    
    # Classify
    result = ai.classify_email(
        from_email=email.get("from_email", ""),
        to_email=email.get("to_emails", [""])[0] if email.get("to_emails") else "",
        subject=email.get("subject", ""),
        body=body
    )
    
    # Update email with classification
    gmail.update_email_classification(
        email_id=email_id,
        category=result.category,
        confidence=result.confidence,
        priority=result.priority,
        department=result.department,
        summary=result.summary,
        entities=result.key_entities
    )
    
    return {
        "success": True,
        "classification": {
            "category": result.category,
            "confidence": result.confidence,
            "department": result.department,
            "priority": result.priority,
            "summary": result.summary
        }
    }


@router.post("/classify/batch")
async def classify_batch(
    background_tasks: BackgroundTasks,
    limit: int = Query(100, ge=1, le=500),
    gmail: GmailService = Depends(get_gmail_service),
    ai: AIClassificationService = Depends(get_ai_service)
):
    """Classify unclassified emails in background"""
    
    def classify_unclassified():
        emails = gmail.get_unclassified_emails(limit=limit)
        
        for email in emails:
            try:
                # Use snippet for batch classification (faster)
                result = ai.classify_email(
                    from_email=email.get("from_email", ""),
                    to_email=email.get("to_emails", [""])[0] if email.get("to_emails") else "",
                    subject=email.get("subject", ""),
                    body=email.get("snippet", "")
                )
                
                gmail.update_email_classification(
                    email_id=email["_id"],
                    category=result.category,
                    confidence=result.confidence,
                    priority=result.priority,
                    department=result.department,
                    summary=result.summary,
                    entities=result.key_entities
                )
            except Exception as e:
                logger.error(f"Classification error for {email['_id']}: {e}")
    
    unclassified = gmail.get_unclassified_emails(limit=1)
    count = len(gmail.get_unclassified_emails(limit=limit))
    
    background_tasks.add_task(classify_unclassified)
    
    return {
        "success": True,
        "message": f"Classification started for {count} emails",
        "count": count
    }


# =========================================================================
# COLD EMAIL GENERATION
# =========================================================================

@router.post("/cold-email/generate")
async def generate_cold_email(
    request: ColdEmailRequest,
    ai: AIClassificationService = Depends(get_ai_service)
):
    """Generate personalized cold email sequence"""
    try:
        result = ai.write_cold_email(
            prospect_name=request.prospect_name,
            prospect_title=request.prospect_title,
            prospect_company=request.prospect_company,
            prospect_industry=request.prospect_industry,
            personalization_hooks=request.personalization_hooks,
            pain_points=request.pain_points,
            sender_name=request.sender_name
        )
        
        return {"success": True, "emails": result}
        
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        logger.error(f"Cold email generation error: {e}")
        raise HTTPException(500, "Failed to generate cold email")


# =========================================================================
# THREAD SUMMARY
# =========================================================================

@router.get("/threads/{thread_id}/summary")
async def summarize_thread(
    thread_id: str,
    mailbox_id: str = Query(...),
    gmail: GmailService = Depends(get_gmail_service),
    ai: AIClassificationService = Depends(get_ai_service)
):
    """Get AI-generated summary of email thread"""
    messages = gmail.get_thread_content(mailbox_id, thread_id)
    
    if not messages:
        raise HTTPException(404, "Thread not found")
    
    summary = ai.summarize_thread(messages)
    
    return {"success": True, "summary": summary}
