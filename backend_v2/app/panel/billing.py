"""
SurveyBillingService — the economic chain Slice 18 exists to build:

    Survey completion -> billable completion -> client invoice
    Survey completion -> billable completion -> supplier bill
    revenue - supplier cost = contribution margin

**No second accounting system.** Every actual invoice/bill write goes through
Slice 8's unchanged `InvoiceService.create_invoice()`/`BillService.create_bill()`
— this module's job is entirely upstream of that: turning a batch of billable
`SurveyResponse` records into the one line item those calls need
(`quantity=count, unit_price_minor=<rate>`). Nothing here computes a GST-inclusive
total itself; `compute_totals()` (Slice 8) still does that, unchanged.

**Deterministic, not AI.** `record_billable_completion()` marks exactly the
completions that are actually billable (a real `"complete"`, not reversed) and
snapshots the rate at that moment — `survey.cpi`/`survey.client_rate` are real
`Survey` fields set at survey-configuration time, never computed or guessed by
a model. Master-prompt Phase 18's own words: "Do NOT let an LLM calculate the
accounting truth." Nothing in this module imports `app.ai`.

**Idempotent, both ways.** A `SurveyResponse` already marked `billable=True` is
returned unchanged on a second call (never re-costed against a possibly-changed
`Survey.cpi`, which would silently corrupt historical accounting). A response
already carrying a `client_invoice_id`/`supplier_bill_id` is excluded from the
next invoice/bill generation run — the direct guard against billing or costing
the same completion twice.

**Margin is a read, not a write.** `compute_margin()` sums already-recorded
`supplier_cost` and the survey's `client_rate` across billable responses — it
never writes anything, and it's exposed to `app.panel.ai_allocation`'s context
(Slice 19) as one more real signal the model can use to prioritize surveys,
alongside conversion/dropout/category — never as something the model computes
itself.

**One real, honest gap, stated once here**: `Survey.opportunity_id` is the only
linkage from a survey to its commercial client (via `Opportunity.account_id`).
There is no separate `Study` entity, and a `Bill`'s `vendor_account_id` (which
supplier to pay) is not derivable from `Survey`/`Supplier` at all yet — no
`Supplier`↔`Account` linkage exists in the identity spine — so
`generate_supplier_bill()` takes `vendor_account_id` as an explicit parameter
rather than pretending to derive it.
"""

from __future__ import annotations

from app.crm.models import Opportunity
from app.finance.models import Bill, GstDetails, Invoice, LineItem
from app.finance.service import BillService, InvoiceService
from app.models.base import CanonicalRepository
from app.models.money import Money
from app.panel.models import Survey, SurveyResponse


class SurveyBillingError(Exception):
    """Missing survey/response, a response that isn't actually billable, no
    unbilled completions to invoice/bill, or a survey missing the rate/opportunity
    configuration billing requires. Same discipline as every other domain's
    single error type."""


class SurveyBillingService:
    def __init__(
        self, survey_responses: CanonicalRepository[SurveyResponse], surveys: CanonicalRepository[Survey],
        opportunities: CanonicalRepository[Opportunity], invoice_service: InvoiceService, bill_service: BillService,
    ):
        self._responses = survey_responses
        self._surveys = surveys
        self._opportunities = opportunities
        self._invoice_service = invoice_service
        self._bill_service = bill_service

    async def record_billable_completion(self, *, org_id: str, actor: str, survey_response_id: str) -> SurveyResponse:
        response = await self._responses.get(survey_response_id)
        if response is None or response.org_id != org_id:
            raise SurveyBillingError(f"survey response {survey_response_id} does not exist")
        if response.billable:
            return response  # idempotent — never re-costed against a possibly-changed rate
        if response.final_status != "complete":
            raise SurveyBillingError(f"response {survey_response_id} is not a completion (final_status={response.final_status})")

        survey = await self._surveys.get(response.survey_id)
        if survey is None:
            raise SurveyBillingError(f"survey {response.survey_id} no longer exists")

        return await self._responses.update(response.id, response.version, {"billable": True, "supplier_cost": survey.cpi}, updated_by=actor)

    async def generate_client_invoice(self, *, org_id: str, actor: str, survey_id: str, gst_details: GstDetails, currency: str) -> Invoice:
        survey = await self._get_survey(survey_id, org_id=org_id)
        if survey.client_rate is None:
            raise SurveyBillingError(f"survey {survey_id} has no client_rate configured — cannot bill a client for it")
        if survey.opportunity_id is None:
            raise SurveyBillingError(f"survey {survey_id} has no opportunity_id — cannot determine which client account to bill")
        opportunity = await self._opportunities.get(survey.opportunity_id)
        if opportunity is None or opportunity.account_id is None:
            raise SurveyBillingError(f"opportunity {survey.opportunity_id} has no account_id to bill")

        unbilled = await self._responses.find_all({"survey_id": survey_id, "billable": True, "client_invoice_id": None})
        if not unbilled:
            raise SurveyBillingError(f"survey {survey_id} has no unbilled completions")

        count = len(unbilled)
        line_items = [LineItem(description=f"{survey.external_id} — {count} completed interview(s)", quantity=count, unit_price_minor=survey.client_rate.amount_minor, gst_rate_bps=0)]
        invoice = await self._invoice_service.create_invoice(
            org_id=org_id, actor=actor, customer_account_id=opportunity.account_id, line_items=line_items,
            gst_details=gst_details, currency=currency, opportunity_id=survey.opportunity_id,
        )
        for response in unbilled:
            await self._responses.update(response.id, response.version, {"client_invoice_id": invoice.id}, updated_by=actor)
        return invoice

    async def generate_supplier_bill(self, *, org_id: str, actor: str, survey_id: str, vendor_account_id: str, gst_details: GstDetails, currency: str) -> Bill:
        survey = await self._get_survey(survey_id, org_id=org_id)
        unbilled = await self._responses.find_all({"survey_id": survey_id, "billable": True, "supplier_bill_id": None})
        if not unbilled:
            raise SurveyBillingError(f"survey {survey_id} has no uncosted completions")

        count = len(unbilled)
        line_items = [LineItem(description=f"{survey.external_id} — {count} completed interview(s) (supplier cost)", quantity=count, unit_price_minor=survey.cpi.amount_minor, gst_rate_bps=0)]
        bill = await self._bill_service.create_bill(org_id=org_id, actor=actor, vendor_account_id=vendor_account_id, line_items=line_items, gst_details=gst_details, currency=currency)
        for response in unbilled:
            await self._responses.update(response.id, response.version, {"supplier_bill_id": bill.id}, updated_by=actor)
        return bill

    async def compute_margin(self, *, org_id: str, survey_id: str) -> dict:
        """Read-only. `margin_pct` is `None` when revenue is zero (division is
        undefined, not silently reported as 0% or 100%).

        Aggregated via MongoDB, not pulled into Python (Phase 18 performance
        follow-up): only the count and the summed supplier_cost are needed —
        unlike generate_client_invoice()/generate_supplier_bill(), nothing
        here updates the individual SurveyResponse documents, so pulling all
        of them (a number that grows with a study's real completion volume,
        and this margin figure gets checked repeatedly, not once) was
        entirely wasted work."""
        survey = await self._get_survey(survey_id, org_id=org_id)
        pipeline = [
            {"$match": {"survey_id": survey_id, "billable": True, "deleted_at": None}},
            {"$group": {"_id": None, "completions": {"$sum": 1}, "cost_minor": {"$sum": "$supplier_cost.amount_minor"}}},
        ]
        result = await self._responses._collection.aggregate(pipeline).to_list(length=1)
        completions = result[0]["completions"] if result else 0
        cost_minor = (result[0].get("cost_minor") or 0) if result else 0
        revenue_minor = completions * survey.client_rate.amount_minor if survey.client_rate else 0
        margin_minor = revenue_minor - cost_minor
        currency = survey.cpi.currency

        return {
            "completions": completions,
            "revenue": Money(amount_minor=revenue_minor, currency=currency),
            "supplier_cost": Money(amount_minor=cost_minor, currency=currency),
            "contribution_margin": Money(amount_minor=margin_minor, currency=currency),
            "margin_pct": round(margin_minor / revenue_minor * 100, 2) if revenue_minor > 0 else None,
        }

    async def _get_survey(self, survey_id: str, *, org_id: str) -> Survey:
        survey = await self._surveys.get(survey_id)
        if survey is None or survey.org_id != org_id:
            raise SurveyBillingError(f"survey {survey_id} does not exist")
        return survey
