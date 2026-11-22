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
import socket
import ssl
import time
from email.utils import make_msgid
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
        svc = GmailWorkspaceService(db_name="torpedo_gmail")
        if not svc.load_service_account():
            raise RuntimeError("Gmail service account is not configured in Torpedo")
        _service = svc._get_service(PANEL_GMAIL_SENDER)
    return _service


def from_header() -> str:
    return f"{PANEL_GMAIL_FROM_NAME} <{PANEL_GMAIL_SENDER}>"


# Bounded retry for transient transport failures. Sending twice is worse than
# failing once, so a retry only happens when the message provably was not sent:
#   * SSL handshake errors (WRONG_VERSION_NUMBER), refused/reset-before-send and
#     DNS errors: the request never went out.
#   * HTTP 429 / 5xx from the Gmail API: a response came back saying it failed.
#   * A read timeout is ambiguous (the request may have been delivered and only
#     the reply lost). We ask Gmail whether a message with our Message-ID is in
#     SENT: found -> report success. Not found (or the lookup fails) -> report a
#     failure and do NOT resend: Gmail may rewrite the Message-ID, so "not found"
#     doesn't prove it wasn't delivered, and a missed invite beats a duplicate
#     (owner decision, 2026-11-22). The next scheduled run can pick it up.
# 4xx (other than 429) and anything else are never retried. Each retry rebuilds
# the Gmail client so it uses a fresh HTTP connection.
RETRY_BACKOFF_SECONDS = (2, 5)
_sleep = time.sleep


def _reset_service():
    global _service
    _service = None


def _classify(exc: Exception) -> str:
    """'retry' (never sent), 'check' (maybe sent), or 'fail'."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status is not None:
        try:
            status = int(status)
        except (TypeError, ValueError):
            status = None
    if status is not None:
        return "retry" if status == 429 or 500 <= status < 600 else "fail"
    if isinstance(exc, (ssl.SSLError, ConnectionRefusedError, socket.gaierror)):
        if isinstance(exc, ssl.SSLError) and "timed out" in str(exc).lower():
            return "check"
        return "retry"
    if isinstance(exc, (socket.timeout, TimeoutError, ConnectionResetError, ConnectionAbortedError,
                        BrokenPipeError)):
        return "check"
    return "fail"


def _already_sent(message_id: str) -> bool:
    res = _gmail().users().messages().list(
        userId="me", q=f"rfc822msgid:{message_id.strip('<>')}", maxResults=1).execute()
    return bool(res.get("messages"))


def send_message(msg: Message) -> Tuple[bool, Dict[str, Any]]:
    """Send a fully built MIME message (To/Subject set) from the panel mailbox."""
    try:
        if msg.get("From"):
            msg.replace_header("From", from_header())
        else:
            msg["From"] = from_header()
        if not msg.get("Message-ID"):
            msg["Message-ID"] = make_msgid(domain=PANEL_GMAIL_SENDER.split("@")[-1])
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    except Exception as e:
        logger.error(f"[panel-gmail] send to {msg.get('To')} failed: {e}")
        return False, {"error": str(e)[:300]}

    attempt = 0
    while True:
        try:
            sent = _gmail().users().messages().send(userId="me", body={"raw": raw}).execute()
            return True, {"gmail_message_id": sent.get("id", ""), **({"retries": attempt} if attempt else {})}
        except Exception as e:
            kind = _classify(e)
            if kind == "fail" or attempt >= len(RETRY_BACKOFF_SECONDS):
                logger.error(f"[panel-gmail] send to {msg.get('To')} failed: {e}")
                return False, {"error": str(e)[:300]}
            if kind == "check":
                try:
                    if _already_sent(str(msg["Message-ID"])):
                        logger.warning(f"[panel-gmail] send to {msg.get('To')} timed out but was delivered")
                        return True, {"gmail_message_id": "", "retries": attempt}
                except Exception as ce:
                    logger.error(f"[panel-gmail] send to {msg.get('To')} failed, unsent-check failed too: {e} / {ce}")
                    return False, {"error": str(e)[:300]}
                # Not found in SENT: may still have been delivered, so never resend.
                logger.error(f"[panel-gmail] send to {msg.get('To')} timed out; not resent (may have been delivered): {e}")
                return False, {"error": str(e)[:300]}
            logger.warning(f"[panel-gmail] transient error to {msg.get('To')}: {e}; retry {attempt + 1}")
            _sleep(RETRY_BACKOFF_SECONDS[attempt])
            attempt += 1
            _reset_service()
