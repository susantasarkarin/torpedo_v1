"""
InboundEmail — Slice 12's persisted shape. Named `app.emailai`, not `app.email`,
deliberately: `email` shadows the standard-library package, and a shadowed stdlib
import is exactly the kind of quiet footgun this codebase's naming has avoided
everywhere else (`app.crm` not `app.opportunities`, `app.panel` not `app.survey`).

`EMAIL_CLASSIFICATIONS` is a closed set — the model classifies into exactly one of
these, never a free-text label, so downstream routing (`EmailAIService._route()`)
can be a plain dict dispatch instead of fuzzy string matching.
"""

from __future__ import annotations

from app.models.base import CanonicalDocument

EMAIL_CLASSIFICATIONS = frozenset(
    {
        "SALES_LEAD", "EXISTING_CLIENT", "SUPPLIER", "CINT", "PANEL", "FINANCE",
        "INVOICE", "PAYMENT", "BILL", "MEETING", "SUPPORT", "COMPLAINT",
        "UNSUBSCRIBE", "SPAM", "IRRELEVANT", "OTHER",
        # Phase 4 (AI outreach) — a real reply to an outreach sequence, distinct
        # from EXISTING_CLIENT/SUPPORT: this classification is what lets
        # EmailAIService._route() deterministically mark the matching
        # LeadEnrollment RESPONDED, a real fact rather than the AI *guessing*
        # at reply status the next time it re-evaluates on a schedule.
        "OUTREACH_REPLY",
    }
)


class InboundEmail(CanonicalDocument):
    provider: str  # "gmail" | "imap" | ... — mirrors app.outreach.models.Mailbox.provider
    provider_message_id: str  # idempotency key, paired with provider — see EmailAIService.ingest_email
    from_address: str
    to_address: str
    subject: str
    body: str
    thread_id: str | None = None
    classification: str | None = None  # set once, by analyze_and_route() — None until analyzed
    classification_confidence: float | None = None
    ai_decision_subject_id: str | None = None  # traces back to the AiProposal that classified this email — same pattern as Allocation/Survey/Invoice/Bill
