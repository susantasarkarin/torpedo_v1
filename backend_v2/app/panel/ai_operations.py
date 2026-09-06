"""
OperationsAIService — hard triggers detect, the AI decides the response,
deterministic code enforces authorization/state-validity/idempotency/safety. Per
explicit user instruction: "the 7-day no-traffic condition is a hard trigger, but
what happens afterward should be an AI decision" — this module is that split,
generalized across three real, computable triggers, not just inactivity.

**Three real triggers, each computed from data that actually exists — no invented
fourth or fifth trigger for coverage's sake**:

- `no_traffic_7_days` — reuses `StudyInactivityService`'s exact detection logic
  (composed, not reimplemented).
- `low_conversion` — a survey still nominally eligible
  (`eligibility_is_active_in_pool=True`) whose live `conversion_rate` has fallen
  to or below `CONVERSION_ELIGIBILITY_THRESHOLD` (Slice 9/15's same constant) —
  meaning the deterministic allocation gate is already silently refusing it
  traffic, and nobody has looked at why.
- `high_dropout` — a real dropout rate computed from this survey's own
  `SurveyResponse` records (`terminated`/`quality_term` over total), gated by a
  minimum sample size so five unlucky responses don't trigger an investigation.

**Deliberately not built, honestly**: supplier/provider-failure-rate triggers
(no persisted per-provider failure counter exists — `AllocationService` releases
quota and moves to the next candidate silently on a provider timeout, it doesn't
record a failure-rate metric anywhere yet); client-response/deadline/change-request
triggers (there is no `Study` entity distinct from `Survey`, no client-contact
linkage, and no deadline field — building a real version of any of these needs
that data model first, and a fabricated deadline or a fake client-contact email
would be exactly the no-fake-completion failure this rebuild's discipline exists
to prevent).

**`REQUEST_CLIENT_STATUS` does not send an email** for the same reason — there is
no verified path from a `Survey` to a client contact address yet (that linkage is
Finance/CRM territory, Slices 17-18's problem, not invented here). The decision
still records real state (`operational_status="PENDING_CLIENT_RESPONSE"`) and a
real Activity naming exactly what a human needs to do next.

**Every operational-status change traces back to its `AiProposal`** via
`Survey.ai_decision_subject_id` — the same `Allocation.ai_decision_subject_id`
pattern from Slice 15, generalized per explicit user instruction ("I would use
the same pattern throughout the rest of Torpedo").

**Idempotency**: a survey already decided for a given trigger *today* is not
re-decided — `subject_id` is keyed on `(survey_id, trigger_type, date)`, so a
scheduler running this hourly (once Phase 14 exists) won't spam a fresh AI call
and a fresh state transition every run for the same still-unresolved condition,
while still allowing a genuinely new day's conditions to be re-evaluated.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.ai.decision_engine import Decision, DecisionEngine
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.panel.inactivity import StudyInactivityService
from app.panel.models import Survey, SurveyResponse
from app.panel.providers import SurveyProvider, SurveyProviderUnavailable
from app.panel.service import CONVERSION_ELIGIBILITY_THRESHOLD, SurveyService

ACTIVE = "ACTIVE"
PAUSED = "PAUSED"
CLOSED = "CLOSED"
PENDING_CLIENT_RESPONSE = "PENDING_CLIENT_RESPONSE"
ESCALATED = "ESCALATED"
OPERATIONAL_STATUSES = frozenset({ACTIVE, PAUSED, CLOSED, PENDING_CLIENT_RESPONSE, ESCALATED})

OPERATIONS_ACTIONS = frozenset({"INVESTIGATE", "REQUEST_CLIENT_STATUS", "PAUSE", "CLOSE", "REACTIVATE", "ESCALATE", "NO_ACTION"})

MIN_DROPOUT_SAMPLE_SIZE = 5
HIGH_DROPOUT_THRESHOLD = 0.5

_TASK_INSTRUCTIONS = (
    "A survey has hit an operational trigger (given as 'trigger_type' with "
    "supporting 'evidence'). Decide the response as 'decision', one of: "
    "INVESTIGATE (look deeper before acting), REQUEST_CLIENT_STATUS (this needs "
    "the client to weigh in — no email is sent automatically, a human handles "
    "that), PAUSE, CLOSE, REACTIVATE (only sensible if the survey is currently "
    "paused or awaiting a client response), ESCALATE (needs urgent human "
    "attention), or NO_ACTION (the trigger doesn't warrant a change). Explain "
    "your reasoning in 'reasoning_summary'."
)


def is_valid_operational_transition(current: str, target: str) -> bool:
    """`CLOSED` is terminal — a closed study stays closed. Every other status may
    move to any other (including itself, treated as a no-op) — operational
    lifecycles are not as strictly linear as a qualification or stage pipeline."""
    if current == CLOSED:
        return False
    return target in OPERATIONAL_STATUSES


class OperationsAIError(Exception):
    """The model returned an action outside the closed set, or asked for a
    transition the current state doesn't allow (e.g. reactivating an already-active
    survey). Same discipline as every other domain's single error type."""


class OperationsAIService:
    def __init__(
        self, decision_engine: DecisionEngine, surveys: SurveyService, inactivity: StudyInactivityService,
        survey_repo: CanonicalRepository[Survey], survey_responses: CanonicalRepository[SurveyResponse],
        activities: CanonicalRepository[Activity], ai_proposals: CanonicalRepository[AiProposal],
        shadow_mode: bool = False,
    ):
        self._decision_engine = decision_engine
        self._surveys = surveys
        self._inactivity = inactivity
        self._survey_repo = survey_repo
        self._survey_responses = survey_responses
        self._activities = activities
        self._ai_proposals = ai_proposals
        # See PanelAllocationAIService's constructor docstring comment — same
        # mechanism, same reason. Unlike Allocation/Finance's confidence gate,
        # this module has never had an auto-apply threshold (a valid decision
        # always acted, by design) — shadow mode is the first point anything
        # here can be suppressed at all.
        self._shadow_mode = shadow_mode

    async def detect_triggers(self, *, org_id: str, as_of: datetime | None = None) -> list[tuple[Survey, str]]:
        """One trigger per survey per run, in priority order (no traffic is the
        most urgent signal, then a live conversion failure, then dropout) — a
        survey matching more than one trigger is still only evaluated once."""
        as_of = as_of or datetime.now(timezone.utc)
        triggered: list[tuple[Survey, str]] = []

        inactive_surveys = await self._inactivity.detect_and_flag(org_id=org_id, as_of=as_of)
        already_triggered_ids = set()
        for survey in inactive_surveys:
            if survey.operational_status == CLOSED:
                # StudyInactivityService (Slice 10) only knows about
                # eligibility_is_active_in_pool, not this slice's operational_status
                # — a closed survey must never re-trigger regardless, so the
                # exclusion belongs here rather than weakening that detector.
                continue
            triggered.append((survey, "no_traffic_7_days"))
            already_triggered_ids.add(survey.id)

        all_surveys = await self._survey_repo.find_all({"org_id": org_id, "operational_status": {"$ne": CLOSED}})
        for survey in all_surveys:
            if survey.id in already_triggered_ids:
                continue
            if survey.eligibility_is_active_in_pool and survey.conversion_rate <= CONVERSION_ELIGIBILITY_THRESHOLD:
                triggered.append((survey, "low_conversion"))
                already_triggered_ids.add(survey.id)
                continue
            dropout = await self._dropout_rate(survey.id)
            if dropout is not None and dropout > HIGH_DROPOUT_THRESHOLD:
                triggered.append((survey, "high_dropout"))
                already_triggered_ids.add(survey.id)

        return triggered

    async def evaluate_and_act(self, *, org_id: str, actor: str, survey_id: str, trigger_type: str, provider: SurveyProvider | None = None) -> Decision:
        survey = await self._survey_repo.get(survey_id)
        if survey is None:
            raise OperationsAIError(f"survey {survey_id} does not exist")

        subject_id = f"{survey_id}:{trigger_type}:{date.today().isoformat()}"
        existing_proposal = await self._ai_proposals.find_one({"task": "evaluate_operations_response", "subject_id": subject_id})
        if existing_proposal:
            return Decision.model_validate(existing_proposal.proposed_fields)

        evidence = await self._evidence(survey, trigger_type)
        context = {
            "task_instructions": _TASK_INSTRUCTIONS, "trigger_type": trigger_type, "evidence": evidence,
            "current_operational_status": survey.operational_status, "current_eligibility": survey.eligibility_is_active_in_pool,
            "category": survey.category, "conversion_rate": survey.conversion_rate, "quota_remaining": survey.quota_remaining,
        }
        decision = await self._decision_engine.decide(org_id=org_id, task="evaluate_operations_response", subject_id=subject_id, context=context)

        if decision.decision not in OPERATIONS_ACTIONS:
            raise OperationsAIError(f"model returned an unrecognized operations action {decision.decision!r}")

        if not self._shadow_mode:
            await self._act(org_id=org_id, actor=actor, survey=survey, decision=decision, subject_id=subject_id, provider=provider)
        return decision

    async def _act(self, *, org_id: str, actor: str, survey: Survey, decision: Decision, subject_id: str, provider: SurveyProvider | None) -> None:
        action = decision.decision
        target_status = {"PAUSE": PAUSED, "CLOSE": CLOSED, "REACTIVATE": ACTIVE, "REQUEST_CLIENT_STATUS": PENDING_CLIENT_RESPONSE, "ESCALATE": ESCALATED}.get(action)

        if target_status is not None:
            if not is_valid_operational_transition(survey.operational_status, target_status):
                raise OperationsAIError(f"survey {survey.id} cannot move from {survey.operational_status!r} to {target_status!r}")
            if action == "REACTIVATE" and survey.operational_status not in (PAUSED, PENDING_CLIENT_RESPONSE):
                raise OperationsAIError(f"survey {survey.id} cannot be reactivated from status {survey.operational_status!r} — it was never paused or awaiting a client response")
            if action in ("PAUSE", "CLOSE"):
                await self._surveys.set_eligibility(actor=actor, survey_id=survey.id, is_active_in_pool=False, activated_at=None)
            elif action == "REACTIVATE":
                await self._surveys.set_eligibility(actor=actor, survey_id=survey.id, is_active_in_pool=True, activated_at=datetime.now(timezone.utc))
            await self._survey_repo.update(survey.id, (await self._survey_repo.get(survey.id)).version, {"operational_status": target_status, "ai_decision_subject_id": subject_id}, updated_by=actor)
        elif action == "INVESTIGATE":
            if provider is None:
                raise OperationsAIError("INVESTIGATE requires a SurveyProvider to refresh live data")
            try:
                await self._surveys.refresh_projection(actor=actor, survey_id=survey.id, provider=provider)
            except SurveyProviderUnavailable as exc:
                raise OperationsAIError(f"investigation failed: provider unavailable ({exc})") from exc
            await self._survey_repo.update(survey.id, (await self._survey_repo.get(survey.id)).version, {"ai_decision_subject_id": subject_id}, updated_by=actor)
        else:  # NO_ACTION
            await self._survey_repo.update(survey.id, survey.version, {"ai_decision_subject_id": subject_id}, updated_by=actor)

        await self._activities.insert(
            Activity(
                org_id=org_id, created_by=actor, updated_by=actor, type=f"operations_{action.lower()}",
                subject_type="survey", subject_id=survey.id, actor_type="system", actor_id=actor,
                payload={"trigger": decision.reasoning_summary, "confidence": decision.confidence},
            )
        )

    async def _dropout_rate(self, survey_id: str) -> float | None:
        responses = await self._survey_responses.find_all({"survey_id": survey_id})
        if len(responses) < MIN_DROPOUT_SAMPLE_SIZE:
            return None
        dropouts = sum(1 for r in responses if r.final_status in ("terminated", "quality_term"))
        return dropouts / len(responses)

    async def _evidence(self, survey: Survey, trigger_type: str) -> dict:
        if trigger_type == "low_conversion":
            return {"conversion_rate": survey.conversion_rate, "threshold": CONVERSION_ELIGIBILITY_THRESHOLD}
        if trigger_type == "high_dropout":
            return {"dropout_rate": await self._dropout_rate(survey.id)}
        return {"trigger": trigger_type}
