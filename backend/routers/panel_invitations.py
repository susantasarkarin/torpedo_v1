"""
PANEL INVITATIONS ROUTER
Admin endpoints for sending invitation emails to panelists via Amazon SES.

Endpoints:
- GET  /panel-admin/invitations/preview  - Get eligible panelist count before sending
- POST /panel-admin/invitations/send     - Trigger bulk invitation emails
- GET  /panel-admin/invitations/status   - Get send statistics
"""

import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request, Query, Body

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/panel-admin/invitations", tags=["Panel Invitations"])


# ============== HELPERS ==============

def verify_admin_session(request: Request):
    """Verify admin session from Authorization header"""
    session_id = request.headers.get("Authorization")
    if not session_id:
        raise HTTPException(status_code=401, detail="Missing session token")
    return session_id


# ============== ENDPOINTS ==============

@router.get("/preview")
async def invitation_preview(
    request: Request,
    country: Optional[str] = Query(None),
    daily_mode: bool = Query(False),
):
    """
    Get the count of eligible panelists who would receive invitations.
    Excludes suppressed (bounced/complained) and already-invited panelists.
    """
    verify_admin_session(request)

    try:
        from services.panel_email_service import get_eligible_count
        count = get_eligible_count(country=country, daily_mode=daily_mode)
        return {"eligible_count": count, "country": country or "all", "daily_mode": daily_mode}
    except Exception as e:
        logger.error(f"Error getting invitation preview: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send")
async def send_invitations(
    request: Request,
    data: Dict[str, Any] = Body(default={}),
):
    """
    Trigger bulk invitation emails to eligible panelists.

    Body (optional):
    - country: str — filter by country
    - force_resend: bool — re-send to already invited panelists (default false)
    - daily_mode: bool — enforce one invite per local day and continue until confirmed
    - daily_cap: int — max sends in this run when daily_mode=true
    """
    verify_admin_session(request)

    country = data.get("country")
    force_resend = data.get("force_resend", False)
    daily_mode = bool(data.get("daily_mode", False))
    daily_cap = data.get("daily_cap")

    try:
        from services.panel_email_service import send_bulk_invitations
        result = send_bulk_invitations(
            country=country,
            force_resend=force_resend,
            daily_mode=daily_mode,
            daily_cap=daily_cap,
        )
        return result
    except Exception as e:
        logger.error(f"Error sending invitations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def invitation_status(request: Request):
    """
    Get invitation send statistics across all batches.
    """
    verify_admin_session(request)

    try:
        from services.panel_bounce_handler import (
            invitation_log_collection,
            suppression_collection,
            panelists_collection,
        )

        total_sent = invitation_log_collection.count_documents({"status": "sent"})
        total_bounced = invitation_log_collection.count_documents({"status": "bounced"})
        total_soft_bounced = invitation_log_collection.count_documents({"status": "soft_bounced"})
        total_complained = invitation_log_collection.count_documents({"status": "complained"})
        total_confirmed = invitation_log_collection.count_documents({"status": "confirmed"})
        total_failed = invitation_log_collection.count_documents({"status": "failed"})
        total_suppressed = suppression_collection.count_documents({})
        total_double_opted_in = panelists_collection.count_documents({"double_opt_in_completed": True})

        return {
            "sent": total_sent,
            "bounced": total_bounced,
            "soft_bounced": total_soft_bounced,
            "complained": total_complained,
            "confirmed": total_confirmed,
            "failed": total_failed,
            "suppressed_emails": total_suppressed,
            "double_opt_in_completed": total_double_opted_in,
        }
    except Exception as e:
        logger.error(f"Error getting invitation status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
