"""
Non-human email addresses that must never become leads.

Reply-sourced lead promotion works by finding gmail threads that have both an
outbound and an inbound message and harvesting the inbound sender. A bounce
lands in the thread we created — we mail `lead@company.com`, the MTA replies
from `postmaster@company.com` — so the thread looks two-way and the bounce
notifier gets promoted to a lead, classified against an ICP, and then mailed.
Which bounces. That is how `Postmaster / Precisionopinion` and
`MAILER-DAEMON / Mailerdaemon` ended up in the Leads table with a BOUNCED email
status.

This module is the single definition of "not a person" so the rule cannot drift
between the places that need it. Matching is on the address, never the display
name: `MAILER-DAEMON` and `Mail Delivery Subsystem` are attacker-free but also
entirely unreliable — locales, ESPs and clients all render them differently,
whereas the local part is mechanical.

Two categories, deliberately separate:

  SYSTEM  — automated infrastructure. Nobody reads mail sent here. Never a
            lead, never mailable, no exceptions.
  ROLE    — a shared human mailbox (info@, sales@, support@). Real people may
            read it, but it is not a *person*: it has no name, seniority or
            buying role, so promoting it produces a junk lead like
            `BILL <account-services@…>`. Excluded from lead promotion by
            default, but callers that genuinely want role mailboxes can opt in.
"""

import re
from typing import Optional

# Exact local parts. Anything here is infrastructure.
SYSTEM_LOCALPARTS = frozenset({
    "postmaster", "mailer-daemon", "mailerdaemon", "mail-daemon", "maildaemon",
    "daemon", "mailer", "smtp", "abuse", "spam",
    "noreply", "no-reply", "no_reply", "nreply",
    "donotreply", "do-not-reply", "do_not_reply", "dontreply",
    "notification", "notifications", "notify",
    "alert", "alerts", "alerting",
    "bounce", "bounces", "bounced", "bounce-daemon",
    "return", "returns", "return-path", "returnpath",
    "delivery", "delivery-status", "deliverystatus", "mail-delivery",
    "autoreply", "auto-reply", "auto_reply", "automailer", "autoresponder",
    "listserv", "majordomo", "mailman", "bounce-handler",
    "undisclosed-recipients", "nobody", "devnull", "null",
})

# Local-part prefixes. Catches the numbered and suffixed variants ESPs emit —
# noreply2@, bounce-12345@, notification-team@, mailer-daemon-2@.
SYSTEM_PREFIXES = (
    "postmaster", "mailer-daemon", "mailerdaemon", "mail-daemon",
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
    "bounce", "bounces", "autoreply", "auto-reply", "automailer",
    "notification", "alert", "delivery-status", "mail-delivery",
)

# The prefix must end at a boundary — end of string, a digit, or a separator.
# Without this, `alert` swallows `alerta.garcia@` and `postmaster` swallows
# `postmasterson@`, silently dropping real people from lead promotion. A false
# positive here is worse than a false negative: a junk lead is visible and
# deletable, a discarded prospect is neither.
SYSTEM_PREFIX_PATTERN = re.compile(
    r"^(?:" + "|".join(re.escape(p) for p in SYSTEM_PREFIXES) + r")(?=$|[0-9._+\-])",
    re.IGNORECASE,
)

# Variable-envelope-return-path and Sender-Rewriting-Scheme locals. These carry
# an encoded original recipient, so every bounce has a *different* local part —
# an exact-match list can never catch them, and each one would otherwise become
# its own unique "lead".
#   bounces+12345-abc=example.com@sender.net
#   msprvs1=1234abc=bounces@sender.net
#   srs0=xyz=ab=example.com=user@forwarder.net
#   prvs=1234abcd=user@example.com
VERP_PATTERN = re.compile(
    r"^(?:"
    r"bounces?[+=\-]"
    r"|m?sprvs\d*[=+]"
    r"|prvs[=+]"
    r"|srs\d+[=+]"
    r"|b\d{6,}[=+\-]"
    r")",
    re.IGNORECASE,
)

# Shared human mailboxes — real people, but not a person.
ROLE_LOCALPARTS = frozenset({
    "info", "information", "contact", "contactus", "hello", "hi", "enquiry",
    "enquiries", "inquiry", "inquiries", "office", "team", "general",
    # `mail@` and `root@` read like infrastructure but are routinely a real
    # company's primary contact address — mail@ especially in German-speaking
    # markets. Classing them as system deleted live prospects
    # (mail@mafo-institut.com, root@f1-solutions.net) in a purge dry run, so
    # they are role mailboxes: not promotable as named leads, still reachable.
    "mail", "root",
    "sales", "marketing", "business", "bd", "partnerships", "press", "media",
    "support", "help", "helpdesk", "service", "services", "customerservice",
    "customercare", "care", "feedback",
    "admin", "administrator", "webmaster", "hostmaster", "sysadmin", "it",
    "billing", "invoices", "invoice", "accounts", "accounting", "account",
    "account-services", "accountservices", "finance", "payments", "ar", "ap",
    "hr", "jobs", "careers", "recruitment", "recruiting", "hiring",
    "legal", "privacy", "security", "compliance", "dpo", "gdpr",
    "newsletter", "news", "subscribe", "unsubscribe", "updates", "digest",
})


def split_address(email: str) -> tuple[str, str]:
    """(local_part, domain), both lowercased. ('', '') for anything unparseable."""
    if not email:
        return "", ""
    addr = str(email).strip().lower()
    # Tolerate "Name <addr@example.com>" — callers do not always pre-parse.
    match = re.search(r"<([^>]+)>", addr)
    if match:
        addr = match.group(1).strip()
    if addr.count("@") != 1:
        return "", ""
    local, domain = addr.split("@", 1)
    return local.strip(), domain.strip()


def is_malformed_address(email: str) -> bool:
    """True when the value is not a parseable address at all.

    Distinct from `is_system_address` on purpose. Enrichment leaves literal
    placeholders behind — `firstname.lastname`, `firstnamelastname` — on lead
    records belonging to real, named people at real companies. Folding those
    into "system address" made a cleanup script propose deleting a Kantar
    contact as though it were a mailer-daemon. Unmailable and not-a-person are
    different problems and want different handling.
    """
    local, domain = split_address(email)
    return not local or not domain


def is_system_address(email: str) -> bool:
    """True for automated infrastructure — bounce notifiers, daemons, no-reply.

    Never a lead and never mailable. A positive identification only: malformed
    input is NOT system (see is_malformed_address), so callers that delete on
    this predicate cannot destroy a real person carrying a broken address.
    """
    local, domain = split_address(email)
    if not local or not domain:
        return False

    if local in SYSTEM_LOCALPARTS:
        return True
    if VERP_PATTERN.match(local):
        return True
    if SYSTEM_PREFIX_PATTERN.match(local):
        return True

    # Some MTAs bounce from the subdomain rather than a recognisable local part
    # (e.g. anything@bounce.example.com or @mailer.example.net).
    first_label = domain.split(".")[0]
    if first_label in {"bounce", "bounces", "mailer-daemon", "postmaster", "noreply", "no-reply"}:
        return True

    return False


def is_role_address(email: str) -> bool:
    """True for a shared mailbox (info@, sales@, billing@) — real but not a person."""
    local, _ = split_address(email)
    if not local:
        return False
    if local in ROLE_LOCALPARTS:
        return True
    # Hyphen/dot variants of the same idea: customer-service@, account.services@
    normalised = local.replace(".", "-").replace("_", "-")
    return normalised.replace("-", "") in {r.replace("-", "") for r in ROLE_LOCALPARTS}


def is_promotable_lead_address(email: str, allow_role: bool = False) -> bool:
    """Whether this address may become a lead.

    `allow_role=True` keeps shared mailboxes, for callers that deliberately
    want them (an inbound enquiry from info@ is a real prospect even though it
    is not a named person). System and malformed addresses are never allowed.
    """
    return rejection_reason(email, allow_role=allow_role) is None


def rejection_reason(email: str, allow_role: bool = False) -> Optional[str]:
    """Why the address was rejected, for logging. None if acceptable."""
    if is_malformed_address(email):
        return "malformed_address"
    if is_system_address(email):
        return "system_address"
    if not allow_role and is_role_address(email):
        return "role_address"
    return None


def is_mailable(email: str) -> bool:
    """Whether we may send to this address at all.

    Broader than promotion: role mailboxes are perfectly mailable, malformed
    and system addresses are not. This is the send-time question.
    """
    return not is_malformed_address(email) and not is_system_address(email)
