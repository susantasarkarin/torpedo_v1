"""
Panel Bounce Handler — bounce classification, suppression list management.

Uses the same classification logic as outreach_engine/webhook_handler.py
but operates on panel-specific collections in campaign_platform DB.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from pymongo import MongoClient
from pymongo import ReturnDocument

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
_client = MongoClient(MONGO_URI)
_db = _client["campaign_platform"]

suppression_collection = _db["panel_email_suppression"]
invitation_log_collection = _db["panel_invitation_log"]
panelists_collection = _db["panelists"]

# Ensure indexes
try:
    suppression_collection.create_index([("email", 1)], unique=True)
    invitation_log_collection.create_index([("email", 1)])
    invitation_log_collection.create_index([("batch_id", 1)])
    invitation_log_collection.create_index([("ses_message_id", 1)], sparse=True)
    invitation_log_collection.create_index([("invite_token", 1)], unique=True, sparse=True)
    invitation_log_collection.create_index([("sent_at", -1)])
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


def has_been_invited_today(email: str, timezone_name: str = "Asia/Kolkata") -> bool:
    """Return True if an invite was sent to this email during the current local day."""
    normalized = email.lower().strip()
    if not normalized:
        return False

    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("UTC")

    now_local = datetime.now(tz)
    day_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    next_day_local = day_start_local + timedelta(days=1)

    day_start_utc = day_start_local.astimezone(timezone.utc).replace(tzinfo=None)
    next_day_utc = next_day_local.astimezone(timezone.utc).replace(tzinfo=None)

    return invitation_log_collection.count_documents(
        {
            "email": normalized,
            "status": "sent",
            "sent_at": {"$gte": day_start_utc, "$lt": next_day_utc},
        },
        limit=1,
    ) > 0


def is_double_opted_in(email: str) -> bool:
    """Return True if panelist has completed double opt-in confirmation."""
    normalized = email.lower().strip()
    if not normalized:
        return False

    panelist = panelists_collection.find_one(
        {"email": normalized},
        {"double_opt_in_completed": 1, "email_verified": 1, "status": 1},
    )
    if not panelist:
        return False

    if panelist.get("double_opt_in_completed"):
        return True

    status = str(panelist.get("status") or "").strip().lower()
    return bool(panelist.get("email_verified")) and status in {"active", "confirmed", "double_opted_in"}


def mark_invite_clicked(invite_token: str) -> Optional[Dict[str, Any]]:
    """Mark invitation link click and return invitation metadata if token exists."""
    token = str(invite_token or "").strip()
    if not token:
        return None

    now = datetime.utcnow()
    doc = invitation_log_collection.find_one_and_update(
        {"invite_token": token},
        {
            "$set": {"last_clicked_at": now},
            "$inc": {"click_count": 1},
        },
        return_document=ReturnDocument.AFTER,
    )

    if not doc:
        return None

    if not doc.get("clicked_at"):
        invitation_log_collection.update_one(
            {"_id": doc["_id"]},
            {"$set": {"clicked_at": now}},
        )

    return {
        "email": doc.get("email", ""),
        "panelist_id": doc.get("panelist_id", ""),
        "invite_token": token,
    }


def mark_double_opt_in_completed(
    email: str = "",
    invite_token: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Mark a panelist as confirmed via double opt-in and stop future invite workflow."""
    normalized_email = str(email or "").strip().lower()
    token = str(invite_token or "").strip()

    if not normalized_email and token:
        doc = invitation_log_collection.find_one({"invite_token": token}, {"email": 1})
        if doc:
            normalized_email = str(doc.get("email") or "").strip().lower()

    if not normalized_email:
        return False

    now = datetime.utcnow()
    panelists_collection.update_one(
        {"email": normalized_email},
        {
            "$set": {
                "double_opt_in_completed": True,
                "double_opt_in_completed_at": now,
                "email_verified": True,
                "updated_at": now,
            }
        },
    )

    update_payload = {
        "$set": {
            "status": "confirmed",
            "confirmed_at": now,
            "confirmation_metadata": metadata or {},
        }
    }
    invitation_log_collection.update_many(
        {"email": normalized_email, "status": {"$in": ["sent", "soft_bounced"]}},
        update_payload,
    )
    if token:
        invitation_log_collection.update_one({"invite_token": token}, update_payload)

    return True


def log_invitation(
    email: str,
    panelist_id: str,
    batch_id: str,
    ses_message_id: str = "",
    status: str = "sent",
    invite_token: str = "",
    template_version: str = "",
) -> None:
    """Log a sent invitation for duplicate detection."""
    invitation_log_collection.insert_one({
        "email": email.lower().strip(),
        "panelist_id": panelist_id,
        "batch_id": batch_id,
        "ses_message_id": ses_message_id,
        "status": status,
        "invite_token": invite_token,
        "template_version": template_version,
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
