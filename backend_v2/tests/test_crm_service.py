"""
Slice 10 — CRM commercial spine (Opportunity). Built directly against
schema_catalogue.md §2.2's locked shape and endpoint_catalogue.md's
`POST /opportunities/{id}/convert` deep-dive rather than reinvented.
"""

from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient
from pydantic import ValidationError

from app.crm.models import LOST, NEGOTIATION, NEW, PROPOSAL, QUALIFIED, RFQ, WON, ALL_STAGES, Opportunity, is_valid_transition
from app.crm.service import CRMError, OpportunityService
from app.finance.models import GstDetails, Invoice, LineItem
from app.finance.sequence import SequenceService
from app.finance.service import InvoiceService
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.models.money import Money

ORG = "org-A"
CURRENCY = "INR"
GST = GstDetails(place_of_supply="KA")


def _line_items() -> list[LineItem]:
    return [LineItem(description="research project", quantity=1, unit_price_minor=500_000, gst_rate_bps=1800)]


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def invoice_service(db) -> InvoiceService:
    return InvoiceService(CanonicalRepository(db["invoices"], Invoice), SequenceService(db["finance_sequences"]), CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def opportunity_service(db, invoice_service) -> OpportunityService:
    return OpportunityService(CanonicalRepository(db["opportunities"], Opportunity), CanonicalRepository(db["activities"], Activity), invoice_service)


# --------------------------------------------------------------------------- stage machine (unit-level, no db)


def test_stage_enum_is_closed():
    assert set(ALL_STAGES) == {"new", "rfq", "qualified", "proposal", "negotiation", "won", "lost"}


def test_terminal_stages_accept_no_further_transitions():
    for terminal in (WON, LOST):
        for target in ALL_STAGES:
            assert is_valid_transition(terminal, target) is False


def test_active_stages_can_move_between_each_other_and_close():
    assert is_valid_transition(NEW, RFQ) is True
    assert is_valid_transition(RFQ, QUALIFIED) is True
    assert is_valid_transition(QUALIFIED, NEW) is True  # backward movement allowed — a cooled deal is real
    assert is_valid_transition(NEGOTIATION, WON) is True
    assert is_valid_transition(NEW, LOST) is True
    assert is_valid_transition(NEW, NEW) is False  # not a transition


# --------------------------------------------------------------------------- model validation


def test_probability_outside_unit_interval_is_rejected():
    with pytest.raises(ValidationError):
        Opportunity(org_id=ORG, created_by="alice", updated_by="alice", probability=1.5)
    with pytest.raises(ValidationError):
        Opportunity(org_id=ORG, created_by="alice", updated_by="alice", probability=-0.1)


# --------------------------------------------------------------------------- service behavior


@pytest.mark.asyncio
async def test_create_opportunity_defaults_to_new_stage(opportunity_service: OpportunityService):
    opportunity = await opportunity_service.create_opportunity(org_id=ORG, actor="alice", account_id="acct-1", person_id="person-1")
    assert opportunity.stage == NEW
    assert opportunity.converted_invoice_id is None


@pytest.mark.asyncio
async def test_valid_stage_progression_through_the_pipeline(opportunity_service: OpportunityService):
    opportunity = await opportunity_service.create_opportunity(org_id=ORG, actor="alice", account_id="acct-1")
    for target in (RFQ, QUALIFIED, PROPOSAL, NEGOTIATION):
        opportunity = await opportunity_service.update_stage(actor="alice", opportunity_id=opportunity.id, new_stage=target)
        assert opportunity.stage == target


@pytest.mark.asyncio
async def test_direct_update_stage_to_lost_is_rejected(opportunity_service: OpportunityService):
    """close_lost() is the only path to `lost` — it requires a reason update_stage
    doesn't accept."""
    opportunity = await opportunity_service.create_opportunity(org_id=ORG, actor="alice", account_id="acct-1")
    with pytest.raises(CRMError):
        await opportunity_service.update_stage(actor="alice", opportunity_id=opportunity.id, new_stage=LOST)


@pytest.mark.asyncio
async def test_close_lost_sets_reason_and_is_terminal(opportunity_service: OpportunityService):
    opportunity = await opportunity_service.create_opportunity(org_id=ORG, actor="alice", account_id="acct-1")
    closed = await opportunity_service.close_lost(actor="alice", opportunity_id=opportunity.id, reason="budget cut")
    assert closed.stage == LOST
    assert closed.loss_reason == "budget cut"

    with pytest.raises(CRMError):
        await opportunity_service.update_stage(actor="alice", opportunity_id=closed.id, new_stage=NEW)
    with pytest.raises(CRMError):
        await opportunity_service.close_lost(actor="alice", opportunity_id=closed.id, reason="again")


@pytest.mark.asyncio
async def test_won_opportunity_accepts_no_further_stage_changes(opportunity_service: OpportunityService):
    opportunity = await opportunity_service.create_opportunity(org_id=ORG, actor="alice", account_id="acct-1")
    won = await opportunity_service.update_stage(actor="alice", opportunity_id=opportunity.id, new_stage=WON)
    with pytest.raises(CRMError):
        await opportunity_service.update_stage(actor="alice", opportunity_id=won.id, new_stage=NEGOTIATION)


# --------------------------------------------------------------------------- convert_to_invoice (the real cross-domain integration)


@pytest.mark.asyncio
async def test_convert_requires_won_stage(opportunity_service: OpportunityService):
    opportunity = await opportunity_service.create_opportunity(org_id=ORG, actor="alice", account_id="acct-1")
    with pytest.raises(CRMError):
        await opportunity_service.convert_to_invoice(actor="alice", opportunity_id=opportunity.id, line_items=_line_items(), gst_details=GST, currency=CURRENCY)


@pytest.mark.asyncio
async def test_convert_requires_an_account_to_bill(opportunity_service: OpportunityService):
    opportunity = await opportunity_service.create_opportunity(org_id=ORG, actor="alice", account_id=None)
    won = await opportunity_service.update_stage(actor="alice", opportunity_id=opportunity.id, new_stage=WON)
    with pytest.raises(CRMError):
        await opportunity_service.convert_to_invoice(actor="alice", opportunity_id=won.id, line_items=_line_items(), gst_details=GST, currency=CURRENCY)


@pytest.mark.asyncio
async def test_convert_creates_a_draft_invoice_referencing_the_opportunity(opportunity_service: OpportunityService, db):
    """The direct endpoint_catalogue.md regression: 'Creates a draft Invoice
    referencing the opportunity — never an already-sent document.'"""
    opportunity = await opportunity_service.create_opportunity(org_id=ORG, actor="alice", account_id="acct-1")
    won = await opportunity_service.update_stage(actor="alice", opportunity_id=opportunity.id, new_stage=WON)

    invoice = await opportunity_service.convert_to_invoice(actor="alice", opportunity_id=won.id, line_items=_line_items(), gst_details=GST, currency=CURRENCY)

    assert invoice.status == "draft"
    assert invoice.opportunity_id == won.id
    assert invoice.customer_account_id == "acct-1"

    updated_opportunity = await opportunity_service.get_opportunity(won.id)
    assert updated_opportunity.converted_invoice_id == invoice.id


@pytest.mark.asyncio
async def test_convert_is_not_repeatable(opportunity_service: OpportunityService):
    opportunity = await opportunity_service.create_opportunity(org_id=ORG, actor="alice", account_id="acct-1")
    won = await opportunity_service.update_stage(actor="alice", opportunity_id=opportunity.id, new_stage=WON)
    await opportunity_service.convert_to_invoice(actor="alice", opportunity_id=won.id, line_items=_line_items(), gst_details=GST, currency=CURRENCY)

    with pytest.raises(CRMError):
        await opportunity_service.convert_to_invoice(actor="alice", opportunity_id=won.id, line_items=_line_items(), gst_details=GST, currency=CURRENCY)


@pytest.mark.asyncio
async def test_every_stage_transition_and_conversion_records_exactly_one_activity(opportunity_service: OpportunityService, db):
    opportunity = await opportunity_service.create_opportunity(org_id=ORG, actor="alice", account_id="acct-1")
    won = await opportunity_service.update_stage(actor="alice", opportunity_id=opportunity.id, new_stage=WON)
    await opportunity_service.convert_to_invoice(actor="alice", opportunity_id=won.id, line_items=_line_items(), gst_details=GST, currency=CURRENCY)

    activities = await CanonicalRepository(db["activities"], Activity).find_all({"subject_id": opportunity.id})
    types = [a.type for a in activities]
    assert types == ["opportunity_created", "opportunity_stage_changed", "opportunity_converted"]
