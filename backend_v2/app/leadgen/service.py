"""
LeadGenService — the orchestrator, and the only thing in this package with a
database handle. Everything else (AIClassifier implementations, source adapters that
would call this) is a pure function that hands data to this service; nothing else
writes.

The pipeline, in order, matching lead_generation_specification.md: ingest (§2, with
§3 identity resolution inline) -> enrich_and_qualify (§4 enrichment, §5-6
qualification — AI proposes, the canonical scorer decides) -> assign (§8 ownership)
-> enroll (§9 contactability, §10 enrollment). Every transition writes exactly one
Activity record (register §2.7 / spec's one-canonical-stream rule).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.identity.facet_service import FacetService
from app.identity.facets import LeadState
from app.identity.models import Person
from app.identity.service import IdentityService
from app.leadgen.ai import AI_CONFIDENCE_THRESHOLD, AIClassifier, AIUnavailable
from app.leadgen.models import (
    ASSIGNED,
    CONVERTED,
    DISCOVERED,
    DISQUALIFIED,
    ENRICHING,
    ENROLLED,
    QUALIFIED,
    DeadLetterEvent,
    LeadEnrollment,
    RawLeadEvent,
)
from app.leadgen.scoring import SENIOR_TITLE_MARKERS, ICPProfile, score_lead
from app.outreach.suppression import SuppressionService
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository


class LeadGenError(Exception):
    """Invalid state transition, missing parent, or a suppressed/unassigned lead
    attempting a step it isn't eligible for. Distinct from FacetAttachmentError
    (identity-layer) and VersionConflict (repository-layer) — this is the leadgen
    pipeline's own error class, per the same "one error type per failure class"
    discipline as AuthenticationFailed/PermissionDenied."""


@dataclass(frozen=True)
class IngestResult:
    lead_state_id: str
    person_id: str
    is_new_lead: bool


@dataclass(frozen=True)
class QualificationResult:
    lead_state_id: str
    status: str  # QUALIFIED | DISQUALIFIED | "AI_UNAVAILABLE"
    score: int | None


class LeadGenService:
    def __init__(
        self,
        identity: IdentityService,
        facets: FacetService,
        suppression: SuppressionService,
        *,
        raw_events: CanonicalRepository[RawLeadEvent],
        ai_proposals: CanonicalRepository[AiProposal],
        enrollments: CanonicalRepository[LeadEnrollment],
        dead_letters: CanonicalRepository[DeadLetterEvent],
        activities: CanonicalRepository[Activity],
    ):
        self._identity = identity
        self._facets = facets
        self._suppression = suppression
        self._raw_events = raw_events
        self._ai_proposals = ai_proposals
        self._enrollments = enrollments
        self._dead_letters = dead_letters
        self._activities = activities

    async def get_lead(self, lead_state_id: str) -> LeadState | None:
        return await self._facets.get_lead_state(lead_state_id)

    # ------------------------------------------------------------------ ingest

    async def ingest(
        self, *, org_id: str, actor: str, source_type: str, source_record_id: str, payload: dict
    ) -> IngestResult:
        existing_event = await self._raw_events.find_one(
            {"source_type": source_type, "source_record_id": source_record_id}
        )
        if existing_event and existing_event.resolved_lead_state_id:
            return IngestResult(
                lead_state_id=existing_event.resolved_lead_state_id,
                person_id=existing_event.resolved_person_id,
                is_new_lead=False,
            )

        try:
            account_id = None
            company_domain = payload.get("company_domain")
            if company_domain:
                account_resolution = await self._identity.resolve_account(
                    org_id=org_id, actor=actor, domain=company_domain, name=payload.get("company_name")
                )
                account_id = account_resolution.account_id

            person_resolution = await self._identity.resolve_person(
                org_id=org_id, actor=actor,
                linkedin_url=payload.get("linkedin_url"), email=payload.get("email"), name=payload.get("name"),
                title=payload.get("title"),
            )
            person_id = person_resolution.person_id

            # Reuse a non-terminal LeadState for this person if one already exists —
            # "same person from two sources -> one Person" must also mean "one active
            # lead journey," not a second LeadState racing the first.
            existing_lead = await self._facets.find_lead_state(
                {"person_id": person_id, "state": {"$nin": [DISQUALIFIED, CONVERTED]}}
            )
            if existing_lead:
                lead_state, is_new_lead = existing_lead, False
            else:
                lead_state = await self._facets.attach_lead_state(
                    actor=actor, person_id=person_id, source_type=source_type, account_id=account_id
                )
                is_new_lead = True

            if existing_event:
                await self._raw_events.update(
                    existing_event.id, existing_event.version,
                    {"resolved_person_id": person_id, "resolved_lead_state_id": lead_state.id},
                    updated_by=actor,
                )
            else:
                await self._raw_events.insert(
                    RawLeadEvent(
                        org_id=org_id, created_by=actor, updated_by=actor,
                        source_type=source_type, source_record_id=source_record_id, payload=payload,
                        resolved_person_id=person_id, resolved_lead_state_id=lead_state.id,
                    )
                )

            await self._record_activity(
                org_id=org_id, type="lead_ingested", subject_id=lead_state.id, actor=actor,
                payload={"source_type": source_type, "is_new_lead": is_new_lead},
            )
            return IngestResult(lead_state_id=lead_state.id, person_id=person_id, is_new_lead=is_new_lead)

        except Exception as exc:
            # spec §35: never silently drop a failed event. Recorded, then re-raised
            # — the DLQ record is for later inspection/retry, not a substitute for
            # telling THIS caller their attempt failed.
            await self._dead_letters.insert(
                DeadLetterEvent(
                    org_id=org_id, created_by=actor, updated_by=actor,
                    source_type=source_type, source_record_id=source_record_id,
                    error=str(exc), payload=payload,
                )
            )
            raise

    # -------------------------------------------------------- enrich & qualify

    async def enrich_and_qualify(
        self, *, org_id: str, actor: str, lead_state_id: str, ai_classifier: AIClassifier, profile: ICPProfile
    ) -> QualificationResult:
        lead = await self._get_lead_or_raise(lead_state_id, org_id=org_id)
        if lead.state not in (DISCOVERED, ENRICHING):
            raise LeadGenError(f"lead {lead_state_id} is not eligible for enrichment (state={lead.state})")

        if lead.state == DISCOVERED:
            lead = await self._facets.update_lead_state(lead.id, lead.version, {"state": ENRICHING}, updated_by=actor)
            await self._record_activity(
                org_id=lead.org_id, type="lead_state_changed", subject_id=lead.id, actor=actor,
                payload={"from": DISCOVERED, "to": ENRICHING},
            )

        person = await self._identity.get_person(lead.person_id)
        account = await self._identity.get_account(lead.account_id) if lead.account_id else None

        applied_title = person.title if person else None
        applied_industry = account.industry if account else None
        applied_country: str | None = None  # Person carries no country field in this slice

        try:
            ai_result = await ai_classifier.classify(
                person_fields={"title": applied_title, "given_name": person.given_name if person else None},
                account_fields={"industry": applied_industry, "domain": account.domain if account else None},
            )
        except AIUnavailable:
            # I-4, applied: the lead stays in ENRICHING — genuinely unresolved,
            # awaiting retry — never silently promoted to QUALIFIED or DISQUALIFIED.
            await self._record_activity(
                org_id=lead.org_id, type="enrichment_ai_unavailable", subject_id=lead.id, actor=actor, payload={}
            )
            return QualificationResult(lead_state_id=lead.id, status="AI_UNAVAILABLE", score=None)

        proposal_status = "approved" if ai_result.confidence >= AI_CONFIDENCE_THRESHOLD else "rejected"
        await self._ai_proposals.insert(
            AiProposal(
                org_id=lead.org_id, created_by=actor, updated_by=actor,
                task="lead_enrichment", subject_id=lead.id, model=ai_result.model, model_version=ai_result.model_version,
                confidence=ai_result.confidence, proposed_fields=ai_result.fields, status=proposal_status,
            )
        )
        await self._record_activity(
            org_id=lead.org_id, type="ai_proposal_created", subject_id=lead.id, actor=actor,
            payload={"status": proposal_status, "confidence": ai_result.confidence},
        )

        if proposal_status == "approved":
            # AI proposes enrichment fields only, never a verdict — see ai.py's
            # docstring. What happens next (qualify or not) is decided exclusively
            # by score_lead() below, using whatever fields ended up applied here.
            applied_title = ai_result.fields.get("title", applied_title)
            applied_industry = ai_result.fields.get("industry", applied_industry)
            applied_country = ai_result.fields.get("country", applied_country)

        seniority_marker_present = bool(applied_title) and any(
            marker in applied_title.lower() for marker in SENIOR_TITLE_MARKERS
        )
        result = score_lead(
            title=applied_title, industry=applied_industry, country=applied_country,
            seniority_marker_present=seniority_marker_present, profile=profile,
        )

        new_state = QUALIFIED if result.qualifies else DISQUALIFIED
        changes: dict = {"state": new_state, "icp_score": result.score}
        if new_state == DISQUALIFIED:
            changes["disqualify_reason"] = "below_icp_threshold"
        await self._facets.update_lead_state(lead.id, lead.version, changes, updated_by=actor)

        await self._record_activity(
            org_id=lead.org_id, type="lead_qualified" if result.qualifies else "lead_disqualified",
            subject_id=lead.id, actor=actor, payload={"score": result.score, "breakdown": result.breakdown},
        )
        return QualificationResult(lead_state_id=lead.id, status=new_state, score=result.score)

    # ------------------------------------------------------------- assignment

    async def assign(self, *, org_id: str, actor: str, lead_state_id: str, owner: str, team: str | None = None) -> LeadState:
        lead = await self._get_lead_or_raise(lead_state_id, org_id=org_id)
        if lead.state != QUALIFIED:
            raise LeadGenError(f"lead {lead_state_id} must be qualified before assignment (state={lead.state})")

        updated = await self._facets.update_lead_state(
            lead.id, lead.version, {"state": ASSIGNED, "owner": owner, "team": team}, updated_by=actor
        )
        await self._record_activity(
            org_id=lead.org_id, type="lead_assigned", subject_id=lead.id, actor=actor,
            payload={"owner": owner, "team": team},
        )
        return updated

    # --------------------------------------------------------- contactability

    async def check_contactability(self, person_id: str) -> bool:
        """Always evaluated live — never reads a cached field on the lead itself.
        See lead_generation_specification.md §9 and Slice 5's guard test that
        LeadState has no stored contactability field at all."""
        person = await self._identity.get_person(person_id)
        if person is None or not person.primary_email:
            return False  # no verifiable channel = fail closed, not "assume contactable"
        return not await self._suppression.is_suppressed(person.primary_email)

    # ------------------------------------------------------------- enrollment

    async def enroll(self, *, org_id: str, actor: str, lead_state_id: str, brand_id: str) -> LeadEnrollment:
        lead = await self._get_lead_or_raise(lead_state_id, org_id=org_id)
        if lead.state not in (ASSIGNED, ENROLLED):
            raise LeadGenError(f"lead {lead_state_id} must be assigned before enrollment (state={lead.state})")

        # Re-checked here, at the moment of enrollment, not inherited from qualify()
        # or assign() — a lead contactable when assigned may have been suppressed
        # since. This is the literal test of lead_generation_specification.md §9's
        # rule, not just a restatement of it.
        if not await self.check_contactability(lead.person_id):
            raise LeadGenError(f"lead {lead_state_id} is not contactable")

        existing = await self._enrollments.find_one({"lead_state_id": lead_state_id, "brand_id": brand_id})
        if existing:
            return existing  # idempotent — same (lead, brand) pair, no duplicate

        if lead.account_id:
            await self._identity.ensure_brand_relationship(
                org_id=lead.org_id, actor=actor, account_id=lead.account_id, brand_id=brand_id, relationship_type="prospect"
            )

        saved = await self._enrollments.insert(
            LeadEnrollment(
                org_id=lead.org_id, created_by=actor, updated_by=actor,
                lead_state_id=lead_state_id, person_id=lead.person_id, account_id=lead.account_id, brand_id=brand_id,
            )
        )

        if lead.state == ASSIGNED:
            # First enrollment transitions the lead; a second brand enrollment on an
            # already-ENROLLED lead just adds another LeadEnrollment row (locked
            # principle 5 — no "first brand wins" here either).
            await self._facets.update_lead_state(lead.id, lead.version, {"state": ENROLLED}, updated_by=actor)

        await self._record_activity(
            org_id=lead.org_id, type="lead_enrolled", subject_id=lead.id, actor=actor,
            payload={"brand_id": brand_id, "enrollment_id": saved.id},
        )
        return saved

    # ------------------------------------------------------- account contacts

    async def list_account_contacts(self, *, org_id: str, account_id: str) -> list[Person]:
        """The real "list every contact at this account" query — the piece the
        checklist named as the actual gap, not a selection algorithm (there was
        nothing to rank over a query that didn't exist yet). `LeadState.person_id`
        is singular by design (one lead = one person); "multiple contacts at one
        account" only becomes real data once every `LeadState.account_id`
        pointing at the same account is aggregated back to distinct `Person`
        records, which is exactly what this does.

        Deliberately scoped to `LeadState` — the one Person<->Account link this
        layer (identity + its facets) owns. `Opportunity.account_id`/`person_id`
        is CRM's own data, a layer downstream of identity; reaching into it here
        would invert the module dependency direction this codebase has kept
        consistent since Slice 4. If CRM ever needs a combined view, that
        composition belongs in the CRM module, calling this one — not the
        reverse.
        """
        account = await self._identity.get_account(account_id)
        if account is None or account.org_id != org_id:
            raise LeadGenError(f"account {account_id} does not exist")

        leads = await self._facets.list_lead_states({"org_id": org_id, "account_id": account_id})
        contacts: list[Person] = []
        for person_id in {lead.person_id for lead in leads}:
            person = await self._identity.get_person(person_id)
            if person is not None:
                contacts.append(person)
        return contacts

    # ----------------------------------------------------------------- helpers

    async def _get_lead_or_raise(self, lead_state_id: str, *, org_id: str) -> LeadState:
        lead = await self._facets.get_lead_state(lead_state_id)
        if lead is None or lead.org_id != org_id:
            raise LeadGenError(f"lead state {lead_state_id} does not exist")
        return lead

    async def _record_activity(self, *, org_id: str, type: str, subject_id: str, actor: str, payload: dict) -> None:
        await self._activities.insert(
            Activity(
                org_id=org_id, created_by=actor, updated_by=actor,
                type=type, subject_type="lead", subject_id=subject_id,
                actor_type="system" if actor == "system" else "user", actor_id=actor,
                payload=payload,
            )
        )
