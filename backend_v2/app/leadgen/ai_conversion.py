"""
LeadConversionAIService — the AI-driven Lead -> Opportunity conversion this
codebase has explicitly, honestly documented as a manual gap since Slice 18's
end-to-end test ("no automatic Lead->Opportunity conversion anywhere in the
codebase") and repeated in every README entry since. Same architecture as
every other AI slice: deterministic candidate generation, a real
`DecisionEngine` call, governed execution through the unchanged Slice 10
`OpportunityService`.

**Deterministic eligibility, not an AI judgment call about who's even
offered.** A `LeadState` must already be `QUALIFIED`/`ASSIGNED`/`ENROLLED`
(cleared `app.leadgen.scoring`'s canonical qualification bar), have a real
`account_id` (an `Opportunity` needs a real commercial party — a `person_id`
alone isn't enough), and not already be `CONVERTED`. The AI decides
CONVERT/HOLD/REJECT only among leads that already pass this gate — it is
never asked "should this lead even be considered."

**`LeadState.state = CONVERTED` was a reserved value with zero writers
anywhere in this codebase before this slice** — defined in Slice 4/6
(`app.leadgen.models.CONVERTED`), excluded from `LeadGenService.ingest()`'s
"reuse a non-terminal lead" query, but never actually set. This is the first
real writer.

**Shadow-mode gated, the sixth service this applies to.** Creating a real
`Opportunity` is a commercial action with real downstream consequence — it
can later become a real `Invoice` via `OpportunityService.convert_to_invoice()`
— squarely the "consequential execution" class of action shadow mode exists
to hold back until a real model has been watched deciding well.
"""

from __future__ import annotations

from app.ai.decision_engine import Decision, DecisionEngine
from app.crm.models import Opportunity
from app.crm.service import OpportunityService
from app.identity.facet_service import FacetService
from app.identity.facets import LeadState
from app.identity.models import Account
from app.leadgen.models import ASSIGNED, CONVERTED, ENROLLED, QUALIFIED
from app.models.base import CanonicalRepository

CONVERSION_ELIGIBLE_STATES = frozenset({QUALIFIED, ASSIGNED, ENROLLED})
CONVERSION_ACTIONS = frozenset({"CONVERT", "HOLD", "REJECT"})

_TASK_INSTRUCTIONS = (
    "A qualified lead is a candidate for becoming a real sales Opportunity. "
    "Decide 'decision', one of: CONVERT (create a real Opportunity for this "
    "lead's account now), HOLD (promising, but not ready yet — revisit "
    "later), or REJECT (this lead should not become an opportunity — explain "
    "why in 'reasoning_summary')."
)


class LeadConversionAIError(Exception):
    """Lead missing, lead not eligible (wrong state or no real account), or
    the model returned an action outside the closed set. Same discipline as
    every other domain's single error type."""


class LeadConversionAIService:
    def __init__(
        self, decision_engine: DecisionEngine, facets: FacetService, opportunities: OpportunityService,
        accounts: CanonicalRepository[Account], shadow_mode: bool = False,
    ):
        self._decision_engine = decision_engine
        self._facets = facets
        self._opportunities = opportunities
        self._accounts = accounts
        # See PanelAllocationAIService's constructor docstring comment — same
        # mechanism. Creating a real Opportunity is consequential (it can
        # become a real Invoice downstream), so it's held back in shadow mode
        # exactly like the other five gated execution points.
        self._shadow_mode = shadow_mode

    async def list_conversion_eligible(self, *, org_id: str) -> list[LeadState]:
        """The deterministic candidate set — same 'offer the walls, don't ask
        the AI to build them' discipline as `SurveyService.list_eligible()`.
        A lead outside `CONVERSION_ELIGIBLE_STATES`, or with no real
        `account_id`, is never offered to the model as a choice at all."""
        candidates = await self._facets.list_lead_states({"org_id": org_id, "state": {"$in": list(CONVERSION_ELIGIBLE_STATES)}})
        return [lead for lead in candidates if lead.account_id is not None]

    async def evaluate_and_convert(self, *, org_id: str, actor: str, lead_state_id: str) -> tuple[Decision, Opportunity | None]:
        lead = await self._facets.get_lead_state(lead_state_id)
        if lead is None or lead.org_id != org_id:
            raise LeadConversionAIError(f"lead {lead_state_id} does not exist")
        if lead.state not in CONVERSION_ELIGIBLE_STATES:
            raise LeadConversionAIError(f"lead {lead_state_id} is not eligible for conversion (state={lead.state!r})")
        if lead.account_id is None:
            raise LeadConversionAIError(f"lead {lead_state_id} has no account — an Opportunity needs a real commercial party")

        account = await self._accounts.get(lead.account_id)
        context = {
            "task_instructions": _TASK_INSTRUCTIONS,
            "lead_state": lead.state, "icp_score": lead.icp_score,
            "account_industry": account.industry if account else None, "account_domain": account.domain if account else None,
            "previously_ai_icp_evaluated": lead.ai_decision_subject_id is not None,
        }
        decision = await self._decision_engine.decide(org_id=org_id, task="evaluate_lead_conversion", subject_id=lead_state_id, context=context)
        if decision.decision not in CONVERSION_ACTIONS:
            raise LeadConversionAIError(f"model returned an unrecognized conversion action {decision.decision!r}")

        if decision.decision != "CONVERT" or not decision.is_auto_appliable() or self._shadow_mode:
            # Still traced, even on HOLD/REJECT/shadow-suppressed — the same
            # "every decision is auditable, not just the ones that executed"
            # discipline every other domain applies. This is also what keeps
            # Phase 14's scheduler detector from re-offering the same lead on
            # every single tick — see app.scheduler.detectors' module
            # docstring for the one-shot-per-scheduler-run reasoning.
            await self._facets.update_lead_state(lead.id, lead.version, {"ai_conversion_decision_subject_id": lead_state_id}, updated_by=actor)
            return decision, None

        opportunity = await self._opportunities.create_opportunity(org_id=org_id, actor=actor, account_id=lead.account_id, person_id=lead.person_id)
        await self._facets.update_lead_state(lead.id, lead.version, {"state": CONVERTED, "ai_conversion_decision_subject_id": lead_state_id}, updated_by=actor)
        return decision, opportunity
