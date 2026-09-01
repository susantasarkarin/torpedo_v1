"""
PANEL INVITE JOIN ROUTER
Public endpoints for unique invite links and double opt-in confirmation callbacks.
"""

import hashlib
import hmac
import json
import os
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Body
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/panel/invite", tags=["Panel Invite Join"])

PANEL_SIGNUP_URL = os.getenv("PANEL_SIGNUP_URL", "https://panel.surveyfieldwork.com/signup")
PANEL_CONFIRM_SECRET = (os.getenv("PANEL_CONFIRM_SECRET", "") or "").strip()


def _build_signup_redirect(token: str) -> str:
    if not token:
        return PANEL_SIGNUP_URL
    sep = "&" if "?" in PANEL_SIGNUP_URL else "?"
    return f"{PANEL_SIGNUP_URL}{sep}invite_token={token}"


def _verify_signature(raw_body: bytes, provided_signature: str) -> bool:
    if not PANEL_CONFIRM_SECRET:
        return True
    if not provided_signature:
        return False
    expected = hmac.new(
        PANEL_CONFIRM_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, provided_signature.strip())


@router.get("/join")
async def panel_invite_join(token: str = Query("", min_length=1)):
    """Track invite click and redirect user to panel signup page."""
    try:
        from services.panel_bounce_handler import mark_invite_clicked

        mark_invite_clicked(token)
    except Exception as e:
        logger.warning(f"Invite click tracking failed for token={token[:8]}...: {e}")

    return RedirectResponse(url=_build_signup_redirect(token), status_code=302)


@router.post("/confirm")
async def panel_invite_confirm(
    request: Request,
    data: Dict[str, Any] = Body(default={}),
):
    """
    Confirmation callback from panel system after double opt-in completion.

    Expected JSON body:
    {
      "email": "user@example.com",
      "token": "invite-token",
      "status": "confirmed"
    }

    Optional signature header:
    - X-Panel-Signature: hex(HMAC_SHA256(secret, raw_body))
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Panel-Signature", "")

    if not _verify_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    email = str(data.get("email") or "").strip().lower()
    token = str(data.get("token") or data.get("invite_token") or "").strip()
    status = str(data.get("status") or "confirmed").strip().lower()

    if status not in {"confirmed", "double_opt_in_completed", "opted_in"}:
        return {"updated": False, "reason": "status_not_confirmed"}

    if not email and not token:
        raise HTTPException(status_code=400, detail="email or token is required")

    metadata: Dict[str, Any] = {
        "source": "panel_confirm_webhook",
        "status": status,
    }
    extra = data.get("metadata")
    if isinstance(extra, dict):
        metadata.update(extra)

    try:
        from services.panel_bounce_handler import mark_double_opt_in_completed

        updated = mark_double_opt_in_completed(email=email, invite_token=token, metadata=metadata)

        # Mirror the registration into the canonical CRM spine (best-effort)
        if updated and email:
            try:
                from app.services.spine_connector import mirror_panelist_registration_to_spine
                mirror_panelist_registration_to_spine(email, country=metadata.get("country"))
            except Exception as _spine_err:
                logger.debug(f"spine mirror skipped: {_spine_err}")

        return {"updated": bool(updated), "email": email or None}
    except Exception as e:
        logger.error(f"Failed to process panel confirm callback: {e}")
        raise HTTPException(status_code=500, detail="Failed to process confirmation")
