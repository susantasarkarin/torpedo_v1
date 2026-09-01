"""
Panel unsubscribe — signed opt-out links and the one-click (RFC 8058) flow.

Why this exists: every invitation footer used to link to
panel.surveyfieldwork.com/unsubscribe, an entirely different application.
Torpedo's own opt-out endpoint was never reachable from any email we sent, and
nothing read SFW's answer back, so after 1.29M invitations the Torpedo side had
recorded exactly zero unsubscribes. People who asked to be left alone kept
receiving an invite every other day.

Two things are needed for an opt-out to actually stick:
  1. the link must point at an endpoint that writes to `panel_email_suppression`
     — the one list every sender consults, and
  2. the address must be identifiable from the link alone, because someone
     clicking "unsubscribe" in their mail client is not logged in.

Tokens are HMAC-signed rather than stored, so an opt-out costs no database
lookup and no per-send row: `<b64url(email)>.<hmac>`.

Design note — this deliberately fails OPEN. If the signing secret is missing or
a signature doesn't verify, the request is still honoured and a warning is
logged. Wrongly honouring a forged opt-out costs us one address; wrongly
rejecting a real one is a compliance failure and another spam complaint.
"""

import base64
import hashlib
import hmac
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import quote

from services.panel_bounce_handler import panelists_collection, suppression_collection, invitation_log_collection

logger = logging.getLogger(__name__)

PANEL_PUBLIC_BASE_URL = os.getenv(
    "PANEL_PUBLIC_BASE_URL", "https://torpedo.cogentixresearch.com"
).rstrip("/")

# Falls back to PANEL_CONFIRM_SECRET so a deployment that already has one
# working shared secret doesn't need a second before opt-out links work.
_SECRET = (
    os.getenv("PANEL_UNSUBSCRIBE_SECRET")
    or os.getenv("PANEL_CONFIRM_SECRET")
    or ""
).strip()

# Human-facing page (SPA route) and the RFC 8058 one-click POST target.
UNSUBSCRIBE_PAGE_URL = f"{PANEL_PUBLIC_BASE_URL}/panel/unsubscribe"
ONE_CLICK_URL = f"{PANEL_PUBLIC_BASE_URL}/api/panel/unsubscribe/one-click"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def make_token(email: str) -> str:
    """Signed, self-describing opt-out token for one address."""
    normalized = (email or "").strip().lower()
    payload = _b64e(normalized.encode("utf-8"))
    if not _SECRET:
        return payload
    signature = hmac.new(_SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{signature}"


def read_token(token: str) -> Optional[str]:
    """Recover the address from a token. Returns None only if unreadable.

    A bad signature is logged and the address is still returned — see the
    fail-open note at the top of this module.
    """
    raw = (token or "").strip()
    if not raw:
        return None

    payload, _, signature = raw.partition(".")
    try:
        email = _b64d(payload).decode("utf-8").strip().lower()
    except Exception:
        logger.warning("[panel-unsub] token payload could not be decoded")
        return None

    if "@" not in email:
        return None

    if _SECRET:
        expected = hmac.new(_SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(expected, signature or ""):
            logger.warning(f"[panel-unsub] signature mismatch for {email[:3]}*** — honouring anyway")
    else:
        logger.error(
            "[panel-unsub] no PANEL_UNSUBSCRIBE_SECRET/PANEL_CONFIRM_SECRET set; "
            "opt-out links are unsigned"
        )

    return email


def unsubscribe_url(email: str) -> str:
    """Human-facing opt-out link for an email footer."""
    return f"{UNSUBSCRIBE_PAGE_URL}?token={quote(make_token(email))}"


def one_click_url(email: str) -> str:
    """RFC 8058 List-Unsubscribe-Post target."""
    return f"{ONE_CLICK_URL}?token={quote(make_token(email))}"


def list_unsubscribe_headers(email: str) -> Dict[str, str]:
    """Headers that let Gmail/Yahoo render a native unsubscribe control.

    Both mailbox providers have required these of anyone sending more than
    5,000 messages a day since February 2024. We send ~161,000 a day and were
    sending none of them, which on its own is enough to get bulk mail filtered
    regardless of content.
    """
    return {
        "List-Unsubscribe": f"<{one_click_url(email)}>, <{UNSUBSCRIBE_PAGE_URL}?token={quote(make_token(email))}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def unsubscribe_email(
    email: str,
    source: str = "email_link",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record an opt-out everywhere a sender might look. Idempotent.

    Writes to `panel_email_suppression` (checked by every bulk sender) AND
    flags the panelist, because the signup sender filters on `status: active`
    while the suppression list is what the others consult.
    """
    normalized = (email or "").strip().lower()
    if not normalized or "@" not in normalized:
        return {"unsubscribed": False, "reason": "invalid_email"}

    now = datetime.utcnow()

    suppression_collection.update_one(
        {"email": normalized},
        {
            "$set": {
                "email": normalized,
                "reason": "unsubscribe",
                "source": source,
                "metadata": metadata or {},
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )

    result = panelists_collection.update_one(
        {"email": normalized},
        {"$set": {
            "status": "dnd",
            "dnd": True,
            "unsubscribed": True,
            "unsubscribed_at": now,
            "updated_at": now,
        }},
    )

    invitation_log_collection.update_many(
        {"email": normalized, "status": "sent"},
        {"$set": {"status": "unsubscribed", "unsubscribed_at": now}},
    )

    logger.info(f"[panel-unsub] opted out {normalized[:3]}*** via {source}")
    return {
        "unsubscribed": True,
        "email": normalized,
        "panelist_matched": result.matched_count > 0,
    }
