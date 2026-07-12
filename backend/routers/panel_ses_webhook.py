"""
PANEL SES WEBHOOK ROUTER
Receives SNS notifications from Amazon SES for panel invitation emails.
Processes bounces and complaints, updates the suppression list.

Endpoint:
- POST /webhooks/panel-ses  - Receive SNS notifications (Bounce, Complaint)

Setup:
1. In AWS SES, create an SNS topic for bounce/complaint notifications.
2. Subscribe this endpoint URL to the SNS topic.
3. SNS will first send a SubscriptionConfirmation — this handler auto-confirms it.
"""

import base64
import json
import logging
import os
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Panel SES Webhook"])

# This endpoint is public (AWS SNS posts to it with no auth header), so it must
# defend itself. Two controls:
#   1. SSRF guard — SubscribeURL / SigningCertURL are only ever fetched when the
#      host is a real AWS SNS endpoint (sns.<region>.amazonaws.com over https).
#      Without this an attacker could POST a SubscriptionConfirmation with
#      SubscribeURL=http://169.254.169.254/... and make the server fetch cloud
#      metadata (SSRF).
#   2. Signature verification — the SNS message signature is checked against the
#      AWS-published signing certificate, so forged Bounce/Complaint payloads
#      can't poison the suppression list (which would silently blackhole real
#      panelist emails).
# Set PANEL_SES_SKIP_VERIFY=true only for local testing.

_SNS_HOST_SUFFIX = ".amazonaws.com"


def _is_valid_sns_url(url: Optional[str]) -> bool:
    try:
        p = urlparse(url or "")
    except Exception:
        return False
    host = (p.hostname or "").lower()
    return (
        p.scheme == "https"
        and host.startswith("sns.")
        and host.endswith(_SNS_HOST_SUFFIX)
    )


def _sns_string_to_sign(payload: Dict[str, Any]) -> Optional[bytes]:
    """Build the canonical string AWS signs, per SNS message type."""
    mtype = payload.get("Type", "")
    if mtype == "Notification":
        keys = ["Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"]
    elif mtype in ("SubscriptionConfirmation", "UnsubscribeConfirmation"):
        keys = ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token",
                "TopicArn", "Type"]
    else:
        return None
    parts = []
    for k in keys:
        if k in payload and payload[k] is not None:
            parts.append(k)
            parts.append(str(payload[k]))
    return ("\n".join(parts) + "\n").encode("utf-8")


def _verify_sns_signature(payload: Dict[str, Any]) -> bool:
    """Verify an SNS message signature against the AWS signing certificate."""
    if os.getenv("PANEL_SES_SKIP_VERIFY", "").lower() in ("1", "true", "yes"):
        return True
    cert_url = payload.get("SigningCertURL")
    signature_b64 = payload.get("Signature")
    if not (cert_url and signature_b64):
        logger.warning("[ses-webhook] missing SigningCertURL/Signature — rejecting")
        return False
    if not _is_valid_sns_url(cert_url):
        logger.warning(f"[ses-webhook] SigningCertURL not an AWS SNS host: {cert_url}")
        return False
    string_to_sign = _sns_string_to_sign(payload)
    if string_to_sign is None:
        return False
    try:
        from cryptography.x509 import load_pem_x509_certificate
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes

        with httpx.Client(timeout=5) as client:
            cert_pem = client.get(cert_url).content
        cert = load_pem_x509_certificate(cert_pem)
        # SignatureVersion 1 = SHA1withRSA; 2 = SHA256withRSA
        algo = hashes.SHA256() if str(payload.get("SignatureVersion")) == "2" else hashes.SHA1()
        cert.public_key().verify(
            base64.b64decode(signature_b64), string_to_sign, padding.PKCS1v15(), algo)
        return True
    except Exception as e:
        logger.warning(f"[ses-webhook] signature verification failed: {e}")
        return False


@router.post("/panel-ses")
async def handle_ses_webhook(request: Request):
    """
    Receive and process Amazon SNS notifications from SES.

    Handles:
    - SubscriptionConfirmation: Auto-confirms the SNS subscription
    - Notification: Processes Bounce/Complaint events via panel_bounce_handler
    """
    try:
        body = await request.body()
        payload = json.loads(body)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to parse SES webhook payload: {e}")
        return {"status": "error", "message": "invalid_payload"}

    # Reject anything whose SNS signature doesn't verify — this is the only
    # thing standing between the public internet and the suppression list.
    if not _verify_sns_signature(payload):
        logger.warning("[ses-webhook] rejected message with invalid signature")
        return {"status": "rejected", "message": "invalid_signature"}

    message_type = request.headers.get("x-amz-sns-message-type", "") or payload.get("Type", "")

    # ---- SNS Subscription Confirmation ----
    if message_type == "SubscriptionConfirmation":
        subscribe_url = payload.get("SubscribeURL")
        # SSRF guard: only ever GET a genuine AWS SNS https URL.
        if subscribe_url and _is_valid_sns_url(subscribe_url):
            logger.info(f"Confirming SNS subscription: {subscribe_url}")
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    await client.get(subscribe_url)
                logger.info("SNS subscription confirmed successfully")
            except Exception as e:
                logger.error(f"Failed to confirm SNS subscription: {e}")
        elif subscribe_url:
            logger.warning(f"[ses-webhook] refusing non-SNS SubscribeURL: {subscribe_url}")
        return {"status": "subscription_confirmed"}

    # ---- SNS Notification ----
    if message_type == "Notification":
        # The actual SES event is nested in the "Message" field as a JSON string
        message_str = payload.get("Message", "{}")
        try:
            ses_event = json.loads(message_str) if isinstance(message_str, str) else message_str
        except json.JSONDecodeError:
            logger.error(f"Failed to parse SES event from SNS Message")
            return {"status": "error", "message": "invalid_ses_event"}

        try:
            from services.panel_bounce_handler import handle_ses_notification
            result = handle_ses_notification(ses_event)
            logger.info(f"SES webhook processed: {result}")
            return {"status": "processed", **result}
        except Exception as e:
            logger.error(f"Error processing SES notification: {e}")
            return {"status": "error", "message": str(e)}

    logger.warning(f"Unhandled SNS message type: {message_type}")
    return {"status": "ignored", "message_type": message_type}
