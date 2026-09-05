"""
MessagingFacade — the single send path (I-1 applied to outreach). Both of v1's
competing pipelines (register D-05: "Pipeline 4 sends live mail with no kill switch,
budget, unified log, or CAN-SPAM footer"; D-06: "Pipeline 5 sends with zero
suppression/budget/kill-switch, dormant but fully wired") collapse into this one
`send()` method — there is no second, lighter-weight way to dispatch a message that
skips a gate, no "test send" flag (P1 list: "test-send bypasses kill switch"), and no
caller-supplied override for any check below.

Gate order, every call, no exceptions:
  idempotency replay -> mailbox lookup -> kill switch -> suppression -> content
  (caller-supplied or drafted) -> CAN-SPAM footer -> budget reservation -> provider
  dispatch -> unified log entry.

Everything up to and including the footer check is evaluated before budget is
reserved on purpose — a message this org would never legally send (suppressed,
paused, missing opt-out) must not consume send cap on its way to being blocked.

A provider failure releases its budget reservation, persists a `failed` SendLogEntry,
and re-raises — the same "record then re-raise" DLQ discipline as
`app.leadgen.service.ingest()`. A policy block (suppressed/paused/budget/compliance)
is not an error: `send()` returns the log entry describing why nothing went out,
mirroring `LeadGenService`'s split between expected outcomes (returned) and invalid
states (raised).

**Idempotency caveat, stated once here rather than left implicit**: `idempotency_key`
dedup is a `find_one` lookup before insert, not a unique-index constraint (no index
infrastructure exists yet in backend_v2 — same caveat `BudgetService` documents).
This guarantees correctness for sequential retries, the practical failure mode this
slice targets; true concurrent double-submission of the same key needs a unique index,
deferred alongside the codebase's other "no index yet" gaps.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.outreach.budget import BudgetService
from app.outreach.drafting import DraftUnavailable, MessageDrafter
from app.outreach.kill_switch import KillSwitchService
from app.outreach.models import Mailbox, Message, SendLogEntry
from app.outreach.providers import SendFailed, SendProvider
from app.outreach.suppression import SuppressionService

_FOOTER_MARKER = "unsubscribe"  # deliberately minimal CAN-SPAM check — a literal
# opt-out mechanism must be present in the body; a full compliance engine (physical
# address, one-click List-Unsubscribe headers, etc.) is out of this slice's scope.


class OutreachError(Exception):
    """Invalid request or provider failure — distinct from a policy-blocked send,
    which is a normal, returned outcome. Same discipline as LeadGenError."""


class MessagingFacade:
    def __init__(
        self,
        *,
        mailboxes: CanonicalRepository[Mailbox],
        messages: CanonicalRepository[Message],
        send_logs: CanonicalRepository[SendLogEntry],
        ai_proposals: CanonicalRepository[AiProposal],
        activities: CanonicalRepository[Activity],
        suppression: SuppressionService,
        kill_switch: KillSwitchService,
        budget: BudgetService,
        provider: SendProvider,
    ):
        self._mailboxes = mailboxes
        self._messages = messages
        self._send_logs = send_logs
        self._ai_proposals = ai_proposals
        self._activities = activities
        self._suppression = suppression
        self._kill_switch = kill_switch
        self._budget = budget
        self._provider = provider

    async def send(
        self,
        *,
        org_id: str,
        actor: str,
        mailbox_id: str,
        to_email: str,
        idempotency_key: str,
        subject: str | None = None,
        body: str | None = None,
        campaign_id: str | None = None,
        transactional: bool = False,
        drafter: MessageDrafter | None = None,
        draft_context: dict | None = None,
        day: str | None = None,
    ) -> SendLogEntry:
        existing = await self._send_logs.find_one({"org_id": org_id, "idempotency_key": idempotency_key})
        if existing:
            return existing

        mailbox = await self._mailboxes.get(mailbox_id)
        if mailbox is None or mailbox.org_id != org_id:
            raise OutreachError(f"mailbox {mailbox_id} not found")

        if await self._kill_switch.is_paused(org_id):
            return await self._log(
                org_id=org_id, actor=actor, mailbox_id=mailbox_id, to_email=to_email,
                idempotency_key=idempotency_key, status="kill_switch_active",
            )

        if await self._suppression.is_suppressed(to_email):
            return await self._log(
                org_id=org_id, actor=actor, mailbox_id=mailbox_id, to_email=to_email,
                idempotency_key=idempotency_key, status="suppressed",
            )

        if subject is None or body is None:
            if drafter is None:
                raise OutreachError("subject/body required when no drafter is supplied")
            try:
                draft = await drafter.draft(to_email=to_email, context=draft_context or {})
            except DraftUnavailable:
                return await self._log(
                    org_id=org_id, actor=actor, mailbox_id=mailbox_id, to_email=to_email,
                    idempotency_key=idempotency_key, status="draft_unavailable",
                )
            subject, body = draft.subject, draft.body
            await self._ai_proposals.insert(
                AiProposal(
                    org_id=org_id, created_by=actor, updated_by=actor,
                    task="message_drafting", subject_id=idempotency_key, model=draft.model,
                    model_version=draft.model_version, confidence=draft.confidence,
                    proposed_fields={"subject": subject, "body": body}, status="approved",
                )
            )

        if not transactional and _FOOTER_MARKER not in body.lower():
            return await self._log(
                org_id=org_id, actor=actor, mailbox_id=mailbox_id, to_email=to_email,
                idempotency_key=idempotency_key, status="compliance_blocked",
            )

        send_day = day or datetime.now(timezone.utc).date().isoformat()
        within_budget = await self._budget.reserve(org_id=org_id, mailbox_id=mailbox_id, day=send_day, cap=mailbox.daily_cap)
        if not within_budget:
            return await self._log(
                org_id=org_id, actor=actor, mailbox_id=mailbox_id, to_email=to_email,
                idempotency_key=idempotency_key, status="budget_blocked",
            )

        message = await self._messages.insert(
            Message(
                org_id=org_id, created_by=actor, updated_by=actor,
                to_email=to_email, subject=subject, body=body, campaign_id=campaign_id, transactional=transactional,
            )
        )

        try:
            result = await self._provider.send(
                mailbox_credentials_id=mailbox.credentials_id, to_email=to_email, subject=subject, body=body
            )
        except SendFailed as exc:
            await self._budget.release(org_id=org_id, mailbox_id=mailbox_id, day=send_day)
            await self._log(
                org_id=org_id, actor=actor, mailbox_id=mailbox_id, to_email=to_email,
                idempotency_key=idempotency_key, status="failed", message_id=message.id, error=str(exc),
            )
            raise OutreachError(f"send failed for message {message.id}: {exc}") from exc

        return await self._log(
            org_id=org_id, actor=actor, mailbox_id=mailbox_id, to_email=to_email,
            idempotency_key=idempotency_key, status="sent", message_id=message.id,
            provider_message_id=result.provider_message_id,
        )

    async def record_bounce(self, *, org_id: str, actor: str, to_email: str, reason: str = "hard_bounce") -> None:
        """The D-07 fix: a provider-reported bounce becomes a canonical suppression
        event immediately, through the one SuppressionService every send path
        already checks — not a per-pipeline bounce table other paths never
        consult (register: "hard-bounced addresses stay mailable elsewhere")."""
        await self._suppression.suppress(org_id=org_id, actor=actor, email=to_email, reason=reason, source="bounce")

    async def _log(
        self,
        *,
        org_id: str,
        actor: str,
        mailbox_id: str,
        to_email: str,
        idempotency_key: str,
        status: str,
        message_id: str | None = None,
        provider_message_id: str | None = None,
        error: str | None = None,
    ) -> SendLogEntry:
        entry = await self._send_logs.insert(
            SendLogEntry(
                org_id=org_id, created_by=actor, updated_by=actor,
                message_id=message_id, mailbox_id=mailbox_id, to_email=to_email,
                status=status, idempotency_key=idempotency_key,
                provider_message_id=provider_message_id, error=error,
            )
        )
        await self._activities.insert(
            Activity(
                org_id=org_id, created_by=actor, updated_by=actor,
                type=f"message_{status}", subject_type="message", subject_id=entry.id,
                actor_type="system" if actor == "system" else "user", actor_id=actor,
                payload={"to_email": to_email, "mailbox_id": mailbox_id},
            )
        )
        return entry
