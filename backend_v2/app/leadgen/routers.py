"""
HTTP surface for lead generation. Same discipline as `app.identity.routers`: every
write derives `org_id` from the resolved identity, permission-gated throughout,
404-not-403 on cross-org reads.

`PassthroughAIClassifier` stands in for a real AI-gateway integration (out of this
slice's scope, same reasoning as Slice 4 deferring `PATCH`/brand-relationship
endpoints) — it proposes zero enrichment fields at full confidence, so qualification
proceeds on whatever `Person`/`Account` data already exists rather than being blocked
on an integration this slice doesn't build. Swapping in a real `AIClassifier` is a
one-line change to `get_ai_classifier()` below, not a redesign of this router.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from app.ai.decision_engine import Decision, DecisionEngine, DecisionEngineError
from app.ai.llm import LLMUnavailable, get_llm_provider
from app.ai.tools import ToolRegistry
from app.auth.dependencies import get_current_identity, require_permission
from app.crm.models import Opportunity
from app.crm.routers import get_opportunity_service
from app.db import get_database
from app.identity.facet_service import FacetService
from app.identity.facets import AuthIdentity, CustomerBilling, EmployeeRecord, LeadState, PanelistProfile, VendorProfile
from app.identity.models import Account, AccountBrandRelationship, Person
from app.identity.service import IdentityService
from app.leadgen.ai import AIClassificationResult, AIClassifier
from app.leadgen.ai_conversion import LeadConversionAIError, LeadConversionAIService
from app.leadgen.ai_leadgen import LeadGenAIError, LeadGenAIService
from app.leadgen.ai_outreach import OutreachAIError, OutreachAIService
from app.leadgen.gsc import GSCProvider, GSCProviderUnavailable, SearchSignal
from app.leadgen.models import DeadLetterEvent, LeadEnrollment, RawLeadEvent
from app.models.ai_proposal import AiProposal
from app.leadgen.scoring import ICPProfile
from app.leadgen.service import LeadGenError, LeadGenService, QualificationResult
from app.outreach.routers import get_outreach_service, get_send_provider
from app.outreach.suppression import Suppression, SuppressionService
from app.emailai.drafting import EmailMessageDrafter
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.rbac.identity import ResolvedIdentity
from app.rbac.permissions import LEAD_ASSIGN, LEAD_ENROLL, LEAD_INGEST, LEAD_QUALIFY, LEAD_READ, LEADGEN_AI_CONVERT, LEADGEN_AI_EVALUATE_ICP, LEADGEN_AI_GENERATE, OUTREACH_AI_DECIDE

router = APIRouter()

# Deliberately permissive default — no ICP profile management entity exists yet
# (scoring.py's own scope note). Real profile-per-org configuration is Slice 7+.
_DEFAULT_ICP_PROFILE = ICPProfile(industries=frozenset({"software", "technology", "saas"}), countries=frozenset({"us", "in", "gb"}))


class PassthroughAIClassifier:
    async def classify(self, *, person_fields: dict, account_fields: dict) -> AIClassificationResult:
        return AIClassificationResult(fields={}, confidence=1.0, model="passthrough", model_version="v1")


def get_ai_classifier() -> AIClassifier:
    return PassthroughAIClassifier()


def get_leadgen_service() -> LeadGenService:
    db = get_database()
    identity = IdentityService(
        people=CanonicalRepository(db["people"], Person),
        accounts=CanonicalRepository(db["accounts"], Account),
        brand_relationships=CanonicalRepository(db["account_brand_relationships"], AccountBrandRelationship),
        activities=CanonicalRepository(db["activities"], Activity),
    )
    facets = FacetService(
        people=CanonicalRepository(db["people"], Person),
        accounts=CanonicalRepository(db["accounts"], Account),
        activities=CanonicalRepository(db["activities"], Activity),
        lead_states=CanonicalRepository(db["lead_states"], LeadState),
        panelist_profiles=CanonicalRepository(db["panelist_profiles"], PanelistProfile),
        customer_billing=CanonicalRepository(db["customer_billing"], CustomerBilling),
        vendor_profiles=CanonicalRepository(db["vendor_profiles"], VendorProfile),
        employee_records=CanonicalRepository(db["employee_records"], EmployeeRecord),
        auth_identities=CanonicalRepository(db["auth_identities"], AuthIdentity),
    )
    suppression = SuppressionService(CanonicalRepository(db["suppressions"], Suppression))
    return LeadGenService(
        identity, facets, suppression,
        raw_events=CanonicalRepository(db["raw_lead_events"], RawLeadEvent),
        ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal),
        enrollments=CanonicalRepository(db["lead_enrollments"], LeadEnrollment),
        dead_letters=CanonicalRepository(db["dead_letters"], DeadLetterEvent),
        activities=CanonicalRepository(db["activities"], Activity),
    )


class NullGSCProvider:
    """Stand-in until Google Search Console credentials are supplied — no GSC
    credentials exist in this environment. Raises rather than returning a fake
    empty-but-successful analytics result, so a caller can't mistake "not
    configured" for "no search signals today"."""

    async def get_search_analytics(self, *, site_url: str, days: int = 28) -> list[SearchSignal]:
        raise GSCProviderUnavailable("GSC integration is not configured — no credentials in this environment")


def get_gsc_provider() -> GSCProvider:
    return NullGSCProvider()


def get_leadgen_ai_service() -> LeadGenAIService:
    db = get_database()
    llm = get_llm_provider(db)
    engine = DecisionEngine(llm, ToolRegistry(), CanonicalRepository(db["ai_proposals"], AiProposal))
    return LeadGenAIService(engine, get_leadgen_service())


def get_lead_conversion_ai_service() -> LeadConversionAIService:
    from app.config import get_settings
    from app.finance.routers import get_invoice_service

    db = get_database()
    llm = get_llm_provider(db)
    engine = DecisionEngine(llm, ToolRegistry(), CanonicalRepository(db["ai_proposals"], AiProposal))
    facets = FacetService(
        people=CanonicalRepository(db["people"], Person), accounts=CanonicalRepository(db["accounts"], Account),
        activities=CanonicalRepository(db["activities"], Activity), lead_states=CanonicalRepository(db["lead_states"], LeadState),
        panelist_profiles=CanonicalRepository(db["panelist_profiles"], PanelistProfile), customer_billing=CanonicalRepository(db["customer_billing"], CustomerBilling),
        vendor_profiles=CanonicalRepository(db["vendor_profiles"], VendorProfile), employee_records=CanonicalRepository(db["employee_records"], EmployeeRecord),
        auth_identities=CanonicalRepository(db["auth_identities"], AuthIdentity),
    )
    return LeadConversionAIService(
        engine, facets, get_opportunity_service(get_invoice_service()), CanonicalRepository(db["accounts"], Account),
        shadow_mode=get_settings().ai_shadow_mode,
    )


def get_outreach_ai_service() -> OutreachAIService:
    from app.config import get_settings

    db = get_database()
    llm = get_llm_provider(db)
    engine = DecisionEngine(llm, ToolRegistry(), CanonicalRepository(db["ai_proposals"], AiProposal))
    return OutreachAIService(
        engine, get_leadgen_service(), get_outreach_service(get_send_provider()),
        EmailMessageDrafter(llm), CanonicalRepository(db["lead_enrollments"], LeadEnrollment),
        shadow_mode=get_settings().ai_shadow_mode,
    )


class DecideOutreachRequest(BaseModel):
    mailbox_id: str


# Security-audit finding (2026-09-09): neither field below had any size limit,
# despite both being serialized directly into a real LLM prompt
# (DecisionEngine.decide()/AIClassifier.classify()) — a caller with the right
# permission could send an arbitrarily large payload to tie up the one
# inference slot this deployment's local model serves from (see
# docs/LOCAL_LLM_RUNBOOK.md's DoS note; the systemd memory cap makes this
# self-healing, not catastrophic, but a clean 422 here is a much better
# failure than relying on that cap to be hit at all).
MAX_AI_CONTEXT_BYTES = 20_000  # generous for real business context, not for abuse


def _validate_ai_context_size(v: dict) -> dict:
    size = len(json.dumps(v))
    if size > MAX_AI_CONTEXT_BYTES:
        raise ValueError(f"context payload too large ({size} bytes, max {MAX_AI_CONTEXT_BYTES})")
    return v


class GenerateLeadsRequest(BaseModel):
    site_url: str
    internal_context: dict = {}

    _validate_internal_context_size = field_validator("internal_context")(_validate_ai_context_size)


class EvaluateIcpRequest(BaseModel):
    prospect_context: dict

    _validate_prospect_context_size = field_validator("prospect_context")(_validate_ai_context_size)


class IngestRequest(BaseModel):
    source_type: str
    source_record_id: str
    payload: dict


class AssignRequest(BaseModel):
    owner: str
    team: str | None = None


class EnrollRequest(BaseModel):
    brand_id: str


@router.post("/leads/ingest")
async def ingest_lead(
    body: IngestRequest,
    identity: ResolvedIdentity = Depends(require_permission(LEAD_INGEST)),
    svc: LeadGenService = Depends(get_leadgen_service),
):
    try:
        result = await svc.ingest(
            org_id=identity.org_id, actor=identity.user_id,
            source_type=body.source_type, source_record_id=body.source_record_id, payload=body.payload,
        )
    except Exception as exc:  # dead-lettered inside svc.ingest; surface as 502 here
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ingestion failed: {exc}") from exc
    return result


@router.get("/leads/{lead_state_id}", response_model=LeadState)
async def get_lead(
    lead_state_id: str,
    identity: ResolvedIdentity = Depends(require_permission(LEAD_READ)),
    svc: LeadGenService = Depends(get_leadgen_service),
) -> LeadState:
    lead = await svc.get_lead(lead_state_id)
    if lead is None or lead.org_id != identity.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "lead not found")
    return lead


@router.get("/accounts/{account_id}/contacts", response_model=list[Person])
async def list_account_contacts(
    account_id: str,
    identity: ResolvedIdentity = Depends(require_permission(LEAD_READ)),
    svc: LeadGenService = Depends(get_leadgen_service),
) -> list[Person]:
    try:
        return await svc.list_account_contacts(org_id=identity.org_id, account_id=account_id)
    except LeadGenError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/leads/{lead_state_id}/qualify", response_model=QualificationResult)
async def qualify_lead(
    lead_state_id: str,
    identity: ResolvedIdentity = Depends(require_permission(LEAD_QUALIFY)),
    svc: LeadGenService = Depends(get_leadgen_service),
    ai_classifier: AIClassifier = Depends(get_ai_classifier),
) -> QualificationResult:
    try:
        return await svc.enrich_and_qualify(
            org_id=identity.org_id, actor=identity.user_id, lead_state_id=lead_state_id, ai_classifier=ai_classifier, profile=_DEFAULT_ICP_PROFILE
        )
    except LeadGenError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/leads/{lead_state_id}/assign", response_model=LeadState)
async def assign_lead(
    lead_state_id: str,
    body: AssignRequest,
    identity: ResolvedIdentity = Depends(require_permission(LEAD_ASSIGN)),
    svc: LeadGenService = Depends(get_leadgen_service),
) -> LeadState:
    try:
        return await svc.assign(org_id=identity.org_id, actor=identity.user_id, lead_state_id=lead_state_id, owner=body.owner, team=body.team)
    except LeadGenError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/leads/{lead_state_id}/enroll", response_model=LeadEnrollment)
async def enroll_lead(
    lead_state_id: str,
    body: EnrollRequest,
    identity: ResolvedIdentity = Depends(require_permission(LEAD_ENROLL)),
    svc: LeadGenService = Depends(get_leadgen_service),
) -> LeadEnrollment:
    try:
        return await svc.enroll(org_id=identity.org_id, actor=identity.user_id, lead_state_id=lead_state_id, brand_id=body.brand_id)
    except LeadGenError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/leads/generate")
async def generate_leads(
    body: GenerateLeadsRequest,
    identity: ResolvedIdentity = Depends(require_permission(LEADGEN_AI_GENERATE)),
    svc: LeadGenAIService = Depends(get_leadgen_ai_service),
    gsc: GSCProvider = Depends(get_gsc_provider),
):
    try:
        return await svc.generate_leads(org_id=identity.org_id, actor=identity.user_id, site_url=body.site_url, gsc=gsc, internal_context=body.internal_context)
    except LeadGenAIError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post("/leads/{lead_state_id}/evaluate-icp", response_model=Decision)
async def evaluate_icp(
    lead_state_id: str,
    body: EvaluateIcpRequest,
    identity: ResolvedIdentity = Depends(require_permission(LEADGEN_AI_EVALUATE_ICP)),
    svc: LeadGenAIService = Depends(get_leadgen_ai_service),
) -> Decision:
    try:
        return await svc.evaluate_icp(org_id=identity.org_id, actor=identity.user_id, lead_state_id=lead_state_id, prospect_context=body.prospect_context)
    except LeadGenAIError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except DecisionEngineError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"the model answered but not with a valid decision: {exc}") from exc
    except LLMUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"AI backend unavailable: {exc}") from exc


class AiConvertResponse(BaseModel):
    decision: Decision
    opportunity: Opportunity | None = None


@router.post("/leads/{lead_state_id}/ai/convert", response_model=AiConvertResponse)
async def ai_convert_lead(
    lead_state_id: str,
    identity: ResolvedIdentity = Depends(require_permission(LEADGEN_AI_CONVERT)),
    svc: LeadConversionAIService = Depends(get_lead_conversion_ai_service),
) -> AiConvertResponse:
    try:
        decision, opportunity = await svc.evaluate_and_convert(org_id=identity.org_id, actor=identity.user_id, lead_state_id=lead_state_id)
    except LeadConversionAIError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except DecisionEngineError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"the model answered but not with a valid decision: {exc}") from exc
    except LLMUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"AI backend unavailable: {exc}") from exc
    return AiConvertResponse(decision=decision, opportunity=opportunity)


@router.post("/enrollments/{enrollment_id}/outreach-decide", response_model=Decision)
async def decide_outreach(
    enrollment_id: str,
    body: DecideOutreachRequest,
    identity: ResolvedIdentity = Depends(require_permission(OUTREACH_AI_DECIDE)),
    svc: OutreachAIService = Depends(get_outreach_ai_service),
) -> Decision:
    try:
        return await svc.decide_and_act(org_id=identity.org_id, actor=identity.user_id, enrollment_id=enrollment_id, mailbox_id=body.mailbox_id)
    except OutreachAIError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except DecisionEngineError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"the model answered but not with a valid decision: {exc}") from exc
    except LLMUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"AI backend unavailable: {exc}") from exc
