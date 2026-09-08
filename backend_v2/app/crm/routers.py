"""
HTTP surface for the CRM commercial spine. Same discipline as every prior slice:
`org_id` always derives from the resolved identity, every write permission-gated,
404-not-403 on cross-org reads.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import require_permission
from app.crm.models import Opportunity
from app.crm.service import CRMError, OpportunityService
from app.db import get_database
from app.finance.models import GstDetails, Invoice, LineItem
from app.finance.routers import get_invoice_service
from app.finance.service import InvoiceService
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.models.money import Money
from app.rbac.identity import ResolvedIdentity
from app.rbac.permissions import OPPORTUNITY_CONVERT, OPPORTUNITY_CREATE, OPPORTUNITY_READ, OPPORTUNITY_UPDATE

router = APIRouter()


def get_opportunity_service(invoice_service: InvoiceService = Depends(get_invoice_service)) -> OpportunityService:
    db = get_database()
    return OpportunityService(CanonicalRepository(db["opportunities"], Opportunity), CanonicalRepository(db["activities"], Activity), invoice_service)


class CreateOpportunityRequest(BaseModel):
    account_id: str | None = None
    person_id: str | None = None
    amount: Money | None = None
    probability: float | None = None


class UpdateStageRequest(BaseModel):
    stage: str


class CloseLostRequest(BaseModel):
    reason: str


class ConvertRequest(BaseModel):
    line_items: list[LineItem]
    gst_details: GstDetails
    currency: str


@router.post("/opportunities", response_model=Opportunity)
async def create_opportunity(body: CreateOpportunityRequest, identity: ResolvedIdentity = Depends(require_permission(OPPORTUNITY_CREATE)), svc: OpportunityService = Depends(get_opportunity_service)) -> Opportunity:
    return await svc.create_opportunity(org_id=identity.org_id, actor=identity.user_id, account_id=body.account_id, person_id=body.person_id, amount=body.amount, probability=body.probability)


@router.get("/opportunities/{opportunity_id}", response_model=Opportunity)
async def get_opportunity(opportunity_id: str, identity: ResolvedIdentity = Depends(require_permission(OPPORTUNITY_READ)), svc: OpportunityService = Depends(get_opportunity_service)) -> Opportunity:
    opportunity = await svc.get_opportunity(opportunity_id)
    if opportunity is None or opportunity.org_id != identity.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "opportunity not found")
    return opportunity


@router.post("/opportunities/{opportunity_id}/stage", response_model=Opportunity)
async def update_opportunity_stage(opportunity_id: str, body: UpdateStageRequest, identity: ResolvedIdentity = Depends(require_permission(OPPORTUNITY_UPDATE)), svc: OpportunityService = Depends(get_opportunity_service)) -> Opportunity:
    try:
        return await svc.update_stage(org_id=identity.org_id, actor=identity.user_id, opportunity_id=opportunity_id, new_stage=body.stage)
    except CRMError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/opportunities/{opportunity_id}/close-lost", response_model=Opportunity)
async def close_opportunity_lost(opportunity_id: str, body: CloseLostRequest, identity: ResolvedIdentity = Depends(require_permission(OPPORTUNITY_UPDATE)), svc: OpportunityService = Depends(get_opportunity_service)) -> Opportunity:
    try:
        return await svc.close_lost(org_id=identity.org_id, actor=identity.user_id, opportunity_id=opportunity_id, reason=body.reason)
    except CRMError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/opportunities/{opportunity_id}/convert", response_model=Invoice)
async def convert_opportunity(opportunity_id: str, body: ConvertRequest, identity: ResolvedIdentity = Depends(require_permission(OPPORTUNITY_CONVERT)), svc: OpportunityService = Depends(get_opportunity_service)) -> Invoice:
    try:
        return await svc.convert_to_invoice(org_id=identity.org_id, actor=identity.user_id, opportunity_id=opportunity_id, line_items=body.line_items, gst_details=body.gst_details, currency=body.currency)
    except CRMError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
