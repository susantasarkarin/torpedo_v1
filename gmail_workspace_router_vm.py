"""
Gmail Workspace Router - Handles Gmail API with Service Account Domain-Wide Delegation

This router uses a single service account to access multiple Gmail mailboxes
in a Google Workspace domain. No individual OAuth consent is required.

Setup Requirements:
1. Create Service Account in Google Cloud Console
2. Enable Gmail API 
3. Enable Domain-Wide Delegation for the service account
4. In Google Workspace Admin Console, add service account to domain-wide delegation:
   - Client ID: (from service account)
   - OAuth Scopes:
     - https://www.googleapis.com/auth/gmail.readonly
     - https://www.googleapis.com/auth/gmail.send
     - https://www.googleapis.com/auth/gmail.modify
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from bson import ObjectId

from fastapi import APIRouter, HTTPException, Request, Query, Body, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, EmailStr
from dotenv import load_dotenv

# Import the workspace service
from app.services.gmail_workspace_service import GmailWorkspaceService

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/gmail-ws",
    tags=["gmail-workspace"]
)

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
SERVICE_ACCOUNT_FILE = os.getenv("GMAIL_SERVICE_ACCOUNT_FILE", "")

# Initialize service
gmail_service: Optional[GmailWorkspaceService] = None


def get_gmail_service() -> GmailWorkspaceService:
    """Get or create the Gmail Workspace service"""
    global gmail_service
    
    if gmail_service is None:
        gmail_service = GmailWorkspaceService(
            mongo_uri=MONGO_URI,
            service_account_file=SERVICE_ACCOUNT_FILE if SERVICE_ACCOUNT_FILE else None
        )
        # Try to load from DB if not configured from file
        if not gmail_service.is_configured():
            gmail_service.load_service_account()
    
    return gmail_service


# ============================================
# Pydantic Models
# ============================================

class ServiceAccountUpload(BaseModel):
    """Service account credentials upload"""
    credentials: Dict[str, Any] = Field(..., description="Service account JSON contents")


class MailboxAdd(BaseModel):
    """Add mailbox request"""
    email: EmailStr = Field(..., description="Email address to add")
    display_name: Optional[str] = Field(None, description="Display name")


class MailboxUpdate(BaseModel):
    """Update mailbox request"""
    display_name: Optional[str] = None
    is_active: Optional[bool] = None


class SyncRequest(BaseModel):
    """Sync request"""
    full_sync: bool = Field(False, description="Force full sync instead of incremental")
    max_results: int = Field(500, ge=1, le=50000, description="Maximum emails to sync")


# ============================================
# Service Account Configuration
# ============================================

@router.get("/config/status")
async def get_config_status():
    """
    Get service account configuration status.
    Returns whether the service account is configured and basic info.
    """
    try:
        service = get_gmail_service()
        
        if service.is_configured():
            info = service.get_service_account_info()
            return {
                "configured": True,
                "service_account_email": info.get("client_email") if info else None,
                "project_id": info.get("project_id") if info else None
            }
        else:
            return {
                "configured": False,
                "message": "Service account not configured. Upload credentials to enable Gmail integration."
            }
    except Exception as e:
        logger.error(f"Error checking config status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/service-account")
async def upload_service_account(data: ServiceAccountUpload):
    """
    Upload service account credentials.
    
    Upload the JSON key file contents from Google Cloud Console.
    This enables domain-wide delegation for accessing all mailboxes.
    """
    try:
        service = get_gmail_service()
        service.save_service_account(data.credentials)
        
        return {
            "success": True,
            "message": "Service account configured successfully",
            "client_email": data.credentials.get("client_email")
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error saving service account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Mailbox Management
# ============================================

@router.get("/mailboxes")
async def list_mailboxes(active_only: bool = Query(True)):
    """
    List all configured mailboxes.
    """
    try:
        service = get_gmail_service()
        
        if not service.is_configured():
            return {
                "mailboxes": [],
                "configured": False,
                "message": "Service account not configured"
            }
        
        mailboxes = service.list_mailboxes(active_only=active_only)
        
        return {
            "mailboxes": mailboxes,
            "total": len(mailboxes),
            "configured": True
        }
    except Exception as e:
        logger.error(f"Error listing mailboxes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mailboxes")
async def add_mailbox(data: MailboxAdd):
    """
    Add a new mailbox to sync.
    
    The email must be in the Google Workspace domain that has
    granted domain-wide delegation to the service account.
    """
    try:
        service = get_gmail_service()
        
        if not service.is_configured():
            raise HTTPException(
                status_code=400,
                detail="Service account not configured. Upload credentials first."
            )
        
        mailbox = service.add_mailbox(
            email=data.email,
            display_name=data.display_name
        )
        
        return {
            "success": True,
            "mailbox": mailbox
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding mailbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mailboxes/{mailbox_id}")
async def get_mailbox(mailbox_id: str):
    """Get mailbox details"""
    try:
        service = get_gmail_service()
        mailbox = service.get_mailbox(mailbox_id)
        
        if not mailbox:
            raise HTTPException(status_code=404, detail="Mailbox not found")
        
        return mailbox
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting mailbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/mailboxes/{mailbox_id}")
async def update_mailbox(mailbox_id: str, data: MailboxUpdate):
    """Update mailbox settings"""
    try:
        service = get_gmail_service()
        
        updates = {}
        if data.display_name is not None:
            updates["display_name"] = data.display_name
        if data.is_active is not None:
            updates["is_active"] = data.is_active
        
        success = service.update_mailbox(mailbox_id, updates)
        
        if not success:
            raise HTTPException(status_code=404, detail="Mailbox not found")
        
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating mailbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/mailboxes/{mailbox_id}")
async def remove_mailbox(
    mailbox_id: str,
    delete_emails: bool = Query(False, description="Also delete synced emails")
):
    """
    Remove a mailbox.
    
    Set delete_emails=true to also remove all synced email metadata.
    """
    try:
        service = get_gmail_service()
        success = service.remove_mailbox(mailbox_id, delete_emails=delete_emails)
        
        if not success:
            raise HTTPException(status_code=404, detail="Mailbox not found")
        
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing mailbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mailboxes/{mailbox_id}/signatures")
async def get_mailbox_signatures(mailbox_id: str):
    """
    Get email signatures from Gmail for a mailbox.
    
    Fetches signatures from Gmail's sendAs settings using Gmail API.
    """
    try:
        service = get_gmail_service()
        mailbox = service.get_mailbox(mailbox_id)
        
        if not mailbox:
            raise HTTPException(status_code=404, detail="Mailbox not found")
        
        email = mailbox.get("email")
        gmail = service._get_service(email)
        
        # Fetch send-as addresses with signatures
        response = gmail.users().settings().sendAs().list(userId="me").execute()
        
        signatures = []
        for send_as in response.get("sendAs", []):
            sig_html = send_as.get("signature", "")
            if sig_html:  # Only include if signature exists
                signatures.append({
                    "email": send_as.get("sendAsEmail", ""),
                    "display_name": send_as.get("displayName", ""),
                    "signature_html": sig_html,
                    "is_primary": send_as.get("isPrimary", False),
                    "is_default": send_as.get("isDefault", False),
                })
        
        return {
            "success": True,
            "mailbox_email": email,
            "signatures": signatures
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching signatures: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signatures")
async def get_all_signatures():
    """
    Get email signatures from all active Gmail Workspace mailboxes.
    
    Fetches signatures from each mailbox's sendAs settings.
    """
    try:
        service = get_gmail_service()
        
        if not service.is_configured():
            return {"success": False, "error": "Service account not configured", "signatures": []}
        
        mailboxes = service.list_mailboxes()
        all_signatures = []
        
        for mailbox in mailboxes:
            if not mailbox.get("is_active"):
                continue
                
            email = mailbox.get("email")
            mailbox_id = str(mailbox.get("_id", mailbox.get("id", "")))
            
            try:
                gmail = service._get_service(email)
                response = gmail.users().settings().sendAs().list(userId="me").execute()
                
                for send_as in response.get("sendAs", []):
                    sig_html = send_as.get("signature", "")
                    all_signatures.append({
                        "mailbox_id": mailbox_id,
                        "mailbox_email": email,
                        "email": send_as.get("sendAsEmail", ""),
                        "display_name": send_as.get("displayName", ""),
                        "signature_html": sig_html,
                        "is_primary": send_as.get("isPrimary", False),
                        "is_default": send_as.get("isDefault", False),
                    })
            except Exception as e:
                logger.warning(f"Error fetching signatures for {email}: {e}")
                continue
        
        return {
            "success": True,
            "total": len(all_signatures),
            "signatures": all_signatures
        }
    except Exception as e:
        logger.error(f"Error fetching all signatures: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mailboxes/{mailbox_id}/test")
async def test_mailbox_connection(mailbox_id: str):
    """
    Test connection to a mailbox.
    
    Verifies that the service account can access the mailbox.
    Also updates the mailbox record with the actual Gmail message count.
    """
    try:
        service = get_gmail_service()
        mailbox = service.get_mailbox(mailbox_id)
        
        if not mailbox:
            raise HTTPException(status_code=404, detail="Mailbox not found")
        
        result = service.test_connection(mailbox["email"])
        
        # Save the actual Gmail total to the mailbox record
        if result.get("success") and result.get("messages_total"):
            service.mailboxes.update_one(
                {"_id": ObjectId(mailbox_id)},
                {"$set": {"gmail_total": result["messages_total"]}}
            )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing connection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Email Sync
# ============================================

def run_sync_background(service, mailbox_id: str, max_results: int, full_sync: bool):
    """Background task to run email sync"""
    try:
        result = service.sync_mailbox(
            mailbox_id=mailbox_id,
            max_results=max_results,
            full_sync=full_sync
        )
        logger.info(f"Background sync completed for {mailbox_id}: {result}")
    except Exception as e:
        logger.error(f"Background sync error for {mailbox_id}: {e}")
        # Update mailbox to clear syncing status on error
        try:
            service.mailboxes.update_one(
                {"_id": ObjectId(mailbox_id)},
                {"$set": {"syncing": False, "sync_error": str(e)}}
            )
        except:
            pass

@router.post("/mailboxes/{mailbox_id}/sync")
async def sync_mailbox(
    mailbox_id: str,
    data: SyncRequest = Body(default=SyncRequest()),
    background_tasks: BackgroundTasks = None
):
    """
    Sync emails for a mailbox.
    
    Uses incremental sync (History API) by default.
    Set full_sync=true to force a complete re-sync.
    Runs in background and returns immediately.
    """
    try:
        service = get_gmail_service()
        
        if not service.is_configured():
            raise HTTPException(
                status_code=400,
                detail="Service account not configured"
            )
        
        mailbox = service.get_mailbox(mailbox_id)
        if not mailbox:
            raise HTTPException(status_code=404, detail="Mailbox not found")
        
        # Mark mailbox as syncing immediately
        service.mailboxes.update_one(
            {"_id": ObjectId(mailbox_id)},
            {"$set": {"syncing": True, "sync_progress": 0}}
        )
        
        # Run sync in background
        background_tasks.add_task(
            run_sync_background,
            service,
            mailbox_id,
            data.max_results,
            data.full_sync
        )
        
        return {
            "success": True,
            "message": "Sync started in background",
            "mailbox_id": mailbox_id,
            "status": "syncing"
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error syncing mailbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mailboxes/{mailbox_id}/sync-status")
async def get_sync_status(mailbox_id: str):
    """
    Get sync progress for a mailbox.
    Returns syncing status, progress, and total counts.
    """
    try:
        service = get_gmail_service()
        
        mailbox = service.get_mailbox(mailbox_id)
        if not mailbox:
            raise HTTPException(status_code=404, detail="Mailbox not found")
        
        return {
            "mailbox_id": mailbox_id,
            "email": mailbox.get("email"),
            "syncing": mailbox.get("syncing", False),
            "sync_progress": mailbox.get("sync_progress", 0),
            "sync_total": mailbox.get("sync_total", 0),
            "sync_started_at": mailbox.get("sync_started_at"),
            "sync_completed_at": mailbox.get("sync_completed_at"),
            "email_count": mailbox.get("email_count", 0),
            "sync_error": mailbox.get("sync_error")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting sync status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-all")
async def sync_all_mailboxes(
    data: SyncRequest = Body(default=SyncRequest())
):
    """
    Sync all active mailboxes.
    """
    try:
        service = get_gmail_service()
        
        if not service.is_configured():
            raise HTTPException(
                status_code=400,
                detail="Service account not configured"
            )
        
        mailboxes = service.list_mailboxes(active_only=True)
        
        results = []
        for mailbox in mailboxes:
            try:
                result = service.sync_mailbox(
                    mailbox_id=mailbox["id"],
                    max_results=data.max_results,
                    full_sync=data.full_sync
                )
                results.append(result)
            except Exception as e:
                results.append({
                    "mailbox_id": mailbox["id"],
                    "email": mailbox["email"],
                    "success": False,
                    "error": str(e)
                })
        
        return {
            "synced": len([r for r in results if r.get("success")]),
            "failed": len([r for r in results if not r.get("success")]),
            "results": results
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing all mailboxes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Email Retrieval
# ============================================

@router.get("/emails")
async def get_emails(
    mailbox_id: Optional[str] = Query(None),
    direction: Optional[str] = Query(None, regex="^(inbound|outbound)$"),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """
    Get synced emails with filters.
    """
    try:
        service = get_gmail_service()
        
        result = service.get_emails(
            mailbox_id=mailbox_id,
            direction=direction,
            search=search,
            limit=limit,
            offset=offset
        )
        
        return result
    except Exception as e:
        logger.error(f"Error getting emails: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/emails/{mailbox_id}/{gmail_message_id}")
async def get_email_content(mailbox_id: str, gmail_message_id: str):
    """
    Get full email content.
    
    Fetches the complete email body on-demand from Gmail API.
    """
    try:
        service = get_gmail_service()
        
        content = service.get_email_content(mailbox_id, gmail_message_id)
        
        if not content:
            raise HTTPException(status_code=404, detail="Email not found")
        
        return content
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting email content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Statistics
# ============================================

@router.get("/stats")
async def get_stats():
    """
    Get Gmail integration statistics.
    """
    try:
        service = get_gmail_service()
        
        if not service.is_configured():
            return {
                "configured": False,
                "mailbox_count": 0,
                "total_emails": 0
            }
        
        stats = service.get_stats()
        stats["configured"] = True
        
        return stats
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# SEND EMAIL via Gmail API
# ============================================

class SendEmailRequest(BaseModel):
    """Send email request"""
    to: List[EmailStr] = Field(..., description="Recipient emails")
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body (plain text)")
    html_body: Optional[str] = Field(None, description="HTML body (optional)")
    from_email: Optional[str] = Field(None, description="Sender email (must be configured mailbox or alias)")
    cc: List[EmailStr] = Field(default=[], description="CC recipients")
    bcc: List[EmailStr] = Field(default=[], description="BCC recipients")
    signature_html: Optional[str] = Field(None, description="Email signature HTML to append")
    reply_to_message_id: Optional[str] = Field(None, description="For threading replies")
    thread_id: Optional[str] = Field(None, description="Gmail thread ID for replies")


@router.post("/send")
async def send_email(request: Request, send_request: SendEmailRequest):
    """
    Send email via Gmail API using domain-wide delegation.
    
    This uses the Gmail API directly - no IMAP/SMTP required.
    The sender email must be a configured mailbox or alias.
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        service = get_gmail_service()
        
        if not service.is_configured():
            raise HTTPException(
                status_code=400, 
                detail="Gmail Workspace service not configured. Please set up service account credentials."
            )
        
        # Use provided from_email or find the first active mailbox
        from_email = send_request.from_email
        if not from_email:
            mailboxes = service.list_mailboxes()
            if not mailboxes:
                raise HTTPException(status_code=400, detail="No mailboxes configured")
            from_email = mailboxes[0]["email"]
        
        # Build HTML body
        html_body = send_request.html_body or send_request.body.replace("\n", "<br>")
        
        # Send email
        result = service.send_email(
            from_email=from_email,
            to=send_request.to,
            subject=send_request.subject,
            body_html=html_body,
            body_plain=send_request.body,
            cc=send_request.cc,
            bcc=send_request.bcc,
            reply_to_message_id=send_request.reply_to_message_id,
            thread_id=send_request.thread_id,
            signature_html=send_request.signature_html
        )
        
        if not result["success"]:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to send email"))
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Legacy Compatibility (for old OAuth routes)
# ============================================

@router.get("/auth/url")
async def get_auth_url_legacy():
    """
    Legacy OAuth endpoint - now returns info about new setup.
    
    The new Gmail integration uses Service Account with Domain-Wide Delegation.
    No individual OAuth consent is required.
    """
    return {
        "message": "OAuth is no longer required for Gmail integration.",
        "instructions": [
            "1. Upload service account credentials via POST /gmail/config/service-account",
            "2. Add mailboxes by email address via POST /gmail/mailboxes",
            "3. Sync emails via POST /gmail/mailboxes/{id}/sync"
        ],
        "new_endpoint": "/gmail/config/status"
    }


@router.get("/accounts")
async def get_accounts_legacy():
    """Legacy endpoint - redirects to new mailboxes list"""
    return await list_mailboxes()
