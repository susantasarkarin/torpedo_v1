"""
OpportunityService — the CRM commercial spine, and the first slice to compose across
a domain boundary that was only ever an integration point on paper until now:
endpoint_catalogue.md's `POST /opportunities/{id}/convert` ("Creates a `draft`
`Invoice` referencing the opportunity — never an already-`sent` document") is real
here, calling `app.finance.service.InvoiceService` directly rather than restating
invoice-creation logic a second time (I-1).

**Every write terminates here or in `InvoiceService`** — same architectural gate as
every prior slice. `convert_to_invoice()` is a one-time action, not idempotent
replay: `Opportunity.converted_invoice_id` is set exactly once, and a second call
raises rather than silently returning the first invoice again, because a caller
asking to convert an opportunity that's already been billed is a real mistake to
surface, not a retry to absorb.
"""

from __future__ import annotations

from app.crm.models import LOST, Opportunity, WON, is_valid_transition
from app.finance.models import GstDetails, Invoice, LineItem
from app.finance.service import InvoiceService
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.models.money import Money


class CRMError(Exception):
    """Invalid stage transition, missing parent, or an opportunity not eligible for
    the requested action. Same discipline as FinanceError/OutreachError/LeadGenError."""


class OpportunityService:
    def __init__(self, opportunities: CanonicalRepository[Opportunity], activities: CanonicalRepository[Activity], invoices: InvoiceService):
        self._opportunities = opportunities
        self._activities = activities
        self._invoices = invoices

    async def create_opportunity(
        self, *, org_id: str, actor: str, account_id: str | None = None, person_id: str | None = None,
        amount: Money | None = None, probability: float | None = None,
    ) -> Opportunity:
        opportunity = await self._opportunities.insert(
            Opportunity(org_id=org_id, created_by=actor, updated_by=actor, account_id=account_id, person_id=person_id, amount=amount, probability=probability)
        )
        await self._activity(org_id=org_id, actor=actor, type="opportunity_created", subject_id=opportunity.id, payload={"stage": opportunity.stage})
        return opportunity

    async def update_stage(self, *, org_id: str, actor: str, opportunity_id: str, new_stage: str) -> Opportunity:
        """For any transition except `lost` — `close_lost()` is the only way to
        reach `lost`, because that transition requires a reason and this one
        doesn't accept one."""
        if new_stage == LOST:
            raise CRMError("closing an opportunity as lost requires a reason — call close_lost() instead")
        opportunity = await self._get_or_raise(opportunity_id, org_id=org_id)
        if not is_valid_transition(opportunity.stage, new_stage):
            raise CRMError(f"opportunity {opportunity_id} cannot move from {opportunity.stage!r} to {new_stage!r}")

        updated = await self._opportunities.update(opportunity.id, opportunity.version, {"stage": new_stage}, updated_by=actor)
        await self._activity(org_id=opportunity.org_id, actor=actor, type="opportunity_stage_changed", subject_id=opportunity.id, payload={"from": opportunity.stage, "to": new_stage})
        return updated

    async def close_lost(self, *, org_id: str, actor: str, opportunity_id: str, reason: str) -> Opportunity:
        opportunity = await self._get_or_raise(opportunity_id, org_id=org_id)
        if not is_valid_transition(opportunity.stage, LOST):
            raise CRMError(f"opportunity {opportunity_id} cannot be closed lost from stage {opportunity.stage!r}")

        updated = await self._opportunities.update(opportunity.id, opportunity.version, {"stage": LOST, "loss_reason": reason}, updated_by=actor)
        await self._activity(org_id=opportunity.org_id, actor=actor, type="opportunity_lost", subject_id=opportunity.id, payload={"reason": reason})
        return updated

    async def convert_to_invoice(
        self, *, org_id: str, actor: str, opportunity_id: str, line_items: list[LineItem], gst_details: GstDetails, currency: str
    ) -> Invoice:
        opportunity = await self._get_or_raise(opportunity_id, org_id=org_id)
        if opportunity.stage != WON:
            raise CRMError(f"opportunity {opportunity_id} must be won to convert to an invoice (stage={opportunity.stage})")
        if opportunity.converted_invoice_id is not None:
            raise CRMError(f"opportunity {opportunity_id} was already converted to invoice {opportunity.converted_invoice_id}")
        if opportunity.account_id is None:
            raise CRMError(f"opportunity {opportunity_id} has no account_id to bill")

        invoice = await self._invoices.create_invoice(
            org_id=opportunity.org_id, actor=actor, customer_account_id=opportunity.account_id,
            line_items=line_items, gst_details=gst_details, currency=currency, opportunity_id=opportunity.id,
        )
        await self._opportunities.update(opportunity.id, opportunity.version, {"converted_invoice_id": invoice.id}, updated_by=actor)
        await self._activity(org_id=opportunity.org_id, actor=actor, type="opportunity_converted", subject_id=opportunity.id, payload={"invoice_id": invoice.id})
        return invoice

    async def get_opportunity(self, opportunity_id: str) -> Opportunity | None:
        return await self._opportunities.get(opportunity_id)

    async def _get_or_raise(self, opportunity_id: str, *, org_id: str) -> Opportunity:
        opportunity = await self._opportunities.get(opportunity_id)
        if opportunity is None or opportunity.org_id != org_id:
            raise CRMError(f"opportunity {opportunity_id} does not exist")
        return opportunity

    async def _activity(self, *, org_id: str, actor: str, type: str, subject_id: str, payload: dict) -> None:
        await self._activities.insert(
            Activity(org_id=org_id, created_by=actor, updated_by=actor, type=type, subject_type="opportunity", subject_id=subject_id, actor_type="user", actor_id=actor, payload=payload)
        )
