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

import json
import logging
from typing import Dict, Any

import httpx
from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Panel SES Webhook"])


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

    message_type = request.headers.get("x-amz-sns-message-type", "")

    # ---- SNS Subscription Confirmation ----
    if message_type == "SubscriptionConfirmation":
        subscribe_url = payload.get("SubscribeURL")
        if subscribe_url:
            logger.info(f"Confirming SNS subscription: {subscribe_url}")
            try:
                async with httpx.AsyncClient() as client:
                    await client.get(subscribe_url)
                logger.info("SNS subscription confirmed successfully")
            except Exception as e:
                logger.error(f"Failed to confirm SNS subscription: {e}")
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
