"""
Panel mail through Google Workspace (Gmail API, domain-wide delegation).

Panelist mail is sent from the SurveyFieldwork Workspace mailbox, not SES
(owner, 2026-10-14) — the same mailbox the SurveyFieldwork Panel itself sends
from. Uses the service account Torpedo already stores for its Gmail
integration (GmailWorkspaceService, torpedo_gmail config).
"""

import base64
import logging
import os
from email.message import Message
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

PANEL_GMAIL_SENDER = os.getenv("PANEL_GMAIL_SENDER", "panel@surveyfieldwork.com")
PANEL_GMAIL_FROM_NAME = os.getenv("PANEL_GMAIL_FROM_NAME", "SurveyFieldwork Panel")

_service = None


def _gmail():
    global _service
    if _service is None:
        from app.services.gmail_workspace_service import GmailWorkspaceService
        svc = GmailWorkspaceService(mongo_uri=os.getenv("MONGO_URI") or "mongodb://localhost:27017/", db_name="torpedo_gmail")
        if not svc.load_service_account():
            raise RuntimeError("Gmail service account is not configured in Torpedo")
        _service = svc._get_service(PANEL_GMAIL_SENDER)
    return _service


def from_header() -> str:
    return f"{PANEL_GMAIL_FROM_NAME} <{PANEL_GMAIL_SENDER}>"


def send_message(msg: Message) -> Tuple[bool, Dict[str, Any]]:
    """Send a fully built MIME message (To/Subject set) from the panel mailbox."""
    try:
        if msg.get("From"):
            msg.replace_header("From", from_header())
        else:
            msg["From"] = from_header()
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        sent = _gmail().users().messages().send(userId="me", body={"raw": raw}).execute()
        return True, {"gmail_message_id": sent.get("id", "")}
    except Exception as e:
        logger.error(f"[panel-gmail] send to {msg.get('To')} failed: {e}")
        return False, {"error": str(e)[:300]}
