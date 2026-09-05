"""
PanelAllocationAIService — the AI evaluates which eligible survey best fits a
panelist and ranks the eligible set; `AllocationService.allocate()` (Slice 9,
unchanged) executes the choice atomically. Deliberately **not** a fixed-weights
scoring formula relabeled "AI" — the ranking is a real `DecisionEngine.decide()`
call, and every hard constraint (quota, eligibility, the >20% conversion gate) is
enforced by code the AI never sees a way around, not by trusting its judgment.

**The eligibility gate is enforced by never offering the choice, not by asking the
AI to decline it**: `SurveyService.list_eligible()` runs first, and its result is
the *entire* set of `survey_id`s the model is shown. If the model's response names
a `survey_id` outside that set, `evaluate_and_allocate()` raises rather than
silently dropping the invalid entry and continuing — a model that hallucinates an
ineligible choice fails the whole decision, loudly, not just that one entry.

**`decision.decision` is the model's top choice; `decision.entities` is the
model's ranked fallback list** (Slice 11's generic `entities: list[str]`,
domain-reinterpreted here as "other eligible survey_ids, in preference order" —
the same flexible reuse `entities`/`extracted_entities` get in every AI slice so
far, rather than a new schema per task). Both lists are validated against the
eligible set before either is trusted, and the *whole* ranked list is handed to
`AllocationService.allocate()`, which already knows how to fall through a ranked
list on a provider timeout or a lost quota race (Slice 9) — this slice doesn't
reimplement that fallback, it reuses it.

**Decision memory is real historical data re-queried on every call, not a
separate learning/training pipeline**: `historical_completion_rate`/
`historical_dropout_rate`/`previously_exposed_to_this_survey`/
`days_since_last_allocation` are computed fresh from `SurveyResponse`/`Allocation`
records each time context is built, so every new decision is automatically
informed by every real outcome recorded since the last one — no vector store, no
fine-tuning loop, per master-prompt §24's own "use the simplest architecture that
works reliably." `Allocation.ai_decision_subject_id` links an allocation back to
the `AiProposal` that chose it, so "why was this panelist sent here" is always
answerable.

**What's real context vs. an honest gap**: `category`/`length_minutes`/
`incentive` (Slice 15 added these three real `Survey` fields) and `cpi` (a proxy
for expected value) are real. Demographic profile-fit and fraud/risk signals are
**not included** — there is no consent-gated profile system or fraud-detection
pipeline built yet, and passing a fabricated value for either would be exactly
the no-fake-completion failure this rebuild's discipline exists to prevent.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.ai.decision_engine import Decision, DecisionEngine
from app.models.base import CanonicalRepository
from app.panel.models import Allocation, Survey, SurveyResponse
from app.panel.providers import SurveyProvider
from app.panel.service import AllocationService, SurveyService

_TASK_INSTRUCTIONS = (
    "Choose the single best 'eligible_surveys' entry (by survey_id) for this "
    "panelist as 'decision', using 'panelist_history_by_survey' as real historical "
    "signal — or 'NONE' if none are a good fit right now. List any other viable "
    "eligible survey_ids as 'entities', in your preferred fallback order. In "
    "'extracted_entities', give a per-survey breakdown keyed by survey_id: "
    "{score, expected_conversion, reasons, risks}. Never name a survey_id that "
    "is not in 'eligible_surveys' — that set is the only ones you may choose "
    "from, and choosing outside it will be rejected."
)


class PanelAllocationAIError(Exception):
    """No eligible surveys to offer the model, or the model chose a survey
    outside the eligible set it was actually shown. Same discipline as every
    other domain's single error type."""


class PanelAllocationAIService:
    def __init__(
        self, decision_engine: DecisionEngine, surveys: SurveyService, allocations: AllocationService,
        survey_responses: CanonicalRepository[SurveyResponse], allocation_repo: CanonicalRepository[Allocation],
    ):
        self._decision_engine = decision_engine
        self._surveys = surveys
        self._allocations = allocations
        self._survey_responses = survey_responses
        self._allocation_repo = allocation_repo

    async def evaluate_and_allocate(
        self, *, org_id: str, actor: str, person_id: str, vendor_id: str, country_code: str, respondent_ref: str, provider: SurveyProvider,
    ) -> tuple[Decision, Allocation | None]:
        """Returns `(Decision, Allocation | None)` — `None` when the model
        recommends no allocation at all, or when its recommendation wasn't
        auto-appliable (low confidence / `requires_human_approval`). Both are
        legitimate outcomes, not errors — a real allocation attempt that then
        loses a quota race, or finds every ranked candidate exhausted, still
        raises `SurveyError` from `AllocationService.allocate()` unchanged."""
        eligible = await self._surveys.list_eligible(org_id=org_id)
        if not eligible:
            raise PanelAllocationAIError("no surveys pass the deterministic eligibility gate — nothing to offer the model")

        eligible_ids = {s.id for s in eligible}
        history_by_survey = {s.id: await self._panelist_history(person_id=person_id, survey_id=s.id) for s in eligible}
        context = {
            "task_instructions": _TASK_INSTRUCTIONS,
            "eligible_surveys": [self._survey_context(s) for s in eligible],
            "panelist_history_by_survey": history_by_survey,
            "country_code": country_code,
        }

        subject_id = f"{person_id}:{respondent_ref}"
        decision = await self._decision_engine.decide(org_id=org_id, task="evaluate_panel_allocation", subject_id=subject_id, context=context)

        if decision.decision == "NONE":
            return decision, None

        ranked_ids = [decision.decision] + [e for e in decision.entities if e != decision.decision]
        for survey_id in ranked_ids:
            if survey_id not in eligible_ids:
                raise PanelAllocationAIError(f"model chose survey {survey_id!r}, which was not in the eligible set it was offered")

        if not decision.is_auto_appliable():
            return decision, None

        allocation = await self._allocations.allocate(
            org_id=org_id, actor=actor, candidate_survey_ids=ranked_ids, person_id=person_id, vendor_id=vendor_id,
            country_code=country_code, respondent_ref=respondent_ref, provider=provider, ai_decision_subject_id=subject_id,
        )
        return decision, allocation

    async def _panelist_history(self, *, person_id: str, survey_id: str) -> dict:
        responses = await self._survey_responses.find_all({"person_id": person_id})
        total = len(responses)
        completes = sum(1 for r in responses if r.final_status == "complete")
        dropouts = sum(1 for r in responses if r.final_status in ("terminated", "quality_term"))

        prior_allocations = await self._allocation_repo.find_all({"person_id": person_id})
        previously_exposed = any(a.survey_id == survey_id for a in prior_allocations)
        last_allocation_at = max((a.created_at for a in prior_allocations), default=None)
        days_since_last_allocation = (datetime.now(timezone.utc) - last_allocation_at).days if last_allocation_at else None

        return {
            "historical_completion_rate": round(completes / total, 3) if total else None,
            "historical_dropout_rate": round(dropouts / total, 3) if total else None,
            "total_prior_responses": total,
            "previously_exposed_to_this_survey": previously_exposed,
            "days_since_last_allocation": days_since_last_allocation,
        }

    def _survey_context(self, survey: Survey) -> dict:
        return {
            "survey_id": survey.id, "category": survey.category, "length_minutes": survey.length_minutes,
            "incentive_minor": survey.incentive.amount_minor if survey.incentive else None,
            "cpi_minor": survey.cpi.amount_minor, "conversion_rate": survey.conversion_rate, "quota_remaining": survey.quota_remaining,
        }
