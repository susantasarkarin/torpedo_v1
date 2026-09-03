"""
The send facade — the one door every outbound email goes through.

WHY
---
Thirteen modules could put mail on the wire: outreach_mailer, the
outreach_engine sending engine, campaigns/send_queue, cold_outreach_router,
three panel senders, three Gmail services, email_campaigns, campaign_service
and tasks/outreach_tasks. Each had its own idea (or none) of suppression,
caps, and logging. Caps lived in exactly one of them and counted exactly one
collection. Suppression was split across three lists in three databases, so
unsubscribing from one channel left you subscribed to the other two.

Nothing saw total volume. That is the August over-send incident (TOR-06).

WHAT THIS GUARANTEES
--------------------
Every call to `send()`:

  1. is checked against ONE suppression list, which fails CLOSED
  2. is counted against a per-identity budget that spans all channels
  3. is written to ONE send log, whatever the transport
  4. is refused if the pre-flight compliance fields are missing

The order matters. Suppression is checked before budget, so a suppressed
address never consumes quota. Both are checked before the transport, so a
blocked send costs nothing and cannot half-happen.

WHAT IT DOES NOT DO
-------------------
It does not compose messages, template them, schedule them, or decide who to
contact. Those stay with the callers, which know their own domain. This is the
chokepoint, not a framework.

KILL SWITCH
-----------
`SENDING_ENABLED=false` stops every outbound email process-wide, immediately,
without a deploy. It is checked on every call, not captured at import.
"""

import logging
import os
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable, Dict, Optional

from . import budget as _budget
from . import log as _log
from . import suppression as _suppression

logger = logging.getLogger(__name__)


class SendBlocked(Exception):
    """A send was refused before it reached a provider. Carries the reason."""

    def __init__(self, reason: str, category: str):
        self.reason, self.category = reason, category
        super().__init__(reason)


@dataclass
class SendResult:
    delivered: bool
    reason: Optional[str] = None
    category: Optional[str] = None      # suppressed | budget | disabled | transport | compliance
    provider_message_id: Optional[str] = None
    log_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.delivered


def _is_unsendable_domain(addr: str) -> bool:
    """Delegates to the one blocklist, defined next to the generator."""
    try:
        from leads.bounce_recovery import is_unsendable_domain
    except ImportError:  # pragma: no cover
        from backend.leads.bounce_recovery import is_unsendable_domain
    return is_unsendable_domain(addr)


def sending_enabled() -> bool:
    """Read at call time: the kill switch must work without a restart."""
    return os.getenv("SENDING_ENABLED", "true").strip().lower() not in (
        "0", "false", "no", "off")


def _compliance_problem(transactional: bool) -> Optional[str]:
    """
    Bulk mail is illegal without a postal address and an unsubscribe path
    (CAN-SPAM). outreach_mailer already refused to send without these; the rule
    belongs here so it covers every channel rather than one of thirteen.

    Transactional mail is exempt — a password reset needs no unsubscribe link.
    """
    if transactional:
        return None
    if not os.getenv("OUTREACH_SENDER_POSTAL_ADDRESS", "").strip():
        return "OUTREACH_SENDER_POSTAL_ADDRESS is not set (legally required for bulk mail)"
    if not os.getenv("OUTREACH_UNSUBSCRIBE_URL", "").strip():
        return "OUTREACH_UNSUBSCRIBE_URL is not set (unsubscribe path required for bulk mail)"
    return None



def gate(addr: str, *, identity: str, channel: str,
         transactional: bool = False, skip_suppression: bool = False,
         raw: Optional[str] = None):
    """
    Run every pre-send check and return (reason, category) if the send must be
    refused, or None if it may proceed.

    Split out of `send()` so that senders which cannot use this module's
    transport can still get its guarantees. The v2 cold-outreach engine is the
    case that forced this: it does its own SMTP/SES delivery, threading and
    tracking, and so had NONE of the kill switch, the unified suppression list,
    the unsendable-domain blocklist, or the cross-channel budget — it consulted
    one of the three bounce lists and nothing else. That is the send path that
    over-sent in August. It now calls this before every message.

    `addr` must already be normalised. Order matters and matches `send()`:
    suppression before budget, so a suppressed address never consumes quota.
    """
    if not addr or "@" not in addr:
        return (f"invalid recipient address: {(raw if raw is not None else addr)!r}",
                "compliance")

    # Domains that can never be a real corporate mailbox (TOR-06 follow-up).
    # The recorded bounces contain 119 sends to @domain.com and 26 to
    # @company.com — the email-pattern TEMPLATE's own placeholder text, never
    # substituted — plus 76 to @linkedin.com, where the domain had been taken
    # from the lead's profile URL instead of their employer. Every one of those
    # was a guaranteed bounce generated by us.
    if _is_unsendable_domain(addr):
        return (f"unsendable domain: {addr.rsplit('@', 1)[-1]} — placeholder, "
                f"social or free-webmail address, never a corporate mailbox",
                "compliance")

    if not sending_enabled():
        return ("SENDING_ENABLED=false (kill switch active)", "disabled")

    problem = _compliance_problem(transactional)
    if problem:
        return (problem, "compliance")

    # 1. Suppression, before budget — a suppressed address must not burn quota.
    if skip_suppression:
        logger.warning("suppression SKIPPED for %s on channel=%s — this must "
                       "only happen for unskippable mail", addr, channel)
    elif _suppression.is_suppressed(addr):
        reason = _suppression.reason_for(addr) or "unknown"
        return (f"suppressed ({reason})", "suppressed")

    # 2. Budget, across every channel using this identity.
    blocked = _budget.allows(identity, transactional=transactional)
    if blocked:
        return (blocked, "budget")

    return None


def send(
    *,
    to_email: str,
    subject: str,
    transport: Callable[..., str],
    identity: str,
    channel: str,
    transactional: bool = False,
    body_text: Optional[str] = None,
    body_html: Optional[str] = None,
    message: Optional[MIMEMultipart] = None,
    metadata: Optional[Dict[str, Any]] = None,
    skip_suppression: bool = False,
) -> SendResult:
    """
    Send one email through the shared gates.

    transport   callable that actually delivers and returns a provider message
                id. Receives the built MIMEMultipart as its only positional
                argument. Keeping it a callable means this module needs no
                knowledge of SES, SMTP or the Gmail API — and callers keep
                their existing, working transports.
    identity    the sending mailbox/identity. THIS is what carries the budget
                and the reputation, so it must be the real From address, not a
                campaign name.
    channel     what kind of mail this is, for the log: outreach, panel_invite,
                campaign, transactional, ...
    transactional
                True for mail a human is waiting on. Exempt from the bulk
                compliance checks and allowed to draw on the reserved quota.
    skip_suppression
                ONLY for genuinely unskippable mail — an unsubscribe
                confirmation, a legal notice. Never for marketing. Logged
                loudly when used.

    Returns a SendResult; never raises for an ordinary block. Transport
    exceptions are caught, logged and returned as a failed result, because a
    caller looping over recipients must not abort the batch on one bad address.
    """
    addr = _suppression.normalize(to_email)
    meta = dict(metadata or {})

    def _blocked(reason: str, category: str) -> SendResult:
        log_id = _log.record(identity=identity, to_email=addr, subject=subject,
                             channel=channel,
                             status={"suppressed": "suppressed",
                                     "budget": "budget_blocked"}.get(category, "failed"),
                             error=reason, transactional=transactional,
                             metadata=meta)
        logger.info("send blocked (%s) to=%s channel=%s: %s",
                    category, addr, channel, reason)
        return SendResult(delivered=False, reason=reason, category=category,
                          log_id=log_id, metadata=meta)

    blocked_reason = gate(addr, identity=identity, transactional=transactional,
                          skip_suppression=skip_suppression, channel=channel,
                          raw=to_email)
    if blocked_reason:
        return _blocked(*blocked_reason)

    # 3. Deliver.
    msg = message if message is not None else _build_message(
        to_email=addr, subject=subject, identity=identity,
        body_text=body_text, body_html=body_html)

    try:
        provider_id = transport(msg)
    except Exception as exc:
        log_id = _log.record(identity=identity, to_email=addr, subject=subject,
                             channel=channel, status="failed", error=str(exc),
                             transactional=transactional, metadata=meta)
        logger.exception("transport failed for %s on channel=%s", addr, channel)
        return SendResult(delivered=False, reason=str(exc), category="transport",
                          log_id=log_id, metadata=meta)

    log_id = _log.record(identity=identity, to_email=addr, subject=subject,
                         channel=channel, status="sent",
                         provider_message_id=provider_id,
                         transactional=transactional, metadata=meta)
    return SendResult(delivered=True, provider_message_id=provider_id,
                      log_id=log_id, metadata=meta)


def _build_message(*, to_email: str, subject: str, identity: str,
                   body_text: Optional[str],
                   body_html: Optional[str]) -> MIMEMultipart:
    """
    Minimal multipart/alternative. Callers with their own message construction
    (headers, List-Unsubscribe, attachments) should pass `message=` instead and
    keep it — this is only for the simple cases.
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = identity
    msg["To"] = to_email
    if body_text:
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))
    if not body_text and not body_html:
        raise ValueError("send() needs body_text, body_html, or a prebuilt message")
    return msg


# ---------------------------------------------------------------------------
# Ops surface
# ---------------------------------------------------------------------------
def status(identity: Optional[str] = None) -> Dict[str, Any]:
    """Everything an operator needs to answer 'why is nothing sending'."""
    out: Dict[str, Any] = {
        "sending_enabled": sending_enabled(),
        "suppression": _suppression.stats(),
    }
    if identity:
        out["budget"] = _budget.usage(identity)
        out["recent"] = _log.recent(limit=20, identity=identity)
    return out
