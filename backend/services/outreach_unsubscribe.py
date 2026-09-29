"""
Cold-outreach opt-out: signed links, and the footer that carries them.

Cold outreach had no unsubscribe path at all. `messaging.facade` refuses every
bulk send unless OUTREACH_SENDER_POSTAL_ADDRESS and OUTREACH_UNSUBSCRIBE_URL are
set, but nothing in the v2 send path ever put either one *into* a message — so
setting those two variables would have satisfied the gate and still shipped mail
with no postal address and no way out. That is the failure this module closes.

Two things are needed for an opt-out to stick:
  1. the link must reach an endpoint that writes to the list every sender
     actually consults — here `messaging.suppression`, the canonical
     `email_automation.suppression_list`, NOT `panel_email_suppression`, which
     is the panel's own list and is read by nothing on this path, and
  2. the address must be identifiable from the link alone, because someone
     clicking "unsubscribe" in their mail client is not logged in.

Tokens are HMAC-signed rather than stored, so an opt-out costs no database
lookup and no per-send row: `<b64url(email)>.<hmac>`. Modelled on
services/panel_unsubscribe, deliberately, including its fail-OPEN stance: if
the secret is missing or a signature does not verify, the opt-out is still
honoured and a warning logged. Wrongly honouring a forged opt-out costs one
address; wrongly rejecting a real one is a compliance failure and another spam
complaint.
"""

import base64
import hashlib
import hmac
import html as _html
import logging
import os
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Where the recipient-facing endpoints live. Falls back to the tracking base
# URL, which the same emails already point at, so a deployment that can serve
# the open pixel can serve an opt-out without a second variable.
_UNSUB_PATH = "/api/cold-outreach/unsubscribe"


def _base_from_unsubscribe_url() -> str:
    """OUTREACH_UNSUBSCRIBE_URL (the setting messaging.facade checks) is the
    endpoint itself; its origin is a valid base for the signed links."""
    url = os.getenv("OUTREACH_UNSUBSCRIBE_URL", "").strip().rstrip("/")
    return url[: -len(_UNSUB_PATH)] if url.endswith(_UNSUB_PATH) else ""


PUBLIC_BASE_URL = (
    os.getenv("OUTREACH_PUBLIC_BASE_URL")
    or os.getenv("TRACKING_BASE_URL")
    or _base_from_unsubscribe_url()
    or ""
).rstrip("/")

_SECRET = (
    os.getenv("OUTREACH_UNSUBSCRIBE_SECRET")
    or os.getenv("PANEL_UNSUBSCRIBE_SECRET")
    or os.getenv("REDIRECT_TOKEN_SECRET")
    or ""
).strip()

# The sender's physical postal address. Optional by owner decision
# (2026-09-28): printed when set, omitted when not, never a placeholder.
# CAN-SPAM §7704(a)(5) expects one in commercial mail to US recipients -- see
# messaging/facade.py and RUNBOOK.md; that exposure is the owner's call.
SENDER_POSTAL_ADDRESS = os.getenv("OUTREACH_SENDER_POSTAL_ADDRESS", "").strip()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(email: str) -> str:
    """Signed, self-describing opt-out token for one address."""
    normalized = (email or "").strip().lower()
    payload = _b64e(normalized.encode("utf-8"))
    if not _SECRET:
        return payload
    signature = hmac.new(
        _SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()[:32]
    return f"{payload}.{signature}"


def read_token(token: str) -> Optional[str]:
    """Recover the address from a token. None only if genuinely unreadable.

    A bad signature is logged and the address is still returned — see the
    fail-open note at the top of this module.
    """
    if not token:
        return None
    payload, _, signature = token.partition(".")
    try:
        email = _b64d(payload).decode("utf-8").strip().lower()
    except Exception:
        logger.warning("[outreach-unsub] unreadable token")
        return None
    if not email or "@" not in email:
        return None

    if _SECRET:
        expected = hmac.new(
            _SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
        ).hexdigest()[:32]
        if not hmac.compare_digest(expected, signature or ""):
            logger.warning(
                "[outreach-unsub] signature mismatch for %s — honouring anyway", email)
    return email


def unsubscribe_url(email: str) -> str:
    """The human-facing opt-out link for one recipient."""
    return f"{PUBLIC_BASE_URL}/api/cold-outreach/unsubscribe/{quote(make_token(email))}"


def one_click_url(email: str) -> str:
    """RFC 8058 one-click POST target for List-Unsubscribe-Post."""
    return (f"{PUBLIC_BASE_URL}/api/cold-outreach/unsubscribe/"
            f"{quote(make_token(email))}/one-click")


def show_optout_link() -> bool:
    """The visible unsubscribe footer is off by default (owner, 2026-09-29:
    "these are all known people and I don't want them to see it"). Opt-outs
    still work: a reply asking to be removed suppresses the address
    (record_optout, called from reply triage). Set
    OUTREACH_SHOW_UNSUBSCRIBE_LINK=true to show the link again. Note: US
    CAN-SPAM and Gmail's bulk-sender rules expect a visible opt-out in
    commercial mail -- the owner's call, see RUNBOOK.md."""
    return os.getenv("OUTREACH_SHOW_UNSUBSCRIBE_LINK", "false").strip().lower() == "true"


def record_optout(email: str, source: str) -> bool:
    """Suppress an address everywhere and close its outreach rows -- from the
    link, the one-click POST, or a reply asking to be removed."""
    try:
        from messaging import suppression as _suppression
    except ImportError:  # pragma: no cover - packaging fallback
        from backend.messaging import suppression as _suppression
    normalized = _suppression.normalize(email)
    if not normalized:
        return False
    _suppression.suppress(normalized, reason="unsubscribed", source=source)
    try:
        from datetime import datetime
        from pymongo import MongoClient
        db = MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/",
                         serverSelectionTimeoutMS=5000)[os.getenv("MONGO_DB_NAME", "torpedo")]
        now = datetime.utcnow()
        db["outreach_leads_v2"].update_many({"email": normalized}, {"$set": {
            "unsubscribed": True, "unsubscribed_at": now, "sendable": False,
            "workflow_status": "suppressed", "updated_at": now}})
    except Exception as exc:  # the suppression write is the one that stops mail
        logger.error("[outreach-unsub] lead rows not updated for %s: %s", normalized, exc)
    return True


def compliance_footer(email: str, business_label: str = "") -> str:
    """
    The HTML footer appended to every cold-outreach message.

    Returns "" when it cannot be built honestly -- no reachable base URL for
    the opt-out link. Callers treat an empty footer as a hard refusal to send
    rather than sending without one; a message that claims an opt-out it cannot
    honour is worse than one that never left. The postal line is included only
    when an address is configured.
    """
    if not PUBLIC_BASE_URL or not show_optout_link():
        return ""
    who = _html.escape(business_label) if business_label else "us"
    address = f'<br>{_html.escape(SENDER_POSTAL_ADDRESS)}' if SENDER_POSTAL_ADDRESS else ""
    return (
        '<div style="margin-top:28px;padding-top:12px;border-top:1px solid #e2e2e2;'
        'font-size:12px;line-height:1.5;color:#767676;font-family:Arial,sans-serif">'
        f'You received this because we believe {who} may be relevant to your work. '
        f'<a href="{_html.escape(unsubscribe_url(email))}" '
        'style="color:#767676;text-decoration:underline">Unsubscribe</a>'
        ' and we will not contact you again.'
        f'{address}'
        '</div>'
    )


def footer_blocker() -> Optional[str]:
    """Why a compliant footer cannot be built, or None if it can (or if the
    visible link is switched off -- then there is nothing to build)."""
    if not show_optout_link():
        return None
    if not PUBLIC_BASE_URL:
        return ("neither OUTREACH_PUBLIC_BASE_URL nor TRACKING_BASE_URL is set "
                "— cannot build a reachable unsubscribe link")
    return None
