"""
Panel Bounce Handler — bounce classification, suppression list management.

Uses the same classification logic as outreach_engine/webhook_handler.py
but operates on panel-specific collections in campaign_platform DB.
"""

import os
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pymongo import MongoClient

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
_client = MongoClient(MONGO_URI)
_db = _client["campaign_platform"]

suppression_collection = _db["panel_email_suppression"]
invitation_log_collection = _db["panel_invitation_log"]

# Ensure indexes
try:
    suppression_collection.create_index([("email", 1)], unique=True)
    invitation_log_collection.create_index([("email", 1)])
    invitation_log_collection.create_index([("batch_id", 1)])
    invitation_log_collection.create_index([("ses_message_id", 1)], sparse=True)
except Exception as e:
    logger.warning(f"Index creation warning (panel bounce): {e}")


SOFT_BOUNCE_MAX_RETRIES = 3


class BounceType(str, Enum):
    HARD = "hard"
    SOFT = "soft"


def classify_bounce(
    reason: str = "",
    smtp_code: int = 0,
    sns_bounce_type: str = "",
) -> BounceType:
    """Classify a bounce as hard or soft using SMTP codes, SNS type, and keyword fallback."""
    # SNS bounce type takes precedence
    if sns_bounce_type:
        sbt = sns_bounce_type.lower()
        if sbt in ("permanent", "undetermined"):
            return BounceType.HARD
        if sbt == "transient":
            return BounceType.SOFT

    # SMTP code classification
    if smtp_code:
        if 500 <= smtp_code <= 599:
            return BounceType.HARD
        if 400 <= smtp_code <= 499:
            return BounceType.SOFT

    # Keyword fallback
    reason_lower = (reason or "").lower()
    hard_keywords = [
        "invalid", "does not exist", "user unknown", "no such user",
        "rejected", "permanently", "disabled", "deactivated",
    ]
    soft_keywords = [
        "full", "over quota", "temporarily", "try again", "rate limit",
        "connection", "timeout", "unavailable", "busy",
    ]

    if any(kw in reason_lower for kw in hard_keywords):
        return BounceType.HARD
    if any(kw in reason_lower for kw in soft_keywords):
        return BounceType.SOFT

    # Default to hard (safe side)
    return BounceType.HARD


def is_suppressed(email: str) -> bool:
    """Return True if email is on the panel suppression list."""
    return suppression_collection.count_documents(
        {"email": email.lower().strip()}, limit=1
    ) > 0


def suppress_email(
    email: str,
    reason: str,
    source: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Add email to the suppression list. Returns True if newly added."""
    email = email.lower().strip()
    try:
        suppression_collection.update_one(
            {"email": email},
            {
                "$set": {
                    "reason": reason,
                    "source": source,
                    "suppressed_at": datetime.utcnow(),
                    "metadata": metadata or {},
                }
            },
            upsert=True,
        )
        logger.info(f"Suppressed panel email: {email} reason={reason}")
        return True
    except Exception as e:
        logger.error(f"Failed to suppress email {email}: {e}")
        return False


def has_been_invited(email: str) -> bool:
    """Return True if this email has already been sent an invitation."""
    return invitation_log_collection.count_documents(
        {"email": email.lower().strip(), "status": "sent"}, limit=1
    ) > 0


def log_invitation(
    email: str,
    panelist_id: str,
    batch_id: str,
    ses_message_id: str = "",
    status: str = "sent",
) -> None:
    """Log a sent invitation for duplicate detection."""
    invitation_log_collection.insert_one({
        "email": email.lower().strip(),
        "panelist_id": panelist_id,
        "batch_id": batch_id,
        "ses_message_id": ses_message_id,
        "status": status,
        "sent_at": datetime.utcnow(),
    })


def handle_ses_notification(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process an SNS notification from SES (Bounce or Complaint).
    Returns a dict with action taken.
    """
    notification_type = payload.get("notificationType") or payload.get("Type", "")

    if notification_type == "Bounce":
        bounce = payload.get("bounce", {})
        bounce_type_str = bounce.get("bounceType", "")
        recipients = bounce.get("bouncedRecipients", [])

        results = []
        for recipient in recipients:
            email = recipient.get("emailAddress", "").lower().strip()
            if not email:
                continue

            reason = recipient.get("diagnosticCode", "")
            smtp_code = 0
            status_str = recipient.get("status", "")
            if status_str:
                try:
                    smtp_code = int(status_str.replace(".", "")[:3])
                except (ValueError, IndexError):
                    pass

            bt = classify_bounce(reason=reason, smtp_code=smtp_code, sns_bounce_type=bounce_type_str)

            if bt == BounceType.HARD:
                suppress_email(email, reason="bounce_hard", source="ses_webhook", metadata={
                    "bounce_type": "hard",
                    "diagnostic": reason,
                    "smtp_code": smtp_code,
                })
                # Update invitation log if exists
                invitation_log_collection.update_many(
                    {"email": email, "status": "sent"},
                    {"$set": {"status": "bounced"}},
                )
                results.append({"email": email, "action": "suppressed_hard_bounce"})
            else:
                # Track soft bounce count
                soft_count = invitation_log_collection.count_documents({
                    "email": email,
                    "status": {"$in": ["bounced", "soft_bounced"]},
                })
                if soft_count >= SOFT_BOUNCE_MAX_RETRIES:
                    suppress_email(email, reason="bounce_soft_max", source="ses_webhook", metadata={
                        "bounce_type": "soft_exceeded",
                        "retries": soft_count,
                        "diagnostic": reason,
                    })
                    results.append({"email": email, "action": "suppressed_soft_max"})
                else:
                    invitation_log_collection.update_many(
                        {"email": email, "status": "sent"},
                        {"$set": {"status": "soft_bounced"}},
                    )
                    results.append({"email": email, "action": "soft_bounce_recorded", "count": soft_count + 1})

        return {"type": "bounce", "processed": len(results), "details": results}

    elif notification_type == "Complaint":
        complaint = payload.get("complaint", {})
        recipients = complaint.get("complainedRecipients", [])

        results = []
        for recipient in recipients:
            email = recipient.get("emailAddress", "").lower().strip()
            if not email:
                continue

            suppress_email(email, reason="complaint", source="ses_webhook", metadata={
                "complaint_type": complaint.get("complaintFeedbackType", ""),
            })
            invitation_log_collection.update_many(
                {"email": email, "status": "sent"},
                {"$set": {"status": "complained"}},
            )
            results.append({"email": email, "action": "suppressed_complaint"})

        return {"type": "complaint", "processed": len(results), "details": results}

    return {"type": notification_type, "processed": 0, "details": "unhandled_type"}
