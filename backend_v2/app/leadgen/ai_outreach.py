"""
OutreachAIService — the ICP→outreach flow (master-prompt §15-19), routed through
the same `DecisionEngine` as email and GSC lead-gen. `LeadEnrollment.sequence_state`
(Slice 14's one model change) is "for persistence and reporting" per §18 — the AI
decides the transition, this service only validates it's a member of the closed
`OUTREACH_SEQUENCE_STATES` set and persists it, exactly the same discipline
`app.crm.models.is_valid_transition` applies to `Opportunity.stage`, except here the
*decider* is the model, not a hand-written rule table.

**Reuses, not rebuilds, three things Slice 6/7 already proved out**:
`LeadGenService.check_contactability()` (live suppression check, Slice 6),
`MessagingFacade.send()` (kill switch/suppression/budget/footer/idempotency,
Slice 7), and `EmailMessageDrafter`-shaped drafting (Slice 12) — outreach
personalization needs the identical "use only the facts in context, never invent
one" drafting discipline §17 asks for, so this module reuses that class rather
than writing a second one with the same rules.

**Contact selection (§16) is honestly not built** — `LeadState.person_id` is
singular in this data model (Slice 4/6's identity spine attaches one `Person` per
lead, and there is no `account_id`-scoped "list every contact at this account"
query built yet). Choosing among multiple contacts needs that query capability
first; faking a selection algorithm over a single-item list would be exactly the
kind of decoration this rebuild's discipline exists to avoid. Documented as a real
gap, not silently skipped.

**Contactability is re-checked at the moment of send, and overrides the model even
if the model didn't ask to stop** — the same "governance is a hard boundary, the AI
proposes inside it, never around it" rule §10 states for suppression applies here
identically: a lead the model wants to contact but that fails the live
contactability check is never sent to, regardless of what `decision.decision` says.
"""

from __future__ import annotations

from app.ai.decision_engine import Decision, DecisionEngine
from app.emailai.drafting import EmailMessageDrafter
from app.leadgen.models import LeadEnrollment
from app.leadgen.service import LeadGenService
from app.models.base import CanonicalRepository
from app.outreach.service import MessagingFacade

OUTREACH_SEQUENCE_STATES = frozenset(
    {"OUTREACH_READY", "CONTACTED", "RESPONDED", "ENGAGED", "MEETING", "OPPORTUNITY", "NURTURE", "UNRESPONSIVE", "STOPPED"}
)


class OutreachAIError(Exception):
    """Missing enrollment/lead, or the model returned a sequence state outside
    the closed set. Same discipline as every other domain's single error type."""


class OutreachAIService:
    def __init__(self, decision_engine: DecisionEngine, leadgen: LeadGenService, outreach: MessagingFacade, drafter: EmailMessageDrafter, enrollments: CanonicalRepository[LeadEnrollment], shadow_mode: bool = False):
        self._decision_engine = decision_engine
        self._leadgen = leadgen
        self._outreach = outreach
        self._drafter = drafter
        self._enrollments = enrollments
        # See PanelAllocationAIService's constructor docstring comment. Scoped
        # to the actual send only — the sequence_state label update below
        # stays live even in shadow mode, same reasoning as EmailAIService's
        # classification.
        self._shadow_mode = shadow_mode

    async def decide_and_act(self, *, org_id: str, actor: str, enrollment_id: str, mailbox_id: str) -> Decision:
        enrollment = await self._enrollments.get(enrollment_id)
        if enrollment is None or enrollment.org_id != org_id:
            raise OutreachAIError(f"enrollment {enrollment_id} does not exist")
        lead = await self._leadgen.get_lead(enrollment.lead_state_id)
        if lead is None or lead.org_id != org_id:
            raise OutreachAIError(f"lead {enrollment.lead_state_id} does not exist")

        person = await self._leadgen._identity.get_person(lead.person_id)
        contactable = await self._leadgen.check_contactability(lead.person_id)

        context = {
            "lead_qualification_state": lead.state, "current_sequence_state": enrollment.sequence_state,
            "icp_score": lead.icp_score, "contactable": contactable, "person_title": person.title if person else None,
        }
        decision = await self._decision_engine.decide(org_id=org_id, task="evaluate_outreach", subject_id=enrollment.id, context=context)

        if decision.decision not in OUTREACH_SEQUENCE_STATES:
            raise OutreachAIError(f"model returned an unrecognized outreach sequence state {decision.decision!r}")

        if "send_message" in decision.actions and decision.is_auto_appliable() and not self._shadow_mode and contactable and person and person.primary_email:
            idempotency_key = f"outreach-ai:{enrollment.id}:{decision.decision}"
            await self._outreach.send(
                org_id=org_id, actor=actor, mailbox_id=mailbox_id, to_email=person.primary_email,
                idempotency_key=idempotency_key, drafter=self._drafter,
                draft_context={"person_title": person.title, "reasoning": decision.reasoning_summary, "sequence_state": decision.decision},
            )

        await self._enrollments.update(enrollment.id, enrollment.version, {"sequence_state": decision.decision, "ai_decision_subject_id": enrollment.id}, updated_by=actor)
        return decision
