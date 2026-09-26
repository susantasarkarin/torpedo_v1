"""
Deterministic pre-filter for the mail-pool RFQ pipeline (no AI, no I/O).

Why this exists: the 2026-09-19/20 real-data benchmark of the local 1.5B model
showed it fabricates a plausible RFQ (invented budget, dates, "evidence") for
mail that plainly isn't one -- bounces, calendar invites, password resets --
because a small model shown a filled-in template tends to fill it in. Those
emails should never reach a model at all.

Rules are built from general email conventions (RFC 3464 DSN senders, calendar
invite subject prefixes, no-reply local parts, well-known bulk-mail platforms),
not from any specific message. Every rule is deliberately conservative: a false
skip silently drops a real RFQ, which is far worse than sending one extra junk
email to the classifier. Measure with the RFQ false-negative check in
tests/test_mail_prefilter.py and scripts/ before adding rules.

Deliberately NOT a rule: "skip known vendor domains". In this business the same
company is both a supplier and a client (Bilendi, Ipsos, Hansa all send RFQs
and also sell us panel), so a domain-level vendor skip would drop real RFQs.
MAIL_PREFILTER_SKIP_DOMAINS exists for domains that are provably pure vendors
or pure noise, and is empty by default.
"""

import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

_DSN_LOCAL_PARTS = frozenset({"mailer-daemon", "postmaster", "mail-daemon"})

_AUTOMATED_LOCAL_PART = re.compile(
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|donotreply|notifications?|notify|"
    r"alerts?|bounces?|auto[-_.]?reply|autoresponder|newsletters?|digest|"
    r"statements?|jobs?[-_.]?(listings?|alerts?))([-_.+].*)?$",
    re.IGNORECASE,
)

_BOUNCE_SUBJECT = re.compile(
    r"delivery status notification|undelivered mail|returned mail|"
    r"mail delivery (failed|subsystem)|delivery (has )?failed|undeliverable",
    re.IGNORECASE,
)

_AUTO_REPLY_SUBJECT = re.compile(
    r"^\s*(\[[^\]]*\]\s*)*(auto(matic)?[ -]?reply|automatische antwort|"
    r"automatisch antwoord|respuesta autom[aá]tica|risposta automatica|"
    r"resposta autom[aá]tica|out of office|auto:|abwesenheit|r[eé]ponse automatique)",
    re.IGNORECASE,
)

_CALENDAR_SUBJECT = re.compile(
    r"^\s*(\[[^\]]*\]\s*)*((updated )?invitation( from google calendar)?|"
    r"accepted|declined|tentatively accepted|canceled event|cancelled event)\s*:",
    re.IGNORECASE,
)
_CALENDAR_BODY_PHRASE = "you have been invited to the following event"

_TRANSACTIONAL_SUBJECT = re.compile(
    r"\b(reset|change[d]?|update[d]?|forgot)\b.{0,25}\bpassword\b|"
    r"\bpassword\b.{0,25}\b(reset|changed|updated)\b|"
    r"\bverify your (e-?mail|account|identity)\b|\bverification code\b|"
    r"\bone[- ]time (password|passcode|code)\b|\b(security|sign-?in) alert\b|"
    r"\b(invoice|receipt|statement)\b.{0,40}\b(available|summary|is ready)\b|"
    r"\byour (payment|subscription|order|plan)\b.{0,40}"
    r"\b(renewed|received|confirmed|processed|successful|failed)\b|"
    r"\bsubscription (is )?renewed\b|\brenewal payment\b|"
    r"\byou'?ve sent a payment\b|\bpayment (confirmation|received|processed|reminder)\b|"
    r"\b(invoice|bill)s?\b.{0,30}\b(due|overdue|reminder)\b",
    re.IGNORECASE,
)

_BULK_PLATFORM_DOMAINS = frozenset({
    "substack.com", "beehiiv.com", "mailchimp.com", "mcsv.net",
    "list-manage.com", "sendgrid.net", "mailerlite.com", "constantcontact.com",
    "campaign-archive.com", "hubspotemail.net", "mktomail.com",
})
_BULK_BODY_PHRASE = "view this post on the web"

_FORWARD_SUBJECT = re.compile(r"^\s*(\[[^\]]*\]\s*)*(fw|fwd)\s*:", re.IGNORECASE)


def _csv_env(name: str, default: str = "") -> frozenset:
    raw = os.getenv(name, default)
    return frozenset(p.strip().lower() for p in raw.split(",") if p.strip())


def own_domains() -> frozenset:
    return _csv_env("INTERNAL_DOMAINS",
                     "cogentixresearch.com,surveyfieldwork.com,bimwavesolutions.com")


def _split_address(from_email: Optional[str]) -> Tuple[str, str]:
    addr = (from_email or "").strip().lower()
    if "<" in addr and ">" in addr:
        addr = addr[addr.rfind("<") + 1:addr.rfind(">")]
    local, _, domain = addr.partition("@")
    return local, domain


def _domain_matches(domain: str, candidates: Iterable[str]) -> bool:
    return any(domain == c or domain.endswith("." + c) for c in candidates)


def _head(doc: Mapping[str, Any], n: int = 400) -> str:
    return str(doc.get("body_plain") or doc.get("body") or doc.get("snippet") or "")[:n]


def skip_reason(doc: Mapping[str, Any]) -> Optional[str]:
    """Return why this email should never reach the RFQ model, or None to keep
    it. First matching rule wins; order goes from most to least certain."""
    subject = str(doc.get("subject") or "")
    local, domain = _split_address(doc.get("from_email"))

    if str(doc.get("direction") or "").lower() == "outbound":
        return "own_outbound"
    if local in _DSN_LOCAL_PARTS:
        return "bounce_sender"
    if _BOUNCE_SUBJECT.search(subject):
        return "bounce_subject"
    if _AUTO_REPLY_SUBJECT.search(subject):
        return "auto_reply"
    if _CALENDAR_SUBJECT.search(subject) or _CALENDAR_BODY_PHRASE in _head(doc).lower():
        return "calendar_invite"
    if _AUTOMATED_LOCAL_PART.match(local):
        return "automated_sender"
    if _TRANSACTIONAL_SUBJECT.search(subject):
        return "transactional"
    if _domain_matches(domain, _BULK_PLATFORM_DOMAINS) or _BULK_BODY_PHRASE in _head(doc, 300).lower():
        return "bulk_newsletter"
    if domain and _domain_matches(domain, _csv_env("MAIL_PREFILTER_SKIP_DOMAINS")):
        return "configured_skip_domain"
    # Our own staff. A forward (Fw:/Fwd:) is kept: colleagues do forward real
    # client RFQs, and the classifier decides what's inside.
    if domain and _domain_matches(domain, own_domains()) and not _FORWARD_SUBJECT.search(subject):
        return "internal_sender"
    return None


def partition(docs: Iterable[Mapping[str, Any]]) -> Tuple[List[Any], Dict[str, int]]:
    """Split docs into (kept, {reason: count}) -- the counts are for logging."""
    kept: List[Any] = []
    skipped: Dict[str, int] = {}
    for d in docs:
        reason = skip_reason(d)
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
        else:
            kept.append(d)
    return kept, skipped
