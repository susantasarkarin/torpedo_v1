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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_identity, require_permission
from app.db import get_database
from app.identity.facet_service import FacetService
from app.identity.facets import AuthIdentity, CustomerBilling, EmployeeRecord, LeadState, PanelistProfile, VendorProfile
from app.identity.models import Account, AccountBrandRelationship, Person
from app.identity.service import IdentityService
from app.leadgen.ai import AIClassificationResult, AIClassifier
from app.leadgen.models import DeadLetterEvent, LeadEnrollment, RawLeadEvent
from app.models.ai_proposal import AiProposal
from app.leadgen.scoring import ICPProfile
from app.leadgen.service import LeadGenError, LeadGenService, QualificationResult
from app.outreach.suppression import Suppression, SuppressionService
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.rbac.identity import ResolvedIdentity
from app.rbac.permissions import LEAD_ASSIGN, LEAD_ENROLL, LEAD_INGEST, LEAD_QUALIFY, LEAD_READ

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


@router.post("/leads/{lead_state_id}/qualify", response_model=QualificationResult)
async def qualify_lead(
    lead_state_id: str,
    identity: ResolvedIdentity = Depends(require_permission(LEAD_QUALIFY)),
    svc: LeadGenService = Depends(get_leadgen_service),
    ai_classifier: AIClassifier = Depends(get_ai_classifier),
) -> QualificationResult:
    try:
        return await svc.enrich_and_qualify(
            actor=identity.user_id, lead_state_id=lead_state_id, ai_classifier=ai_classifier, profile=_DEFAULT_ICP_PROFILE
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
        return await svc.assign(actor=identity.user_id, lead_state_id=lead_state_id, owner=body.owner, team=body.team)
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
        return await svc.enroll(actor=identity.user_id, lead_state_id=lead_state_id, brand_id=body.brand_id)
    except LeadGenError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
