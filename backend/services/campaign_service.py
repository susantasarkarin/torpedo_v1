"""
Campaign Service
================
Business logic for campaign sending, contact upload, and link tracking.

Extracted from routers/legacy_campaign.py (Phase 10).
Routers call these functions — they must not contain orchestration logic.
"""

import asyncio
import logging
import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Tuple

from bson import ObjectId

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config (read once at import; override via env)
# ---------------------------------------------------------------------------
API_BASE = os.getenv("API_BASE", "http://139.59.32.72:8000")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Cogentix Research")


# ---------------------------------------------------------------------------
# Tracking helpers (pure functions — no I/O)
# ---------------------------------------------------------------------------

def rewrite_links_with_tracking(html_body: str, campaign_id: str, email: str) -> str:
    """Replace all href values with click-tracking redirect URLs."""
    return re.sub(
        r'href="(http[s]?://[^"]+)"',
        lambda m: f'href="{API_BASE}/track/click?c={campaign_id}&e={email}&url={m.group(1)}"',
        html_body,
    )


def inject_open_tracking(html_body: str, campaign_id: str, email: str) -> str:
    """Append a 1×1 invisible tracking pixel to an HTML email body."""
    pixel = f'<img src="{API_BASE}/track/open?c={campaign_id}&e={email}" width="1" height="1" style="display:none;" />'
    return html_body + pixel


def personalize_html(html_content: str, contact: Dict[str, Any]) -> str:
    """Substitute template variables with contact-specific values."""
    out = re.sub(r"{{\s*contact\.name\s*}}", contact.get("name") or "there", html_content)
    out = re.sub(r"{{\s*sender\.companyName\s*}}", "Cogentix Research", out)
    return out


# ---------------------------------------------------------------------------
# SMTP delivery (synchronous — call via asyncio.to_thread from async routes)
# ---------------------------------------------------------------------------

def send_email_html_sync(to_email: str, subject: str, html_content: str) -> None:
    """
    Send a single HTML email via SMTP (blocking).
    Raises on misconfiguration or delivery failure.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        raise RuntimeError(
            "SMTP credentials not configured — set SMTP_USER and SMTP_PASSWORD env vars."
        )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_content, "html"))
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [to_email], msg.as_string())


# ---------------------------------------------------------------------------
# Campaign send orchestration
# ---------------------------------------------------------------------------

async def send_campaign(
    contacts: List[Dict[str, Any]],
    template: Dict[str, Any],
    reports_col: Any,
) -> Dict[str, Any]:
    """
    Orchestrate a batch email send.

    Steps:
      1. Create a campaign report document.
      2. For each contact: personalise HTML, add tracking, send via SMTP.
      3. Record per-email send/fail results.

    Returns dict with keys: campaign_id, sent, failed.

    NOTE: SMTP send is blocking — each email runs in a thread pool to avoid
    starving the event loop.
    """
    subject = template.get("subject", "No Subject")
    html_content = template.get("htmlContent", "")
    campaign_id = str(ObjectId())

    reports_col.insert_one({
        "campaignId": campaign_id,
        "subject": subject,
        "sent": [],
        "opens": [],
        "clicks": [],
        "createdAt": datetime.utcnow(),
    })

    sent: List[str] = []
    failed: List[Dict[str, str]] = []

    for contact in contacts:
        email = (contact.get("email") or "").strip()
        if not email:
            continue
        try:
            personalized = personalize_html(html_content, contact)
            personalized = rewrite_links_with_tracking(personalized, campaign_id, email)
            personalized = inject_open_tracking(personalized, campaign_id, email)

            # Non-blocking: send in thread pool
            await asyncio.to_thread(send_email_html_sync, email, subject, personalized)

            sent.append(email)
            reports_col.update_one(
                {"campaignId": campaign_id},
                {"$push": {"sent": {"email": email, "time": datetime.utcnow()}}},
            )
        except Exception as exc:
            logger.warning("Send failed for %s: %s", email, exc)
            failed.append({"email": email, "error": str(exc)})

    logger.info("Campaign %s: sent=%d failed=%d", campaign_id, len(sent), len(failed))
    return {"campaign_id": campaign_id, "sent": sent, "failed": failed}


# ---------------------------------------------------------------------------
# Contact upload / deduplication
# ---------------------------------------------------------------------------

def upload_contacts_batch(
    raw_contacts: List[Dict[str, Any]],
    lists_col: Any,
    contacts_col: Any,
) -> List[Dict[str, Any]]:
    """
    Resolve list IDs, deduplicate by (email, listId/listName), and insert
    new contacts.  Returns the list of successfully inserted contacts.
    """
    inserted: List[Dict[str, Any]] = []

    for contact in raw_contacts:
        email = (contact.get("email") or "").strip()
        list_name = contact.get("listName")
        incoming_list_id = contact.get("listId")
        if not email:
            continue

        resolved_list_id = None
        try:
            if incoming_list_id and ObjectId.is_valid(str(incoming_list_id)):
                resolved_list_id = str(incoming_list_id)
            elif incoming_list_id:
                found = lists_col.find_one({"name": incoming_list_id})
                resolved_list_id = str(found["_id"]) if found else incoming_list_id
            elif list_name:
                found = lists_col.find_one({"name": list_name})
                resolved_list_id = str(found["_id"]) if found else None
        except Exception as exc:
            logger.warning("upload_contacts_batch: list id resolution error: %s", exc)

        query: Dict[str, Any] = {"email": email}
        if resolved_list_id:
            query["listId"] = resolved_list_id
        elif list_name:
            query["listName"] = list_name

        if contacts_col.find_one(query):
            continue  # deduplicate

        if list_name:
            contact["listName"] = list_name
        if resolved_list_id:
            contact["listId"] = resolved_list_id

        try:
            result = contacts_col.insert_one(contact)
            contact["_id"] = str(result.inserted_id)
            inserted.append(contact)
        except Exception as exc:
            logger.error("MongoDB insert failed for %s: %s", email, exc)

    return inserted


# ---------------------------------------------------------------------------
# List cascade delete
# ---------------------------------------------------------------------------

def delete_list_cascade(list_id: str, lists_col: Any, contacts_col: Any) -> int:
    """
    Delete a list document and all its associated contacts.
    Returns deleted_count for the contacts (informational).
    """
    lists_col.delete_one({"_id": ObjectId(list_id)})
    result = contacts_col.delete_many({"listId": list_id})
    logger.info("List %s deleted with %d cascaded contacts", list_id, result.deleted_count)
    return result.deleted_count
