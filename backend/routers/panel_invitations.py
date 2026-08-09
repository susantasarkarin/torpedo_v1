"""
PANEL INVITATIONS ROUTER
Admin endpoints for sending invitation emails to panelists via Amazon SES.

Endpoints:
- GET  /panel-admin/invitations/preview  - Get eligible panelist count before sending
- POST /panel-admin/invitations/send     - Trigger bulk invitation emails
- GET  /panel-admin/invitations/status   - Get send statistics
"""

import asyncio
import logging
import threading
from datetime import datetime
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
        count = await asyncio.to_thread(get_eligible_count, country=country, daily_mode=daily_mode)
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
    - daily_mode: bool — enforce the per-address invite cooldown
      (PANEL_INVITE_MIN_GAP_DAYS, default 3 days) and continue until confirmed
    - daily_cap: int — max sends in this run when daily_mode=true
    """
    verify_admin_session(request)

    country = data.get("country")
    force_resend = data.get("force_resend", False)
    daily_mode = bool(data.get("daily_mode", False))
    daily_cap = data.get("daily_cap")

    try:
        from services.panel_email_service import send_bulk_invitations
        import uuid as _uuid
        job_id = f"invite-{_uuid.uuid4().hex[:10]}"
        started_at = datetime.utcnow().isoformat()

        def _run():
            try:
                result = send_bulk_invitations(
                    country=country,
                    force_resend=force_resend,
                    daily_mode=daily_mode,
                    daily_cap=daily_cap,
                )
                logger.info(f"[{job_id}] Bulk invite complete: {result}")
            except Exception as exc:
                logger.error(f"[{job_id}] Bulk invite failed: {exc}")

        threading.Thread(target=_run, daemon=True, name=f"invite-{job_id}").start()

        return {
            "job_id": job_id,
            "status": "started",
            "started_at": started_at,
            "message": "Invitation job started in background. Monitor logs for progress.",
            "country": country or "all",
            "daily_mode": daily_mode,
        }
    except Exception as e:
        logger.error(f"Error starting invitation job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-send")
async def send_test_invitation(
    request: Request,
    data: Dict[str, Any] = Body(default={}),
):
    """
    Send a single test invitation email to a specified address.
    Body:
    - to_email: str (required) — recipient address
    - first_name: str (optional) — name to personalise the greeting
    """
    verify_admin_session(request)

    to_email = data.get("to_email", "").strip()
    if not to_email or "@" not in to_email:
        raise HTTPException(status_code=422, detail="Valid to_email is required")

    first_name = data.get("first_name", "").strip()
    test_token = "test-preview-token"

    try:
        from services.panel_email_service import send_invitation_email
        success, details = await asyncio.to_thread(
            send_invitation_email,
            to_email=to_email,
            first_name=first_name,
            invite_token=test_token,
        )
        if success:
            return {"sent": True, "to": to_email, "ses_message_id": details.get("ses_message_id")}
        else:
            raise HTTPException(status_code=500, detail=details.get("message") or details.get("error") or "SES error")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending test invitation to {to_email}: {e}")
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


@router.get("/ses-quota")
async def ses_quota(request: Request):
    """Live SES send quota and the headroom reserved for transactional mail.

    Exists to answer "why didn't the verification / password-reset email
    arrive?" — if sent_last_24h is at max_24h, SES is throttling and the bulk
    invite run has eaten the reserve.
    """
    verify_admin_session(request)

    try:
        from services.panel_email_service import (
            _get_ses_client, PANEL_SES_RESERVE, PANEL_DAILY_SEND_CAP,
        )

        quota = await asyncio.to_thread(lambda: _get_ses_client().get_send_quota())
        max_24h = int(quota.get("Max24HourSend") or 0)
        sent_24h = int(quota.get("SentLast24Hours") or 0)
        remaining = max(0, max_24h - sent_24h) if max_24h > 0 else None

        return {
            "max_24h": max_24h,
            "sent_last_24h": sent_24h,
            "remaining": remaining,
            "max_send_rate": quota.get("MaxSendRate"),
            "transactional_reserve": PANEL_SES_RESERVE,
            "bulk_daily_cap": PANEL_DAILY_SEND_CAP,
            "bulk_budget_now": max(0, max_24h - sent_24h - PANEL_SES_RESERVE) if max_24h > 0 else None,
            "transactional_at_risk": remaining is not None and remaining < PANEL_SES_RESERVE,
        }
    except Exception as e:
        logger.error(f"Error reading SES quota: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== REGISTRATION SYNC ==============

@router.post("/sync-registrations")
async def sync_registrations(
    request: Request,
    data: Dict[str, Any] = Body(default={}),
):
    """
    Pull SFW-panel signups and mark matching panelists as registered
    (double_opt_in_completed). Normally runs daily via Celery; this triggers it
    on demand. Body (optional): since (ISO datetime) to limit to recent signups.
    """
    verify_admin_session(request)

    since = data.get("since")
    try:
        from services.panel_sync_service import sync_registrations_from_sfw
        result = await asyncio.to_thread(sync_registrations_from_sfw, since)
        return {"status": "completed", **result}
    except Exception as e:
        logger.error(f"Error syncing panel registrations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== LOGIN INVITATIONS ==============

@router.get("/login/preview")
async def login_invitation_preview(
    request: Request,
    country: Optional[str] = Query(None),
):
    """
    Get the count of registered panelists eligible for login invitations.
    """
    verify_admin_session(request)

    try:
        from services.panel_bounce_handler import panelists_collection, invitation_log_collection
        from datetime import datetime, timezone, timedelta
        from zoneinfo import ZoneInfo

        query = {"double_opt_in_completed": True}
        if country:
            query["country"] = {"$regex": f"^{country}$", "$options": "i"}

        all_panelists = list(panelists_collection.find(query, {"email": 1}))
        email_list = [(p.get("email") or "").lower().strip() for p in all_panelists if p.get("email")]
        email_list = list(set(email_list))  # Deduplicate

        # Check how many already sent login email today
        try:
            tz = ZoneInfo("Asia/Kolkata")
        except Exception:
            tz = ZoneInfo("UTC")

        now_local = datetime.now(tz)
        day_start_utc = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
        next_day_utc = day_start_utc + timedelta(days=1)

        already_sent_today = invitation_log_collection.count_documents(
            {"email": {"$in": email_list}, "status": "sent", "type": "login",
             "sent_at": {"$gte": day_start_utc, "$lt": next_day_utc}}
        )

        count = len(email_list) - already_sent_today
        return {
            "eligible_count": max(0, count),
            "total_registered": len(email_list),
            "already_sent_today": already_sent_today,
            "country": country or "all",
        }
    except Exception as e:
        logger.error(f"Error getting login invitation preview: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/login/send")
async def send_login_invitations(
    request: Request,
    data: Dict[str, Any] = Body(default={}),
):
    """
    Trigger bulk login invitation emails to registered panelists.

    Body (optional):
    - country: str — filter by country
    - daily_cap: int — max sends in this run (default 6000)
    """
    verify_admin_session(request)

    country = data.get("country")
    daily_cap = data.get("daily_cap")

    try:
        from services.panel_email_service import send_bulk_login_invitations
        import uuid as _uuid
        job_id = f"login-invite-{_uuid.uuid4().hex[:10]}"
        started_at = datetime.utcnow().isoformat()

        def _run():
            try:
                result = send_bulk_login_invitations(
                    country=country,
                    daily_cap=daily_cap,
                )
                logger.info(f"[{job_id}] Bulk login invite complete: {result}")
            except Exception as exc:
                logger.error(f"[{job_id}] Bulk login invite failed: {exc}")

        threading.Thread(target=_run, daemon=True, name=f"login-invite-{job_id}").start()

        return {
            "job_id": job_id,
            "status": "started",
            "started_at": started_at,
            "message": "Login invitation job started in background. Monitor logs for progress.",
            "country": country or "all",
        }
    except Exception as e:
        logger.error(f"Error starting login invitation job: {e}")
        raise HTTPException(status_code=500, detail=str(e))
