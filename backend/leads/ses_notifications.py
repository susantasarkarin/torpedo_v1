"""
SES SNS NOTIFICATION HANDLER
============================
Turns SES bounce / complaint / (List-Unsubscribe click) notifications into
suppression-list entries automatically, so an address that bounces today is
never qualified again tomorrow.

Wiring (one-time, see RUNBOOK):
  SES configuration set -> SNS topic -> HTTPS subscription pointing at the
  route below (or an SQS consumer calling process_ses_notification directly).

The handler is transport-agnostic: `process_ses_notification(payload)` takes
the decoded SNS message body and is unit-testable without AWS. A FastAPI
router is provided for the HTTPS path, including the SubscriptionConfirmation
handshake.

Only permanent bounces suppress. Transient bounces (mailbox full, greylisting)
are logged but NOT suppressed — suppressing those throws away good leads.
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ses_notifications")


# ============================================================
# CORE HANDLER (no AWS, no web framework — pure logic)
# ============================================================

def process_ses_notification(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle one decoded SES notification. Returns a summary dict:
        {"type": ..., "suppressed": [emails], "ignored": [emails]}
    Never raises — a bad notification must not 500 the endpoint into SNS
    retry storms.
    """
    result = {"type": "unknown", "suppressed": [], "ignored": []}
    try:
        notification_type = payload.get("notificationType") or payload.get("eventType") or ""
        result["type"] = notification_type

        if notification_type == "Bounce":
            _handle_bounce(payload.get("bounce") or {}, result)
        elif notification_type == "Complaint":
            _handle_complaint(payload.get("complaint") or {}, result)
        else:
            logger.info("ses notification ignored type=%r", notification_type)
    except Exception as e:
        logger.error("ses notification processing failed: %s", e)
    return result


def _handle_bounce(bounce: Dict[str, Any], result: Dict[str, Any]) -> None:
    bounce_type = bounce.get("bounceType", "")
    recipients = _recipient_emails(bounce.get("bouncedRecipients"))

    if bounce_type == "Permanent":
        for email in recipients:
            _suppress(email, "bounced")
            result["suppressed"].append(email)
        logger.info("permanent bounce suppressed count=%d", len(recipients))
    else:
        # Transient/Undetermined: do not suppress — the address may be fine.
        result["ignored"].extend(recipients)
        logger.info("transient bounce ignored type=%r count=%d",
                    bounce_type, len(recipients))


def _handle_complaint(complaint: Dict[str, Any], result: Dict[str, Any]) -> None:
    recipients = _recipient_emails(complaint.get("complainedRecipients"))
    for email in recipients:
        _suppress(email, "complaint")
        result["suppressed"].append(email)
    logger.info("complaint suppressed count=%d", len(recipients))


def process_unsubscribe(email: str) -> bool:
    """Called by the unsubscribe endpoint. Returns True if suppressed."""
    if not email or "@" not in email:
        return False
    _suppress(email, "unsubscribed")
    return True


def _recipient_emails(recipients: Optional[List[Dict[str, Any]]]) -> List[str]:
    out = []
    for r in recipients or []:
        email = (r.get("emailAddress") or "").strip().lower()
        if email:
            out.append(email)
    return out


def _suppress(email: str, reason: str) -> None:
    from leads.outreach_mailer import record_bounce, record_unsubscribe
    if reason == "unsubscribed":
        record_unsubscribe(email)
    else:
        # record_bounce writes reason='bounced'; complaints go through the
        # manager directly to keep the true reason.
        if reason == "complaint":
            from leads.outreach_qualification import _get_suppression_manager
            try:
                _get_suppression_manager().add(email, "complaint")
            except Exception as e:
                logger.error("failed to suppress complaint %s: %s", email, e)
        else:
            record_bounce(email)


# ============================================================
# SNS ENVELOPE
# ============================================================

def unwrap_sns_envelope(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    SNS HTTPS delivery wraps the SES payload in an envelope with a JSON-string
    `Message`. Returns the decoded SES payload, or None for non-Notification
    envelope types (handled separately).
    """
    if body.get("Type") != "Notification":
        return None
    try:
        return json.loads(body.get("Message") or "{}")
    except (json.JSONDecodeError, TypeError):
        logger.warning("SNS Message field was not valid JSON")
        return None


# ============================================================
# FASTAPI ROUTER (optional — mount in the main app)
# ============================================================

def build_router():
    """
    Returns a FastAPI APIRouter with:
      POST /outreach/ses-notifications   (SNS subscription endpoint)
      GET  /outreach/unsubscribe         (?email=... — List-Unsubscribe target)
    Kept in a factory so importing this module never requires FastAPI.
    """
    from fastapi import APIRouter, Request
    from fastapi.responses import PlainTextResponse

    router = APIRouter()

    @router.post("/outreach/ses-notifications")
    async def ses_notifications(request: Request):
        try:
            body = json.loads(await request.body())
        except Exception:
            return {"ok": False, "error": "invalid json"}

        envelope_type = body.get("Type", "")
        if envelope_type == "SubscriptionConfirmation":
            # Confirm by fetching the SubscribeURL, as SNS requires.
            url = body.get("SubscribeURL", "")
            if url.startswith("https://") and ".amazonaws.com/" in url:
                import urllib.request
                urllib.request.urlopen(url, timeout=10)  # nosec - AWS-validated URL
                logger.info("SNS subscription confirmed")
                return {"ok": True, "confirmed": True}
            logger.warning("rejected non-AWS SubscribeURL")
            return {"ok": False}

        payload = unwrap_sns_envelope(body)
        if payload is None:
            return {"ok": True, "ignored": envelope_type}
        return {"ok": True, **process_ses_notification(payload)}

    @router.get("/outreach/unsubscribe")
    async def unsubscribe(email: str = ""):
        done = process_unsubscribe(email)
        return PlainTextResponse(
            "You have been unsubscribed. You will not hear from us again."
            if done else "Invalid unsubscribe request.")

    return router
