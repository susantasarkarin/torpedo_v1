"""
EmailAIService — event → context → AI decision → deterministic routing, per the
master prompt's §1 mandate ("do not build isolated decision engines"). Every
classification and every follow-up decision goes through the *same*
`app.ai.decision_engine.DecisionEngine` Slice 11 built — this module owns only the
email-specific context assembly and the deterministic routing table that turns a
classification into an action.

**Routing is deliberately a plain dict-shaped dispatch on a closed classification
set, never fuzzy string matching on free-text model output.** `analyze_and_route()`
raises `EmailAIError` before touching any other service if the model returns
anything outside `EMAIL_CLASSIFICATIONS` — a malformed classification must not
reach `_route()` and partially apply.

**Every routed action reuses an existing, already-governed service — nothing here
is a new write path**: `SALES_LEAD` calls `LeadGenService.ingest()` (Slice 6's
identity-resolution/dedup pipeline, unchanged); `UNSUBSCRIBE` calls
`SuppressionService.suppress()` (Slice 7); `INVOICE`/`PAYMENT`/`BILL` calls
`ReconciliationService.record_external_entry()` (Slice 8) — which only ever
*records a candidate entry for reconciliation*, never touches an invoice/bill
balance directly, per master-prompt §7's explicit "do not let AI directly alter
accounting balances." Every other classification (`EXISTING_CLIENT`, `SUPPLIER`,
`CINT`, `PANEL`, `MEETING`, `SUPPORT`, `COMPLAINT`, `SPAM`, `IRRELEVANT`, `OTHER`)
gets classified and audited but triggers no further action yet — a deliberately
conservative default, not a silent gap: routing rules for those are for whichever
slice actually owns that workflow to add, not for this one to guess at.

**`analyze_and_route()` is idempotent on the email itself**, not on a caller-supplied
key: an email already classified returns the same `Decision`, reconstructed from its
original `AiProposal`, rather than re-running the model and routing a second time
(the direct fix for "duplicate event → no duplicate action").
"""

from __future__ import annotations

from app.ai.decision_engine import Decision, DecisionEngine
from app.emailai.drafting import EmailMessageDrafter
from app.emailai.models import EMAIL_CLASSIFICATIONS, InboundEmail
from app.finance.service import ReconciliationService
from app.leadgen.service import LeadGenService
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.models.money import Money
from app.outreach.service import MessagingFacade
from app.outreach.suppression import SuppressionService

# Classifications that trigger no further automated action beyond classify + audit
# — see module docstring for why this is a deliberate, conservative default.
_NO_AUTOMATED_ACTION = frozenset({"EXISTING_CLIENT", "SUPPLIER", "CINT", "PANEL", "MEETING", "SUPPORT", "COMPLAINT", "SPAM", "IRRELEVANT", "OTHER"})


class EmailAIError(Exception):
    """The model returned a classification outside the closed set, or a routed
    action's own service rejected the request. Same discipline as every other
    domain's single error type."""


class EmailAIService:
    def __init__(
        self,
        emails: CanonicalRepository[InboundEmail],
        ai_proposals: CanonicalRepository[AiProposal],
        activities: CanonicalRepository[Activity],
        decision_engine: DecisionEngine,
        leadgen: LeadGenService,
        suppression: SuppressionService,
        reconciliation: ReconciliationService,
        outreach: MessagingFacade,
        drafter: EmailMessageDrafter,
    ):
        self._emails = emails
        self._ai_proposals = ai_proposals
        self._activities = activities
        self._decision_engine = decision_engine
        self._leadgen = leadgen
        self._suppression = suppression
        self._reconciliation = reconciliation
        self._outreach = outreach
        self._drafter = drafter

    async def ingest_email(
        self, *, org_id: str, actor: str, provider: str, provider_message_id: str,
        from_address: str, to_address: str, subject: str, body: str, thread_id: str | None = None,
    ) -> InboundEmail:
        existing = await self._emails.find_one({"provider": provider, "provider_message_id": provider_message_id})
        if existing:
            return existing
        return await self._emails.insert(
            InboundEmail(
                org_id=org_id, created_by=actor, updated_by=actor, provider=provider, provider_message_id=provider_message_id,
                from_address=from_address, to_address=to_address, subject=subject, body=body, thread_id=thread_id,
            )
        )

    async def analyze_and_route(self, *, org_id: str, actor: str, email_id: str) -> Decision:
        email = await self._get_or_raise(email_id)

        if email.classification is not None:
            existing_proposal = await self._ai_proposals.find_one({"task": "classify_email", "subject_id": email.id})
            if existing_proposal:
                return Decision.model_validate(existing_proposal.proposed_fields)

        context = {"from_address": email.from_address, "to_address": email.to_address, "subject": email.subject, "body": email.body}
        decision = await self._decision_engine.decide(org_id=org_id, task="classify_email", subject_id=email.id, context=context)

        if decision.decision not in EMAIL_CLASSIFICATIONS:
            raise EmailAIError(f"model returned an unrecognized email classification {decision.decision!r} — refusing to route")

        await self._emails.update(email.id, email.version, {"classification": decision.decision, "classification_confidence": decision.confidence}, updated_by=actor)
        await self._route(org_id=org_id, actor=actor, email=email, decision=decision)
        return decision

    async def _route(self, *, org_id: str, actor: str, email: InboundEmail, decision: Decision) -> None:
        classification = decision.decision

        if classification == "SALES_LEAD":
            payload = {
                "email": decision.extracted_entities.get("contact_email") or email.from_address,
                "name": decision.extracted_entities.get("contact_name"),
                "company_domain": decision.extracted_entities.get("company_domain"),
                "company_name": decision.extracted_entities.get("company_name"),
                "title": decision.extracted_entities.get("title"),
            }
            await self._leadgen.ingest(org_id=org_id, actor=actor, source_type="email", source_record_id=email.id, payload=payload)

        elif classification == "UNSUBSCRIBE":
            await self._suppression.suppress(org_id=org_id, actor=actor, email=email.from_address, reason="unsubscribed_via_email", source="email")

        elif classification in ("INVOICE", "PAYMENT", "BILL"):
            amount_data = decision.extracted_entities.get("amount")
            if amount_data:
                await self._reconciliation.record_external_entry(
                    org_id=org_id, actor=actor, source="email", external_reference=email.id,
                    amount=Money(amount_minor=int(amount_data.get("amount_minor", 0)), currency=amount_data.get("currency", "INR")),
                )

        elif classification not in _NO_AUTOMATED_ACTION:
            raise EmailAIError(f"classification {classification!r} is in EMAIL_CLASSIFICATIONS but has no routing rule — this is a real gap, not a silent no-op")

        await self._activities.insert(
            Activity(
                org_id=org_id, created_by=actor, updated_by=actor, type="email_classified",
                subject_type="inbound_email", subject_id=email.id, actor_type="system", actor_id=actor,
                payload={"classification": classification, "confidence": decision.confidence},
            )
        )

    async def decide_followup(self, *, org_id: str, actor: str, email_id: str, mailbox_id: str) -> Decision:
        """The AI decides whether/how to follow up; `MessagingFacade.send()` is
        what actually enforces suppression/kill-switch/budget/footer — this method
        never bypasses it, and never sends when the decision isn't auto-appliable
        (low confidence or `requires_human_approval`)."""
        email = await self._get_or_raise(email_id)
        context = {
            "original_subject": email.subject, "original_body": email.body,
            "from_address": email.from_address, "classification": email.classification,
        }
        decision = await self._decision_engine.decide(org_id=org_id, task="email_followup_decision", subject_id=email.id, context=context)

        if "send_response" in decision.actions and decision.is_auto_appliable():
            idempotency_key = f"email-followup:{email.id}:{decision.decision}"
            await self._outreach.send(
                org_id=org_id, actor=actor, mailbox_id=mailbox_id, to_email=email.from_address,
                idempotency_key=idempotency_key, drafter=self._drafter,
                draft_context={"original_subject": email.subject, "original_body": email.body, "reasoning": decision.reasoning_summary},
            )
        return decision

    async def _get_or_raise(self, email_id: str) -> InboundEmail:
        email = await self._emails.get(email_id)
        if email is None:
            raise EmailAIError(f"email {email_id} does not exist")
        return email
