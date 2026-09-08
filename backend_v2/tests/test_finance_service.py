"""
Slice 8 — Finance. P0/P1 regression coverage named after the register findings each
test proves cannot recur: D-33 (unvalidated payment amount, no reversal), D-11 (no
credit-note instrument, statutory history rewritten in place), D-10 (GST structure),
D-35 (shared payment-number counter collision), D-37 (self-approvable expenses),
D-38 (drifting AR/AP-style scalars), D-26 (plaintext bank data), D-12/D-14 (approval
subsystem finally has real callers, admin wildcard still carved out).
"""

import inspect
from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient
from pydantic import ValidationError

from app.finance.models import BankAccount, Bill, CreditNote, Expense, GstDetails, Invoice, LineItem, Payment, ReconciliationRecord
from app.finance.rewards_ledger import RewardLedgerEntry, RewardLedgerError, RewardLedgerService
from app.finance.sequence import SequenceService
from app.finance.service import (
    EXPENSE_AUTO_APPROVE_CEILING,
    BankAccountService,
    BillService,
    CreditNoteService,
    ExpenseService,
    FinanceError,
    InvoiceService,
    PaymentService,
    ReconciliationService,
)
from app.models.activity import Activity
from app.models.base import CanonicalDocument, CanonicalRepository
from app.models.money import Money
from app.rbac.identity import ResolvedIdentity
from app.rbac.models import ApprovalAuthority
from app.rbac.service import RBACService

ORG = "org-A"
CURRENCY = "INR"

GST = GstDetails(place_of_supply="KA")


def _identity(user_id: str, *, permissions: frozenset[str] = frozenset(), principal_type: str = "user", real_actor_id: str | None = None) -> ResolvedIdentity:
    return ResolvedIdentity(
        user_id=user_id, org_id=ORG, principal_type=principal_type,
        roles=frozenset(), permissions=permissions, real_actor_id=real_actor_id or user_id,
    )


def _line_items(*, unit_price_minor: int = 100_000, quantity: int = 1, gst_rate_bps: int = 1800) -> list[LineItem]:
    return [LineItem(description="widget", quantity=quantity, unit_price_minor=unit_price_minor, gst_rate_bps=gst_rate_bps)]


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def rbac(db) -> RBACService:
    from app.rbac.models import Role, UserRole

    return RBACService(
        user_roles=CanonicalRepository(db["user_roles"], UserRole),
        roles=CanonicalRepository(db["roles"], Role),
        approval_authorities=CanonicalRepository(db["approval_authorities"], ApprovalAuthority),
    )


async def _grant_ceiling(rbac: RBACService, *, user_id: str, entity_type: str, max_amount: Money) -> None:
    await rbac._approval_authorities.insert(
        ApprovalAuthority(org_id=ORG, created_by="seed", updated_by="seed", user_id=user_id, entity_type=entity_type, max_amount=max_amount)
    )


@pytest.fixture
def sequences(db) -> SequenceService:
    return SequenceService(db["finance_sequences"])


@pytest.fixture
def activities(db) -> CanonicalRepository[Activity]:
    return CanonicalRepository(db["activities"], Activity)


@pytest.fixture
def invoice_service(db, sequences, activities) -> InvoiceService:
    return InvoiceService(CanonicalRepository(db["invoices"], Invoice), sequences, activities)


@pytest.fixture
def bill_service(db, sequences, activities) -> BillService:
    return BillService(CanonicalRepository(db["bills"], Bill), sequences, activities)


@pytest.fixture
def payment_service(db, sequences, activities) -> PaymentService:
    return PaymentService(
        CanonicalRepository(db["payments"], Payment), CanonicalRepository(db["invoices"], Invoice),
        CanonicalRepository(db["bills"], Bill), sequences, activities,
    )


@pytest.fixture
def expense_service(db, activities) -> ExpenseService:
    return ExpenseService(CanonicalRepository(db["expenses"], Expense), activities)


@pytest.fixture
def credit_note_service(db, sequences, activities) -> CreditNoteService:
    return CreditNoteService(CanonicalRepository(db["credit_notes"], CreditNote), CanonicalRepository(db["invoices"], Invoice), sequences, activities)


@pytest.fixture
def bank_account_service(db) -> BankAccountService:
    return BankAccountService(CanonicalRepository(db["bank_accounts"], BankAccount))


@pytest.fixture
def reconciliation_service(db) -> ReconciliationService:
    return ReconciliationService(CanonicalRepository(db["reconciliation_records"], ReconciliationRecord), CanonicalRepository(db["payments"], Payment))


@pytest.fixture
def reward_ledger_service(db) -> RewardLedgerService:
    return RewardLedgerService(CanonicalRepository(db["reward_ledger_entries"], RewardLedgerEntry))


async def _sent_invoice(invoice_service: InvoiceService, rbac: RBACService, *, creator="alice", approver="bob", total_minor=118_000) -> Invoice:
    invoice = await invoice_service.create_invoice(org_id=ORG, actor=creator, customer_account_id="cust-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)
    await invoice_service.submit_invoice(org_id=ORG, actor=creator, invoice_id=invoice.id)
    await _grant_ceiling(rbac, user_id=approver, entity_type="finance.invoice", max_amount=Money(amount_minor=total_minor, currency=CURRENCY))
    approver_identity = _identity(approver, permissions=frozenset({"finance.invoice.approve"}))
    await invoice_service.approve_invoice(identity=approver_identity, rbac=rbac, invoice_id=invoice.id)
    return await invoice_service.send_invoice(org_id=ORG, actor=creator, invoice_id=invoice.id)


# --------------------------------------------------------------------------- totals (D-10, no rounding drift)


def test_line_item_totals_computed_server_side_with_gst():
    from app.finance.totals import compute_totals

    items = [
        LineItem(description="a", quantity=2, unit_price_minor=100_000, gst_rate_bps=1800),  # 200000 + 18% = 236000
        LineItem(description="b", quantity=1, unit_price_minor=50_000, gst_rate_bps=0),
    ]
    subtotal, tax_total, total = compute_totals(items, currency=CURRENCY)
    assert subtotal.amount_minor == 250_000
    assert tax_total.amount_minor == 36_000
    assert total.amount_minor == 286_000


def test_gst_details_can_represent_export_and_reverse_charge_distinctly():
    """D-10: v1 could not distinguish zero-rated/export/RCM supplies on the issued
    document at all. Here they're real, independent, queryable fields."""
    export = GstDetails(place_of_supply="KA", is_export=True, lut_number="LUT123")
    rcm = GstDetails(place_of_supply="KA", is_reverse_charge=True)
    assert export.is_export and not export.is_reverse_charge
    assert rcm.is_reverse_charge and not rcm.is_export


# --------------------------------------------------------------------------- invoice lifecycle


@pytest.mark.asyncio
async def test_invoice_lifecycle_draft_to_sent(invoice_service: InvoiceService, rbac: RBACService):
    invoice = await _sent_invoice(invoice_service, rbac)
    assert invoice.status == "sent"
    assert invoice.approved_by == "bob"
    assert invoice.approved_at is not None


@pytest.mark.asyncio
async def test_invoice_approval_blocks_self_approval(invoice_service: InvoiceService, rbac: RBACService):
    """register §5.7 acceptance test #1, applied to finance."""
    invoice = await invoice_service.create_invoice(org_id=ORG, actor="alice", customer_account_id="cust-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)
    await invoice_service.submit_invoice(org_id=ORG, actor="alice", invoice_id=invoice.id)
    await _grant_ceiling(rbac, user_id="alice", entity_type="finance.invoice", max_amount=Money(amount_minor=10_000_000, currency=CURRENCY))

    with pytest.raises(FinanceError):
        await invoice_service.approve_invoice(identity=_identity("alice", permissions=frozenset({"finance.invoice.approve"})), rbac=rbac, invoice_id=invoice.id)


@pytest.mark.asyncio
async def test_invoice_approval_requires_ceiling_covering_the_amount(invoice_service: InvoiceService, rbac: RBACService):
    """register §5.7 acceptance test #2."""
    invoice = await invoice_service.create_invoice(org_id=ORG, actor="alice", customer_account_id="cust-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)
    await invoice_service.submit_invoice(org_id=ORG, actor="alice", invoice_id=invoice.id)
    await _grant_ceiling(rbac, user_id="bob", entity_type="finance.invoice", max_amount=Money(amount_minor=1, currency=CURRENCY))

    with pytest.raises(FinanceError):
        await invoice_service.approve_invoice(identity=_identity("bob", permissions=frozenset({"finance.invoice.approve"})), rbac=rbac, invoice_id=invoice.id)


@pytest.mark.asyncio
async def test_admin_wildcard_does_not_bypass_invoice_approval(invoice_service: InvoiceService, rbac: RBACService):
    """D-14, applied to finance: an admin-wildcard identity still cannot approve —
    the wildcard was never in identity.permissions as `finance.invoice.approve`
    literally, and can_approve() never treats it as satisfying the check."""
    from app.rbac.permissions import ADMIN_WILDCARD

    invoice = await invoice_service.create_invoice(org_id=ORG, actor="alice", customer_account_id="cust-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)
    await invoice_service.submit_invoice(org_id=ORG, actor="alice", invoice_id=invoice.id)
    await _grant_ceiling(rbac, user_id="bob", entity_type="finance.invoice", max_amount=Money(amount_minor=10_000_000, currency=CURRENCY))

    with pytest.raises(FinanceError):
        await invoice_service.approve_invoice(identity=_identity("bob", permissions=frozenset({ADMIN_WILDCARD})), rbac=rbac, invoice_id=invoice.id)


@pytest.mark.asyncio
async def test_invoice_approval_is_idempotent_for_the_same_approver(invoice_service: InvoiceService, rbac: RBACService):
    invoice = await invoice_service.create_invoice(org_id=ORG, actor="alice", customer_account_id="cust-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)
    await invoice_service.submit_invoice(org_id=ORG, actor="alice", invoice_id=invoice.id)
    await _grant_ceiling(rbac, user_id="bob", entity_type="finance.invoice", max_amount=Money(amount_minor=10_000_000, currency=CURRENCY))
    bob = _identity("bob", permissions=frozenset({"finance.invoice.approve"}))

    first = await invoice_service.approve_invoice(identity=bob, rbac=rbac, invoice_id=invoice.id)
    second = await invoice_service.approve_invoice(identity=bob, rbac=rbac, invoice_id=invoice.id)
    assert first.id == second.id == invoice.id
    assert second.status == "approved"


@pytest.mark.asyncio
async def test_invoice_approval_rejects_a_different_second_approver(invoice_service: InvoiceService, rbac: RBACService):
    invoice = await invoice_service.create_invoice(org_id=ORG, actor="alice", customer_account_id="cust-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)
    await invoice_service.submit_invoice(org_id=ORG, actor="alice", invoice_id=invoice.id)
    for approver in ("bob", "carol"):
        await _grant_ceiling(rbac, user_id=approver, entity_type="finance.invoice", max_amount=Money(amount_minor=10_000_000, currency=CURRENCY))

    await invoice_service.approve_invoice(identity=_identity("bob", permissions=frozenset({"finance.invoice.approve"})), rbac=rbac, invoice_id=invoice.id)
    with pytest.raises(FinanceError):
        await invoice_service.approve_invoice(identity=_identity("carol", permissions=frozenset({"finance.invoice.approve"})), rbac=rbac, invoice_id=invoice.id)


@pytest.mark.asyncio
async def test_send_invoice_requires_approved_status(invoice_service: InvoiceService):
    invoice = await invoice_service.create_invoice(org_id=ORG, actor="alice", customer_account_id="cust-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)
    with pytest.raises(FinanceError):
        await invoice_service.send_invoice(org_id=ORG, actor="alice", invoice_id=invoice.id)


# --------------------------------------------------------------------------- payments (D-33)


def test_payment_amount_cannot_be_a_non_numeric_string():
    """D-33: v1's `amount` was raw client JSON `$inc`-ed straight into four fields
    ('abc' passed, negatives passed). Here, Money's type system rejects it before
    any handler runs."""
    with pytest.raises(ValidationError):
        Money(amount_minor="not-a-number", currency=CURRENCY)


@pytest.mark.asyncio
async def test_recording_a_payment_never_mutates_invoice_totals(invoice_service: InvoiceService, payment_service: PaymentService, rbac: RBACService):
    """The direct D-11/D-33 regression: only amount_paid/balance_due/status may
    change when money moves — subtotal/tax_total/total are the statutory record and
    must never be touched by anything other than create_invoice."""
    invoice = await _sent_invoice(invoice_service, rbac)
    original_subtotal, original_tax, original_total = invoice.subtotal, invoice.tax_total, invoice.total

    payment = await payment_service.record_payment(
        org_id=ORG, actor="alice", direction="received", amount=Money(amount_minor=50_000, currency=CURRENCY),
        method="bank_transfer", idempotency_key="pay-1", invoice_id=invoice.id,
    )
    updated_invoice = await invoice_service._invoices.get(invoice.id)

    assert updated_invoice.subtotal == original_subtotal
    assert updated_invoice.tax_total == original_tax
    assert updated_invoice.total == original_total
    assert updated_invoice.amount_paid.amount_minor == 50_000
    assert updated_invoice.balance_due.amount_minor == original_total.amount_minor - 50_000
    assert updated_invoice.status == "partially_paid"
    assert payment.payment_number.startswith("RCV-")


@pytest.mark.asyncio
async def test_full_payment_marks_invoice_paid(invoice_service: InvoiceService, payment_service: PaymentService, rbac: RBACService):
    invoice = await _sent_invoice(invoice_service, rbac)
    await payment_service.record_payment(
        org_id=ORG, actor="alice", direction="received", amount=invoice.total, method="bank_transfer",
        idempotency_key="pay-full", invoice_id=invoice.id,
    )
    updated = await invoice_service._invoices.get(invoice.id)
    assert updated.status == "paid"
    assert updated.balance_due.amount_minor == 0


@pytest.mark.asyncio
async def test_payment_before_invoice_sent_is_rejected(invoice_service: InvoiceService, payment_service: PaymentService):
    invoice = await invoice_service.create_invoice(org_id=ORG, actor="alice", customer_account_id="cust-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)
    with pytest.raises(FinanceError):
        await payment_service.record_payment(
            org_id=ORG, actor="alice", direction="received", amount=Money(amount_minor=1000, currency=CURRENCY),
            method="cash", idempotency_key="k1", invoice_id=invoice.id,
        )


@pytest.mark.asyncio
async def test_overpayment_rejected_unless_explicitly_allowed(invoice_service: InvoiceService, payment_service: PaymentService, rbac: RBACService):
    """'unvalidated overpayment' (P1 list) — must be refused by default, allowed
    only via an explicit, separately-named flag."""
    invoice = await _sent_invoice(invoice_service, rbac)
    over_amount = Money(amount_minor=invoice.total.amount_minor + 1, currency=CURRENCY)

    with pytest.raises(FinanceError):
        await payment_service.record_payment(org_id=ORG, actor="alice", direction="received", amount=over_amount, method="cash", idempotency_key="k1", invoice_id=invoice.id)

    payment = await payment_service.record_payment(
        org_id=ORG, actor="alice", direction="received", amount=over_amount, method="cash",
        idempotency_key="k2", invoice_id=invoice.id, allow_overpayment=True,
    )
    assert payment.amount.amount_minor == over_amount.amount_minor


@pytest.mark.asyncio
async def test_payment_currency_mismatch_rejected(invoice_service: InvoiceService, payment_service: PaymentService, rbac: RBACService):
    invoice = await _sent_invoice(invoice_service, rbac)
    with pytest.raises(FinanceError):
        await payment_service.record_payment(
            org_id=ORG, actor="alice", direction="received", amount=Money(amount_minor=1000, currency="USD"),
            method="cash", idempotency_key="k1", invoice_id=invoice.id,
        )


@pytest.mark.asyncio
async def test_payer_account_mismatch_rejected(invoice_service: InvoiceService, payment_service: PaymentService, rbac: RBACService):
    """endpoint_catalogue.md: 'validates invoice_id's account matches the payment's
    declared payer — closing the payment-applied-to-any-invoice defect'."""
    invoice = await _sent_invoice(invoice_service, rbac)
    with pytest.raises(FinanceError):
        await payment_service.record_payment(
            org_id=ORG, actor="alice", direction="received", amount=Money(amount_minor=1000, currency=CURRENCY),
            method="cash", idempotency_key="k1", invoice_id=invoice.id, payer_account_id="someone-else",
        )


@pytest.mark.asyncio
async def test_payment_idempotent_replay_does_not_double_apply(invoice_service: InvoiceService, payment_service: PaymentService, rbac: RBACService):
    invoice = await _sent_invoice(invoice_service, rbac)
    first = await payment_service.record_payment(org_id=ORG, actor="alice", direction="received", amount=Money(amount_minor=1000, currency=CURRENCY), method="cash", idempotency_key="same-key", invoice_id=invoice.id)
    second = await payment_service.record_payment(org_id=ORG, actor="alice", direction="received", amount=Money(amount_minor=1000, currency=CURRENCY), method="cash", idempotency_key="same-key", invoice_id=invoice.id)

    assert first.id == second.id
    updated = await invoice_service._invoices.get(invoice.id)
    assert updated.amount_paid.amount_minor == 1000  # not 2000


@pytest.mark.asyncio
async def test_payment_numbers_never_collide_across_directions(invoice_service: InvoiceService, bill_service: BillService, payment_service: PaymentService, rbac: RBACService, db):
    """D-35: v1's RCV-/PAY- sequences shared one counter and interleaved/collided.
    Each direction must advance independently."""
    invoice = await _sent_invoice(invoice_service, rbac)
    bill = await bill_service.create_bill(org_id=ORG, actor="alice", vendor_account_id="vendor-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)
    await bill_service.submit_bill(org_id=ORG, actor="alice", bill_id=bill.id)
    await _grant_ceiling(rbac, user_id="bob", entity_type="finance.bill", max_amount=Money(amount_minor=10_000_000, currency=CURRENCY))
    bill = await bill_service.approve_bill(identity=_identity("bob", permissions=frozenset({"finance.bill.approve"})), rbac=rbac, bill_id=bill.id)

    p1 = await payment_service.record_payment(org_id=ORG, actor="alice", direction="received", amount=Money(amount_minor=1000, currency=CURRENCY), method="cash", idempotency_key="r1", invoice_id=invoice.id)
    p2 = await payment_service.record_payment(org_id=ORG, actor="alice", direction="made", amount=Money(amount_minor=1000, currency=CURRENCY), method="cash", idempotency_key="m1", bill_id=bill.id)
    p3 = await payment_service.record_payment(org_id=ORG, actor="alice", direction="received", amount=Money(amount_minor=1000, currency=CURRENCY), method="cash", idempotency_key="r2", invoice_id=invoice.id)

    assert p1.payment_number == "RCV-000001"
    assert p2.payment_number == "PAY-000001"
    assert p3.payment_number == "RCV-000002"


@pytest.mark.asyncio
async def test_reverse_payment_restores_balance_and_status(invoice_service: InvoiceService, payment_service: PaymentService, rbac: RBACService):
    """'no delete or void endpoint for payments at all... permanent' — a real,
    auditable reversal path now exists."""
    invoice = await _sent_invoice(invoice_service, rbac)
    payment = await payment_service.record_payment(org_id=ORG, actor="alice", direction="received", amount=invoice.total, method="cash", idempotency_key="k1", invoice_id=invoice.id)
    paid_invoice = await invoice_service._invoices.get(invoice.id)
    assert paid_invoice.status == "paid"

    await _grant_ceiling(rbac, user_id="carol", entity_type="finance.payment", max_amount=Money(amount_minor=10_000_000, currency=CURRENCY))
    reversed_payment = await payment_service.reverse_payment(identity=_identity("carol", permissions=frozenset({"finance.payment.approve"})), rbac=rbac, payment_id=payment.id)

    assert reversed_payment.status == "reversed"
    restored_invoice = await invoice_service._invoices.get(invoice.id)
    assert restored_invoice.status == "sent"
    assert restored_invoice.balance_due.amount_minor == invoice.total.amount_minor
    assert restored_invoice.amount_paid.amount_minor == 0


@pytest.mark.asyncio
async def test_reverse_payment_blocks_self_approval(invoice_service: InvoiceService, payment_service: PaymentService, rbac: RBACService):
    invoice = await _sent_invoice(invoice_service, rbac)
    payment = await payment_service.record_payment(org_id=ORG, actor="alice", direction="received", amount=Money(amount_minor=1000, currency=CURRENCY), method="cash", idempotency_key="k1", invoice_id=invoice.id)
    await _grant_ceiling(rbac, user_id="alice", entity_type="finance.payment", max_amount=Money(amount_minor=10_000_000, currency=CURRENCY))

    with pytest.raises(FinanceError):
        await payment_service.reverse_payment(identity=_identity("alice", permissions=frozenset({"finance.payment.approve"})), rbac=rbac, payment_id=payment.id)


@pytest.mark.asyncio
async def test_double_reversal_rejected(invoice_service: InvoiceService, payment_service: PaymentService, rbac: RBACService):
    invoice = await _sent_invoice(invoice_service, rbac)
    payment = await payment_service.record_payment(org_id=ORG, actor="alice", direction="received", amount=Money(amount_minor=1000, currency=CURRENCY), method="cash", idempotency_key="k1", invoice_id=invoice.id)
    await _grant_ceiling(rbac, user_id="carol", entity_type="finance.payment", max_amount=Money(amount_minor=10_000_000, currency=CURRENCY))
    carol = _identity("carol", permissions=frozenset({"finance.payment.approve"}))

    await payment_service.reverse_payment(identity=carol, rbac=rbac, payment_id=payment.id)
    with pytest.raises(FinanceError):
        await payment_service.reverse_payment(identity=carol, rbac=rbac, payment_id=payment.id)


# --------------------------------------------------------------------------- expenses (D-37)


def test_expense_service_never_accepts_approval_status_from_a_caller():
    """Structural guard, not just behavioral: D-37 was 'approval_status derived from
    requires_approval, and any client can flip requires_approval to self-approve.'
    Here, no caller of create_expense can pass either field at all — it isn't a
    parameter, so there's no boolean left to omit or flip."""
    params = set(inspect.signature(ExpenseService.create_expense).parameters)
    assert "approval_status" not in params
    assert "requires_approval" not in params


@pytest.mark.asyncio
async def test_expense_under_ceiling_is_auto_approved(expense_service: ExpenseService):
    small = Money(amount_minor=EXPENSE_AUTO_APPROVE_CEILING.amount_minor - 1, currency="INR")
    expense = await expense_service.create_expense(org_id=ORG, actor="alice", payee_account_id="vendor-1", category="travel", amount=small)
    assert expense.approval_status == "approved"
    assert expense.requires_approval is False


@pytest.mark.asyncio
async def test_expense_over_ceiling_requires_manual_approval(expense_service: ExpenseService, rbac: RBACService):
    large = Money(amount_minor=EXPENSE_AUTO_APPROVE_CEILING.amount_minor + 1, currency="INR")
    expense = await expense_service.create_expense(org_id=ORG, actor="alice", payee_account_id="vendor-1", category="travel", amount=large)
    assert expense.approval_status == "pending"

    await _grant_ceiling(rbac, user_id="bob", entity_type="finance.expense", max_amount=Money(amount_minor=10_000_000, currency="INR"))
    approved = await expense_service.approve_expense(identity=_identity("bob", permissions=frozenset({"finance.expense.approve"})), rbac=rbac, expense_id=expense.id)
    assert approved.approval_status == "approved"
    assert approved.approved_by == "bob"


@pytest.mark.asyncio
async def test_expense_approval_blocks_self_approval(expense_service: ExpenseService, rbac: RBACService):
    large = Money(amount_minor=EXPENSE_AUTO_APPROVE_CEILING.amount_minor + 1, currency="INR")
    expense = await expense_service.create_expense(org_id=ORG, actor="alice", payee_account_id="vendor-1", category="travel", amount=large)
    await _grant_ceiling(rbac, user_id="alice", entity_type="finance.expense", max_amount=Money(amount_minor=10_000_000, currency="INR"))

    with pytest.raises(FinanceError):
        await expense_service.approve_expense(identity=_identity("alice", permissions=frozenset({"finance.expense.approve"})), rbac=rbac, expense_id=expense.id)


@pytest.mark.asyncio
async def test_expense_reject_transitions_out_of_pending(expense_service: ExpenseService, rbac: RBACService):
    large = Money(amount_minor=EXPENSE_AUTO_APPROVE_CEILING.amount_minor + 1, currency="INR")
    expense = await expense_service.create_expense(org_id=ORG, actor="alice", payee_account_id="vendor-1", category="travel", amount=large)
    await _grant_ceiling(rbac, user_id="bob", entity_type="finance.expense", max_amount=Money(amount_minor=10_000_000, currency="INR"))

    rejected = await expense_service.reject_expense(identity=_identity("bob", permissions=frozenset({"finance.expense.approve"})), rbac=rbac, expense_id=expense.id)
    assert rejected.approval_status == "rejected"


# --------------------------------------------------------------------------- credit notes (D-11)


@pytest.mark.asyncio
async def test_credit_note_issuance_requires_sufficient_ceiling(invoice_service: InvoiceService, credit_note_service: CreditNoteService, rbac: RBACService):
    invoice = await _sent_invoice(invoice_service, rbac)
    await _grant_ceiling(rbac, user_id="dana", entity_type="finance.creditnote", max_amount=Money(amount_minor=1, currency=CURRENCY))

    with pytest.raises(FinanceError):
        await credit_note_service.issue_credit_note(
            org_id=ORG, identity=_identity("dana", permissions=frozenset({"finance.creditnote.create"})), rbac=rbac,
            invoice_id=invoice.id, amount=Money(amount_minor=10_000, currency=CURRENCY), reason="pricing error",
        )


@pytest.mark.asyncio
async def test_credit_note_cannot_exceed_invoice_total(invoice_service: InvoiceService, credit_note_service: CreditNoteService, rbac: RBACService):
    invoice = await _sent_invoice(invoice_service, rbac)
    await _grant_ceiling(rbac, user_id="dana", entity_type="finance.creditnote", max_amount=Money(amount_minor=10_000_000, currency=CURRENCY))

    with pytest.raises(FinanceError):
        await credit_note_service.issue_credit_note(
            org_id=ORG, identity=_identity("dana", permissions=frozenset({"finance.creditnote.create"})), rbac=rbac,
            invoice_id=invoice.id, amount=Money(amount_minor=invoice.total.amount_minor + 1, currency=CURRENCY), reason="too much",
        )


@pytest.mark.asyncio
async def test_apply_credit_note_reduces_balance_but_never_touches_totals(invoice_service: InvoiceService, credit_note_service: CreditNoteService, rbac: RBACService):
    """The direct D-11 regression: a correction is a new instrument, never a rewrite
    of the invoice's statutory total/subtotal/tax_total."""
    invoice = await _sent_invoice(invoice_service, rbac)
    await _grant_ceiling(rbac, user_id="dana", entity_type="finance.creditnote", max_amount=Money(amount_minor=10_000_000, currency=CURRENCY))
    note = await credit_note_service.issue_credit_note(
        org_id=ORG, identity=_identity("dana", permissions=frozenset({"finance.creditnote.create"})), rbac=rbac,
        invoice_id=invoice.id, amount=Money(amount_minor=10_000, currency=CURRENCY), reason="pricing error",
    )

    applied = await credit_note_service.apply_credit_note(org_id=ORG, actor="dana", credit_note_id=note.id)
    updated_invoice = await invoice_service._invoices.get(invoice.id)

    assert applied.status == "applied"
    assert updated_invoice.balance_due.amount_minor == invoice.balance_due.amount_minor - 10_000
    assert updated_invoice.total == invoice.total  # never rewritten
    assert updated_invoice.subtotal == invoice.subtotal
    assert updated_invoice.tax_total == invoice.tax_total


@pytest.mark.asyncio
async def test_apply_credit_note_twice_rejected(invoice_service: InvoiceService, credit_note_service: CreditNoteService, rbac: RBACService):
    invoice = await _sent_invoice(invoice_service, rbac)
    await _grant_ceiling(rbac, user_id="dana", entity_type="finance.creditnote", max_amount=Money(amount_minor=10_000_000, currency=CURRENCY))
    note = await credit_note_service.issue_credit_note(
        org_id=ORG, identity=_identity("dana", permissions=frozenset({"finance.creditnote.create"})), rbac=rbac,
        invoice_id=invoice.id, amount=Money(amount_minor=10_000, currency=CURRENCY), reason="pricing error",
    )
    await credit_note_service.apply_credit_note(org_id=ORG, actor="dana", credit_note_id=note.id)
    with pytest.raises(FinanceError):
        await credit_note_service.apply_credit_note(org_id=ORG, actor="dana", credit_note_id=note.id)


# --------------------------------------------------------------------------- bank accounts (D-26)


def test_bank_account_model_has_no_field_that_could_hold_a_secret():
    own_fields = set(BankAccount.model_fields.keys()) - set(CanonicalDocument.model_fields.keys())
    assert own_fields == {"owner_type", "owner_id", "account_holder_name", "bank_name", "account_details_ref", "is_active"}
    for field_name in own_fields:
        for forbidden in ("account_number", "iban", "swift_secret", "pin", "cvv"):
            assert forbidden not in field_name


@pytest.mark.asyncio
async def test_bank_account_stores_only_a_reference(bank_account_service: BankAccountService):
    account = await bank_account_service.add_bank_account(
        org_id=ORG, actor="alice", owner_type="vendor", owner_id="vendor-1",
        account_holder_name="Acme Vendor", bank_name="Test Bank", account_details_ref="secretstore://ref/abc123",
    )
    assert account.account_details_ref == "secretstore://ref/abc123"


# --------------------------------------------------------------------------- reconciliation


@pytest.mark.asyncio
async def test_reconciliation_match_requires_amount_equality(invoice_service: InvoiceService, payment_service: PaymentService, reconciliation_service: ReconciliationService, rbac: RBACService):
    invoice = await _sent_invoice(invoice_service, rbac)
    payment = await payment_service.record_payment(org_id=ORG, actor="alice", direction="received", amount=Money(amount_minor=1000, currency=CURRENCY), method="cash", idempotency_key="k1", invoice_id=invoice.id)
    record = await reconciliation_service.record_external_entry(org_id=ORG, actor="alice", source="bank_statement", external_reference="stmt-1", amount=Money(amount_minor=999, currency=CURRENCY))

    with pytest.raises(FinanceError):
        await reconciliation_service.match(org_id=ORG, actor="alice", record_id=record.id, payment_id=payment.id)


@pytest.mark.asyncio
async def test_reconciliation_match_succeeds_and_is_not_repeatable(invoice_service: InvoiceService, payment_service: PaymentService, reconciliation_service: ReconciliationService, rbac: RBACService):
    invoice = await _sent_invoice(invoice_service, rbac)
    payment = await payment_service.record_payment(org_id=ORG, actor="alice", direction="received", amount=Money(amount_minor=1000, currency=CURRENCY), method="cash", idempotency_key="k1", invoice_id=invoice.id)
    record = await reconciliation_service.record_external_entry(org_id=ORG, actor="alice", source="bank_statement", external_reference="stmt-1", amount=Money(amount_minor=1000, currency=CURRENCY))

    matched = await reconciliation_service.match(org_id=ORG, actor="alice", record_id=record.id, payment_id=payment.id)
    assert matched.status == "matched"
    with pytest.raises(FinanceError):
        await reconciliation_service.match(org_id=ORG, actor="alice", record_id=record.id, payment_id=payment.id)


# --------------------------------------------------------------------------- reward ledger boundary (D-12)


def test_reward_ledger_entry_has_no_stored_balance_field():
    """Balance must always be derived — a stored balance_after field would be
    exactly the kind of drifting scalar D-38 already proved goes wrong."""
    assert "balance_after" not in RewardLedgerEntry.model_fields
    assert "balance" not in RewardLedgerEntry.model_fields


@pytest.mark.asyncio
async def test_reward_balance_is_derived_from_entries(reward_ledger_service: RewardLedgerService):
    await reward_ledger_service.credit(org_id=ORG, actor="system", panelist_person_id="p1", amount=Money(amount_minor=500, currency=CURRENCY), reference_type="survey_completion", reference_id="sr-1")
    await reward_ledger_service.credit(org_id=ORG, actor="system", panelist_person_id="p1", amount=Money(amount_minor=300, currency=CURRENCY), reference_type="survey_completion", reference_id="sr-2")
    await reward_ledger_service.debit(org_id=ORG, actor="system", panelist_person_id="p1", amount=Money(amount_minor=200, currency=CURRENCY), reference_type="redemption", reference_id="r-1")

    balance = await reward_ledger_service.get_balance("p1", currency=CURRENCY)
    assert balance.amount_minor == 600


@pytest.mark.asyncio
async def test_reward_debit_rejected_when_insufficient_balance(reward_ledger_service: RewardLedgerService):
    await reward_ledger_service.credit(org_id=ORG, actor="system", panelist_person_id="p1", amount=Money(amount_minor=100, currency=CURRENCY), reference_type="survey_completion", reference_id="sr-1")
    with pytest.raises(RewardLedgerError):
        await reward_ledger_service.debit(org_id=ORG, actor="system", panelist_person_id="p1", amount=Money(amount_minor=101, currency=CURRENCY), reference_type="redemption", reference_id="r-1")


@pytest.mark.asyncio
async def test_reward_clawback_is_the_missing_d12_write_path(reward_ledger_service: RewardLedgerService, rbac: RBACService):
    """D-12: 'supplier reversal never reaches the reward ledger — panelist keeps
    points on a reversed complete.' This is that path, built and callable."""
    await reward_ledger_service.credit(org_id=ORG, actor="system", panelist_person_id="p1", amount=Money(amount_minor=500, currency=CURRENCY), reference_type="survey_completion", reference_id="sr-1")
    await _grant_ceiling(rbac, user_id="ops-lead", entity_type="rewards.clawback", max_amount=Money(amount_minor=10_000_000, currency=CURRENCY))

    await reward_ledger_service.clawback(
        org_id=ORG, actor="ops-lead", identity=_identity("ops-lead", permissions=frozenset({"rewards.clawback.approve"})), rbac=rbac,
        panelist_person_id="p1", amount=Money(amount_minor=500, currency=CURRENCY),
        reference_type="payment_reversal", reference_id="pay-1", creator_id="system",
    )
    balance = await reward_ledger_service.get_balance("p1", currency=CURRENCY)
    assert balance.amount_minor == 0


@pytest.mark.asyncio
async def test_reward_clawback_blocks_self_approval_no_exception(reward_ledger_service: RewardLedgerService, rbac: RBACService):
    """register §5.7: clawback always requires approval, no exception."""
    await reward_ledger_service.credit(org_id=ORG, actor="system", panelist_person_id="p1", amount=Money(amount_minor=500, currency=CURRENCY), reference_type="survey_completion", reference_id="sr-1")
    await _grant_ceiling(rbac, user_id="ops-lead", entity_type="rewards.clawback", max_amount=Money(amount_minor=10_000_000, currency=CURRENCY))

    with pytest.raises(RewardLedgerError):
        await reward_ledger_service.clawback(
            org_id=ORG, actor="ops-lead", identity=_identity("ops-lead", permissions=frozenset({"rewards.clawback.approve"})), rbac=rbac,
            panelist_person_id="p1", amount=Money(amount_minor=500, currency=CURRENCY),
            reference_type="payment_reversal", reference_id="pay-1", creator_id="ops-lead",
        )


# --------------------------------------------------------------------------- tenant isolation (Phase 15 security audit)


@pytest.mark.asyncio
async def test_submit_invoice_cannot_cross_org_boundaries(invoice_service: InvoiceService):
    """Phase 15 audit finding: every id-scoped write in this module resolved its
    entity via CanonicalRepository.get(id) alone, with no check that it belonged
    to the caller's org — the same class of bug fixed in
    app.governance.approvals.ApprovalService.review(). A cross-org invoice_id
    must be indistinguishable from a missing one, and must never be mutated."""
    other_orgs_invoice = await invoice_service.create_invoice(org_id="org-B", actor="mallory", customer_account_id="cust-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)

    with pytest.raises(FinanceError):
        await invoice_service.submit_invoice(org_id=ORG, actor="mallory", invoice_id=other_orgs_invoice.id)

    untouched = await invoice_service._invoices.get(other_orgs_invoice.id)
    assert untouched.status == "draft"


@pytest.mark.asyncio
async def test_reverse_payment_cannot_cross_org_boundaries(payment_service: PaymentService, invoice_service: InvoiceService, rbac: RBACService):
    other_orgs_invoice = await invoice_service.create_invoice(org_id="org-B", actor="system", customer_account_id="cust-1", line_items=_line_items(), gst_details=GST, currency=CURRENCY)
    await invoice_service.submit_invoice(org_id="org-B", actor="system", invoice_id=other_orgs_invoice.id)
    updated = await invoice_service._invoices.get(other_orgs_invoice.id)
    await invoice_service._invoices.update(updated.id, updated.version, {"status": "sent"}, updated_by="system")

    payment = await payment_service.record_payment(
        org_id="org-B", actor="system", direction="received", amount=other_orgs_invoice.total, method="bank_transfer",
        idempotency_key="k-other-org", invoice_id=other_orgs_invoice.id,
    )

    with pytest.raises(FinanceError):
        await payment_service.reverse_payment(identity=_identity("mallory", permissions=frozenset({"finance.payment.reverse"}), real_actor_id="mallory"), rbac=rbac, payment_id=payment.id)

    untouched = await payment_service._payments.get(payment.id)
    assert untouched.status != "reversed"
