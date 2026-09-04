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
PUBLIC_BASE_URL = (
    os.getenv("OUTREACH_PUBLIC_BASE_URL")
    or os.getenv("TRACKING_BASE_URL")
    or ""
).rstrip("/")

_SECRET = (
    os.getenv("OUTREACH_UNSUBSCRIBE_SECRET")
    or os.getenv("PANEL_UNSUBSCRIBE_SECRET")
    or os.getenv("REDIRECT_TOKEN_SECRET")
    or ""
).strip()

# The physical postal address of the sender, required in every commercial
# message by CAN-SPAM §7704(a)(5) and by the equivalent rules elsewhere. There
# is deliberately no default: a made-up address is worse than no send.
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


def compliance_footer(email: str, business_label: str = "") -> str:
    """
    The HTML footer appended to every cold-outreach message.

    Returns "" when it cannot be built honestly — no base URL, or no configured
    postal address. Callers treat an empty footer as a hard refusal to send
    rather than sending without one; a message that claims an opt-out it cannot
    honour is worse than one that never left.
    """
    if not PUBLIC_BASE_URL or not SENDER_POSTAL_ADDRESS:
        return ""
    who = _html.escape(business_label) if business_label else "us"
    return (
        '<div style="margin-top:28px;padding-top:12px;border-top:1px solid #e2e2e2;'
        'font-size:12px;line-height:1.5;color:#767676;font-family:Arial,sans-serif">'
        f'You received this because we believe {who} may be relevant to your work. '
        f'<a href="{_html.escape(unsubscribe_url(email))}" '
        'style="color:#767676;text-decoration:underline">Unsubscribe</a>'
        ' and we will not contact you again.<br>'
        f'{_html.escape(SENDER_POSTAL_ADDRESS)}'
        '</div>'
    )


def footer_blocker() -> Optional[str]:
    """Why a compliant footer cannot be built, or None if it can."""
    if not SENDER_POSTAL_ADDRESS:
        return ("OUTREACH_SENDER_POSTAL_ADDRESS is not set — cannot build the "
                "postal-address line every commercial message must carry")
    if not PUBLIC_BASE_URL:
        return ("neither OUTREACH_PUBLIC_BASE_URL nor TRACKING_BASE_URL is set "
                "— cannot build a reachable unsubscribe link")
    return None
