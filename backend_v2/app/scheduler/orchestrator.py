"""
EventOrchestrator — claims a pending `Event`, dispatches it to the *same* real
AI service each of Slices 12-18 already built (never a new decision path,
never a second `DecisionEngine`), records the outcome. `EventDetectionService`
decides *what* needs attention; this class decides nothing — it only executes
what a detector already found, through code every prior slice's tests already
proved governed.

**Claiming is single-flight via `CanonicalRepository.update()`'s existing
optimistic-concurrency guarantee** — a version-guarded `PENDING/FAILED ->
PROCESSING` transition. A `VersionConflict` means someone else claimed it
first; this orchestrator just moves to the next event rather than treating
that as an error.

**A recoverable failure is recorded on the `Event`, never swallowed and never
crashes the whole cycle.** Every exception type each AI service's own module
already documents raising (`LLMUnavailable`, `DecisionEngineError`,
`SurveyProviderUnavailable`, and each domain's own `*Error`) is caught per
event, incrementing `attempts` and storing `last_error` — genuinely useful
right now, since every one of these calls will raise `LLMUnavailable` until
`RUNPOD_API_KEY` exists, and this is exactly the mechanism that makes that
safe to run on a cadence today: nothing fakes a decision, the event just waits,
retryable, for the credential. An exception *outside* that documented set is a
real bug, not an expected failure mode, and is deliberately left to propagate —
catching it here would hide it as indistinguishable from a credential-blocked
retry.
"""

from __future__ import annotations

from app.ai.decision_engine import DecisionEngineError
from app.ai.llm import LLMUnavailable
from app.emailai.service import EmailAIError, EmailAIService
from app.finance.ai_finance import AIFinanceError, AIFinanceService
from app.leadgen.ai_conversion import LeadConversionAIError, LeadConversionAIService
from app.leadgen.ai_leadgen import LeadGenAIError, LeadGenAIService
from app.leadgen.ai_outreach import OutreachAIError, OutreachAIService
from app.models.base import CanonicalRepository, VersionConflict
from app.panel.ai_operations import OperationsAIError, OperationsAIService
from app.panel.providers import SurveyProvider, SurveyProviderUnavailable
from app.scheduler.detectors import EventDetectionService
from app.scheduler.models import FAILED, MAX_ATTEMPTS, PENDING, PROCESSED, PROCESSING, Event

_RECOVERABLE_ERRORS = (
    LLMUnavailable, DecisionEngineError, SurveyProviderUnavailable,
    OperationsAIError, AIFinanceError, LeadGenAIError, EmailAIError, OutreachAIError, LeadConversionAIError,
)

ACTOR = "system"


class EventOrchestrator:
    def __init__(
        self, *, events: CanonicalRepository[Event], detection: EventDetectionService,
        operations_ai: OperationsAIService, finance_ai: AIFinanceService, leadgen_ai: LeadGenAIService,
        email_ai: EmailAIService, outreach_ai: OutreachAIService, survey_provider: SurveyProvider,
        conversion_ai: LeadConversionAIService,
    ):
        self._events = events
        self._detection = detection
        self._operations_ai = operations_ai
        self._finance_ai = finance_ai
        self._leadgen_ai = leadgen_ai
        self._email_ai = email_ai
        self._outreach_ai = outreach_ai
        self._survey_provider = survey_provider
        self._conversion_ai = conversion_ai

    async def run_detection_cycle(self, *, org_id: str) -> dict[str, int]:
        return await self._detection.run_all(org_id=org_id)

    async def process_pending(self, *, org_id: str, limit: int = 50) -> dict[str, int]:
        candidates = await self._events.find_all({"org_id": org_id, "processing_status": {"$in": [PENDING, FAILED]}})
        candidates = [e for e in candidates if e.processing_status == PENDING or e.attempts < MAX_ATTEMPTS][:limit]

        processed = failed = skipped = 0
        for event in candidates:
            try:
                claimed = await self._events.update(event.id, event.version, {"processing_status": PROCESSING}, updated_by=ACTOR)
            except VersionConflict:
                skipped += 1
                continue

            try:
                result = await self._dispatch(claimed)
            except _RECOVERABLE_ERRORS as exc:
                await self._events.update(claimed.id, claimed.version, {"processing_status": FAILED, "attempts": claimed.attempts + 1, "last_error": str(exc)}, updated_by=ACTOR)
                failed += 1
                continue

            await self._events.update(claimed.id, claimed.version, {"processing_status": PROCESSED, "result": result}, updated_by=ACTOR)
            processed += 1

        return {"processed": processed, "failed": failed, "skipped": skipped}

    async def _dispatch(self, event: Event) -> dict:
        handler = getattr(self, f"_handle_{event.event_type}")
        return await handler(event)

    async def _handle_survey_operations_trigger(self, event: Event) -> dict:
        decision = await self._operations_ai.evaluate_and_act(org_id=event.org_id, actor=ACTOR, survey_id=event.entity_id, trigger_type=event.payload["trigger_type"], provider=self._survey_provider)
        return {"decision": decision.decision, "confidence": decision.confidence}

    async def _handle_ar_followup_due(self, event: Event) -> dict:
        decision = await self._finance_ai.decide_ar_followup(org_id=event.org_id, actor=ACTOR, invoice_id=event.entity_id)
        return {"decision": decision.decision, "confidence": decision.confidence}

    async def _handle_ap_followup_due(self, event: Event) -> dict:
        decision = await self._finance_ai.decide_ap_followup(org_id=event.org_id, actor=ACTOR, bill_id=event.entity_id)
        return {"decision": decision.decision, "confidence": decision.confidence}

    async def _handle_reconciliation_unmatched(self, event: Event) -> dict:
        decision, payment = await self._finance_ai.match_payment_to_invoice(org_id=event.org_id, actor=ACTOR, reconciliation_record_id=event.entity_id)
        return {"decision": decision.decision, "confidence": decision.confidence, "payment_id": payment.id if payment else None}

    async def _handle_lead_icp_evaluation_due(self, event: Event) -> dict:
        decision = await self._leadgen_ai.evaluate_icp(org_id=event.org_id, actor=ACTOR, lead_state_id=event.entity_id, prospect_context=event.payload.get("prospect_context", {}))
        return {"decision": decision.decision, "confidence": decision.confidence}

    async def _handle_email_classification_due(self, event: Event) -> dict:
        decision = await self._email_ai.analyze_and_route(org_id=event.org_id, actor=ACTOR, email_id=event.entity_id)
        return {"decision": decision.decision, "confidence": decision.confidence}

    async def _handle_outreach_followup_due(self, event: Event) -> dict:
        decision = await self._outreach_ai.decide_and_act(org_id=event.org_id, actor=ACTOR, enrollment_id=event.entity_id, mailbox_id=event.payload["mailbox_id"])
        return {"decision": decision.decision, "confidence": decision.confidence}

    async def _handle_lead_conversion_due(self, event: Event) -> dict:
        decision, opportunity = await self._conversion_ai.evaluate_and_convert(org_id=event.org_id, actor=ACTOR, lead_state_id=event.entity_id)
        return {"decision": decision.decision, "confidence": decision.confidence, "opportunity_id": opportunity.id if opportunity else None}
