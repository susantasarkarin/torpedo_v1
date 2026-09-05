"""
HTTP surface for the panel/survey domain. Same discipline as every prior slice's
routers, with one deliberate exception: `POST /surveys/{id}/callback` does **not**
go through `get_current_identity`/`require_permission` at all — it's a signed
external webhook, per endpoint_catalogue.md ("signed webhook" permission column),
not a Torpedo user session. `verify_hmac_signature` (called inside
`CallbackService.handle_callback`, unconditionally, before anything else) is this
endpoint's authentication mechanism; there is no other guard on it, deliberately,
because a real webhook caller cannot present a Torpedo session token.

`StubSurveyProvider` is this slice's `PassthroughAIClassifier`/`StubSendProvider`
equivalent — no real Cint HTTP client exists yet, swappable at one dependency-provider
function.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.dependencies import require_permission
from app.db import get_database
from app.finance.rewards_ledger import RewardLedgerEntry, RewardLedgerService
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.models.money import Money
from app.panel.callback_security import SignatureConfigError, SignatureInvalid
from app.panel.models import Allocation, SURVEY_PROVIDERS, Supplier, Survey, SurveyResponse, SupplierReconciliationRecord, TrafficSource
from app.panel.providers import SurveyProvider, SurveyProviderUnavailable, SurveyProjection
from app.panel.service import AllocationService, CallbackService, SupplierReconciliationService, SupplierService, SurveyError, SurveyService, TrafficSourceService
from app.rbac.identity import ResolvedIdentity
from app.rbac.permissions import SUPPLIER_MANAGE, SURVEY_ALLOCATE, SURVEY_MANAGE, SURVEY_READ, SURVEY_RECONCILE

router = APIRouter()


class StubSurveyProvider:
    async def build_redirect_url(self, *, survey: Survey, respondent_ref: str) -> str:
        return f"https://stub-provider.example/redirect?survey={survey.external_id}&r={respondent_ref}"

    async def refresh(self, *, survey: Survey) -> SurveyProjection:
        return SurveyProjection(quota_remaining=survey.quota_remaining, cpi_minor=survey.cpi.amount_minor, conversion_rate=survey.conversion_rate)


def get_survey_provider() -> SurveyProvider:
    return StubSurveyProvider()


def get_survey_service() -> SurveyService:
    db = get_database()
    return SurveyService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["activities"], Activity))


def get_allocation_service() -> AllocationService:
    db = get_database()
    return AllocationService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["allocations"], Allocation), CanonicalRepository(db["activities"], Activity))


def get_callback_service() -> CallbackService:
    from app.config import get_settings

    db = get_database()
    settings = get_settings()
    return CallbackService(
        CanonicalRepository(db["survey_responses"], SurveyResponse), CanonicalRepository(db["allocations"], Allocation),
        CanonicalRepository(db["activities"], Activity), RewardLedgerService(CanonicalRepository(db["reward_ledger_entries"], RewardLedgerEntry)),
        signing_secret=settings.survey_callback_signing_secret,
    )


def get_supplier_service() -> SupplierService:
    return SupplierService(CanonicalRepository(get_database()["suppliers"], Supplier))


def get_traffic_source_service() -> TrafficSourceService:
    return TrafficSourceService(CanonicalRepository(get_database()["traffic_sources"], TrafficSource))


def get_reconciliation_service() -> SupplierReconciliationService:
    db = get_database()
    return SupplierReconciliationService(CanonicalRepository(db["supplier_reconciliation_records"], SupplierReconciliationRecord), CanonicalRepository(db["survey_responses"], SurveyResponse))


class CreateSurveyRequest(BaseModel):
    provider: str
    external_id: str
    quota_remaining: int
    cpi: Money
    conversion_rate: float


class SetEligibilityRequest(BaseModel):
    is_active_in_pool: bool
    activated_at: str | None = None


class AllocateRequest(BaseModel):
    candidate_survey_ids: list[str]
    person_id: str
    vendor_id: str
    country_code: str
    respondent_ref: str


class CreateSupplierRequest(BaseModel):
    name: str
    provider: str


class CreateTrafficSourceRequest(BaseModel):
    vendor_id: str
    country_code: str
    campaign_ref: str


class ReconcileRequest(BaseModel):
    survey_id: str | None = None
    supplier_reported_count: int


@router.post("/surveys", response_model=Survey)
async def create_survey(body: CreateSurveyRequest, identity: ResolvedIdentity = Depends(require_permission(SURVEY_MANAGE)), svc: SurveyService = Depends(get_survey_service)) -> Survey:
    try:
        return await svc.create_survey(org_id=identity.org_id, actor=identity.user_id, provider=body.provider, external_id=body.external_id, quota_remaining=body.quota_remaining, cpi=body.cpi, conversion_rate=body.conversion_rate)
    except SurveyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/surveys/{survey_id}/metrics", response_model=Survey)
async def get_survey_metrics(survey_id: str, identity: ResolvedIdentity = Depends(require_permission(SURVEY_READ)), svc: SurveyService = Depends(get_survey_service)) -> Survey:
    survey = await svc._surveys.get(survey_id)
    if survey is None or survey.org_id != identity.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "survey not found")
    return survey


@router.post("/surveys/{survey_id}/eligibility", response_model=Survey)
async def set_survey_eligibility(survey_id: str, body: SetEligibilityRequest, identity: ResolvedIdentity = Depends(require_permission(SURVEY_MANAGE)), svc: SurveyService = Depends(get_survey_service)) -> Survey:
    try:
        return await svc.set_eligibility(actor=identity.user_id, survey_id=survey_id, is_active_in_pool=body.is_active_in_pool, activated_at=body.activated_at)
    except SurveyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/traffic/{traffic_source_id}/allocate", response_model=Allocation)
async def allocate(
    traffic_source_id: str,
    body: AllocateRequest,
    identity: ResolvedIdentity = Depends(require_permission(SURVEY_ALLOCATE)),
    svc: AllocationService = Depends(get_allocation_service),
    provider: SurveyProvider = Depends(get_survey_provider),
) -> Allocation:
    try:
        return await svc.allocate(
            org_id=identity.org_id, actor=identity.user_id, candidate_survey_ids=body.candidate_survey_ids,
            person_id=body.person_id, vendor_id=body.vendor_id, country_code=body.country_code,
            respondent_ref=body.respondent_ref, provider=provider,
        )
    except SurveyError as exc:
        # register/catalogue distinguish 409 (quota race lost) from 422 (no eligible
        # survey at all); this slice doesn't yet split SurveyError into subtypes to
        # tell them apart at this layer — a deferred nuance, not a silent gap.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/surveys/{survey_id}/callback")
async def survey_callback(survey_id: str, request: Request, x_signature: str = Header(alias="X-Signature"), svc: CallbackService = Depends(get_callback_service)) -> SurveyResponse:
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid JSON body") from exc

    payout = Money(**payload["payout"]) if payload.get("payout") else None
    try:
        return await svc.handle_callback(
            org_id=payload["org_id"], raw_payload=raw_body, signature_hex=x_signature,
            allocation_id=payload["allocation_id"], provider=payload["provider"],
            external_event_id=payload["external_event_id"], final_status=payload["final_status"],
            payout=payout, reverses_external_event_id=payload.get("reverses_external_event_id"),
        )
    except SignatureConfigError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    except SignatureInvalid as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    except SurveyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/suppliers", response_model=Supplier)
async def create_supplier(body: CreateSupplierRequest, identity: ResolvedIdentity = Depends(require_permission(SUPPLIER_MANAGE)), svc: SupplierService = Depends(get_supplier_service)) -> Supplier:
    try:
        return await svc.create_supplier(org_id=identity.org_id, actor=identity.user_id, name=body.name, provider=body.provider)
    except SurveyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/traffic-sources", response_model=TrafficSource)
async def create_traffic_source(body: CreateTrafficSourceRequest, identity: ResolvedIdentity = Depends(require_permission(SUPPLIER_MANAGE)), svc: TrafficSourceService = Depends(get_traffic_source_service)) -> TrafficSource:
    return await svc.create_traffic_source(org_id=identity.org_id, actor=identity.user_id, vendor_id=body.vendor_id, country_code=body.country_code, campaign_ref=body.campaign_ref)


@router.post("/suppliers/{supplier_id}/reconcile", response_model=SupplierReconciliationRecord)
async def reconcile_supplier(supplier_id: str, body: ReconcileRequest, identity: ResolvedIdentity = Depends(require_permission(SURVEY_RECONCILE)), svc: SupplierReconciliationService = Depends(get_reconciliation_service)) -> SupplierReconciliationRecord:
    return await svc.reconcile(org_id=identity.org_id, actor=identity.user_id, supplier_id=supplier_id, survey_id=body.survey_id, supplier_reported_count=body.supplier_reported_count)
