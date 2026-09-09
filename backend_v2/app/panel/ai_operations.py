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

**Client-deadline and stale-pending-response triggers, closed 2026-09-09**: the
checklist's stated blocker ("no `Study` entity distinct from `Survey`, no
client-contact linkage, no deadline field") turned out to be mostly already
solved by Slice 18 — `billing.py`'s own docstring settled "there is no separate
`Study` entity" (`Survey.opportunity_id`/`client_rate` already carry the study
concept), and `Opportunity.account_id`/`person_id` is a real, resolvable
client-contact linkage once an `Opportunity` exists. The one genuinely missing
piece was a deadline field, so that's what got added
(`Survey.client_deadline`, `SurveyService.set_client_deadline()`) — two new
triggers, `deadline_passed`/`deadline_approaching`, computed from it exactly
like every other threshold here. `pending_client_response_stale` closes the
other real gap: a survey nobody followed up on after `REQUEST_CLIENT_STATUS`,
detected from the `operations_request_client_status` Activity trail (never
`Survey.updated_at`, which bumps on unrelated field writes like a projection
refresh and would silently reset a staleness clock keyed on it).

**Still deliberately not built, honestly**: the **change-request** trigger.
Unlike a deadline or a stale pending-response, there is no data source at all
for "the client asked for something to change" — no support-ticket or
change-request entity exists anywhere in this codebase. Fabricating one to
close out a checklist line would be exactly the no-fake-completion failure
this rebuild's discipline exists to prevent, so it stays not built until a
real change-request data model exists to detect from.

**`REQUEST_CLIENT_STATUS` still does not send an email** — that remains a
deliberate, separate decision (an automatic, recurring, real client-facing send
is a bigger step than resolving *who* to contact, and this codebase's own
discipline elsewhere treats firing a real external send as needing explicit
human authorization, not something an AI operations loop does on its own
initiative). What changed: the Activity it records now carries the real,
resolved contact (`client_contact`: person id/name/email, via
`Survey.opportunity_id -> Opportunity.person_id -> Person`) when that linkage
exists, or `None` — never a fabricated placeholder — when it doesn't. A human
now has exactly who to email, in the record, without this service sending
anything itself.

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

from datetime import date, datetime, timedelta, timezone

from app.ai.decision_engine import Decision, DecisionEngine
from app.crm.models import Opportunity
from app.identity.models import Person
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

# Checklist follow-up: "no persisted per-provider failure counter exists" —
# AllocationService now records a real Activity (type="provider_timeout") on
# every SurveyProviderUnavailable it hits, and this is the threshold that
# turns a run of them into a real operational trigger. Same discipline as
# HIGH_DROPOUT_THRESHOLD/MIN_DROPOUT_SAMPLE_SIZE above: an operational
# cadence choice, not a locked business rule — how many failures in how long
# genuinely warrants a human looking at a supplier integration is a real
# judgment call, adjustable here without touching the detection mechanism.
PROVIDER_FAILURE_THRESHOLD = 3
PROVIDER_FAILURE_WINDOW = timedelta(hours=24)

# Same "operational cadence choice, not a locked business rule" discipline as
# the constants above. DEADLINE_WARNING_DAYS is how far out a client_deadline
# starts warranting a look before it's actually missed; STALE_PENDING_RESPONSE_WINDOW
# is how long a survey may sit in PENDING_CLIENT_RESPONSE before nobody having
# followed up becomes its own trigger.
DEADLINE_WARNING_DAYS = 3
STALE_PENDING_RESPONSE_WINDOW = timedelta(days=5)

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
        *,
        opportunities: CanonicalRepository[Opportunity] | None = None,
        people: CanonicalRepository[Person] | None = None,
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
        # Optional, same reason `provider: SurveyProvider | None` is optional for
        # INVESTIGATE: a caller that hasn't wired CRM/identity repositories still
        # gets correct behavior (REQUEST_CLIENT_STATUS records client_contact=None,
        # never a crash and never a fabricated contact).
        self._opportunities = opportunities
        self._people = people

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

            if survey.operational_status == PENDING_CLIENT_RESPONSE:
                # A survey already parked awaiting client input doesn't also need
                # a fresh health-metric trigger this run — the only thing worth
                # raising is that nobody's followed up.
                since = await self._pending_client_response_since(survey.id)
                if since is not None and (as_of - since) > STALE_PENDING_RESPONSE_WINDOW:
                    triggered.append((survey, "pending_client_response_stale"))
                    already_triggered_ids.add(survey.id)
                continue

            if survey.client_deadline is not None:
                days_remaining = (survey.client_deadline - as_of).total_seconds() / 86400
                if days_remaining <= 0:
                    triggered.append((survey, "deadline_passed"))
                    already_triggered_ids.add(survey.id)
                    continue
                if days_remaining <= DEADLINE_WARNING_DAYS:
                    triggered.append((survey, "deadline_approaching"))
                    already_triggered_ids.add(survey.id)
                    continue

            if survey.eligibility_is_active_in_pool and survey.conversion_rate <= CONVERSION_ELIGIBILITY_THRESHOLD:
                triggered.append((survey, "low_conversion"))
                already_triggered_ids.add(survey.id)
                continue
            dropout = await self._dropout_rate(survey.id)
            if dropout is not None and dropout > HIGH_DROPOUT_THRESHOLD:
                triggered.append((survey, "high_dropout"))
                already_triggered_ids.add(survey.id)
                continue
            failures = await self._recent_provider_failure_count(survey.id, as_of=as_of)
            if failures >= PROVIDER_FAILURE_THRESHOLD:
                triggered.append((survey, "provider_failure_rate"))
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
                await self._surveys.set_eligibility(org_id=org_id, actor=actor, survey_id=survey.id, is_active_in_pool=False, activated_at=None)
            elif action == "REACTIVATE":
                await self._surveys.set_eligibility(org_id=org_id, actor=actor, survey_id=survey.id, is_active_in_pool=True, activated_at=datetime.now(timezone.utc))
            await self._survey_repo.update(survey.id, (await self._survey_repo.get(survey.id)).version, {"operational_status": target_status, "ai_decision_subject_id": subject_id}, updated_by=actor)
        elif action == "INVESTIGATE":
            if provider is None:
                raise OperationsAIError("INVESTIGATE requires a SurveyProvider to refresh live data")
            try:
                await self._surveys.refresh_projection(org_id=org_id, actor=actor, survey_id=survey.id, provider=provider)
            except SurveyProviderUnavailable as exc:
                raise OperationsAIError(f"investigation failed: provider unavailable ({exc})") from exc
            await self._survey_repo.update(survey.id, (await self._survey_repo.get(survey.id)).version, {"ai_decision_subject_id": subject_id}, updated_by=actor)
        else:  # NO_ACTION
            await self._survey_repo.update(survey.id, survey.version, {"ai_decision_subject_id": subject_id}, updated_by=actor)

        payload = {"trigger": decision.reasoning_summary, "confidence": decision.confidence}
        if action == "REQUEST_CLIENT_STATUS":
            # The real close of "no verified path from a Survey to a client
            # contact address" — resolved here, recorded honestly (None, never
            # a fabricated placeholder, when the linkage isn't wired or isn't
            # set). See module docstring: this still never sends anything.
            payload["client_contact"] = await self._resolve_client_contact(survey)

        await self._activities.insert(
            Activity(
                org_id=org_id, created_by=actor, updated_by=actor, type=f"operations_{action.lower()}",
                subject_type="survey", subject_id=survey.id, actor_type="system", actor_id=actor,
                payload=payload,
            )
        )

    async def _dropout_rate(self, survey_id: str) -> float | None:
        responses = await self._survey_responses.find_all({"survey_id": survey_id})
        if len(responses) < MIN_DROPOUT_SAMPLE_SIZE:
            return None
        dropouts = sum(1 for r in responses if r.final_status in ("terminated", "quality_term"))
        return dropouts / len(responses)

    async def _recent_provider_failure_count(self, survey_id: str, *, as_of: datetime) -> int:
        return await self._activities._collection.count_documents({
            "type": "provider_timeout", "subject_id": survey_id, "deleted_at": None,
            "created_at": {"$gte": as_of - PROVIDER_FAILURE_WINDOW},
        })

    async def _pending_client_response_since(self, survey_id: str) -> datetime | None:
        """The real elapsed-time source for staleness — the most recent
        `operations_request_client_status` Activity, never `Survey.updated_at`
        (which bumps on any field write, e.g. an unrelated projection refresh,
        and would silently reset a staleness clock keyed on it)."""
        latest = await self._activities._collection.find_one(
            {"type": "operations_request_client_status", "subject_id": survey_id, "deleted_at": None},
            sort=[("created_at", -1)],
        )
        return latest["created_at"] if latest else None

    async def _resolve_client_contact(self, survey: Survey) -> dict | None:
        """Real resolution via Survey.opportunity_id -> Opportunity.person_id ->
        Person — never a fallback guess. Returns None, not a fabricated
        placeholder, whenever any link in that chain isn't wired or isn't set;
        a human then knows to look it up themselves rather than trusting a
        fake contact."""
        if self._opportunities is None or self._people is None or survey.opportunity_id is None:
            return None
        opportunity = await self._opportunities.get(survey.opportunity_id)
        if opportunity is None or opportunity.person_id is None:
            return None
        person = await self._people.get(opportunity.person_id)
        if person is None:
            return None
        name = f"{person.given_name or ''} {person.family_name or ''}".strip() or None
        return {"person_id": person.id, "name": name, "email": person.primary_email}

    async def _evidence(self, survey: Survey, trigger_type: str) -> dict:
        if trigger_type == "low_conversion":
            return {"conversion_rate": survey.conversion_rate, "threshold": CONVERSION_ELIGIBILITY_THRESHOLD}
        if trigger_type == "high_dropout":
            return {"dropout_rate": await self._dropout_rate(survey.id)}
        if trigger_type == "provider_failure_rate":
            count = await self._recent_provider_failure_count(survey.id, as_of=datetime.now(timezone.utc))
            return {"failure_count": count, "window_hours": PROVIDER_FAILURE_WINDOW.total_seconds() / 3600, "threshold": PROVIDER_FAILURE_THRESHOLD}
        if trigger_type in ("deadline_approaching", "deadline_passed"):
            days_remaining = (survey.client_deadline - datetime.now(timezone.utc)).total_seconds() / 86400
            return {"client_deadline": survey.client_deadline.isoformat(), "days_remaining": round(days_remaining, 1)}
        if trigger_type == "pending_client_response_stale":
            since = await self._pending_client_response_since(survey.id)
            days_pending = (datetime.now(timezone.utc) - since).total_seconds() / 86400 if since else None
            return {
                "pending_since": since.isoformat() if since else None,
                "days_pending": round(days_pending, 1) if days_pending is not None else None,
                "window_days": STALE_PENDING_RESPONSE_WINDOW.days,
            }
        return {"trigger": trigger_type}
