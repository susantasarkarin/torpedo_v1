"""
Finance domain services — one class per entity, sharing one error type and the same
"server derives, client never asserts" discipline throughout. Every write terminates
here or in `SequenceService`/`RewardLedgerService`; no `db["..."]` appears anywhere
in this package outside `routers.py`'s provider functions (same architectural gate
as `app.leadgen`/`app.outreach`).

**Two different approval checks are used deliberately, not interchangeably**:

- `RBACService.can_approve()` — the two-actor, self-approval-blocked check (register
  §5.7) — gates `InvoiceService.approve_invoice`, `BillService.approve_bill`,
  `PaymentService.reverse_payment`, `ExpenseService.approve_expense`: each of these
  has a distinct creator and a distinct approver, and the creator must never be able
  to approve their own submission.
- `RBACService.get_approval_ceiling()` — the single-actor "does this identity hold
  authority up to this amount" check, with no creator/approver split — gates
  `CreditNoteService.issue_credit_note()`. The endpoint catalogue marks credit-note
  creation itself `[APPROVAL-GATED]` with no separate submit/approve lifecycle (D-11
  is "no credit-note instrument at all," not "no two-person credit-note workflow");
  the person issuing it must simply already hold sufficient authority, checked at
  the moment of issuance.

**Invoice/Bill immutability**: neither service exposes any method that can change
`line_items`/`subtotal`/`tax_total`/`total` once created — those fields are set once,
in `create_invoice`/`create_bill`, from `compute_totals()`, and never written again by
anything in this file. `record_payment`/`reverse_payment`/`apply_credit_note` only
ever touch `amount_paid`/`balance_due`/`status` — the direct structural fix for D-11
("statutory history is corrected by rewriting it in place").
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.finance.models import Bill, BankAccount, CreditNote, Expense, GstDetails, Invoice, LineItem, Payment, ReconciliationRecord
from app.finance.sequence import SequenceService
from app.finance.totals import compute_totals
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.models.money import Money
from app.rbac.identity import ResolvedIdentity
from app.rbac.service import RBACService

# Placeholder auto-approve ceiling for expenses — no configurable-per-org ceiling
# entity exists yet (same deferred-config pattern as app.leadgen.routers's
# _DEFAULT_ICP_PROFILE). An expense at or under this amount never needs a second
# approver; above it, approval_status starts "pending" and only approve_expense()
# (approval-gated) can move it.
EXPENSE_AUTO_APPROVE_CEILING = Money(amount_minor=500_000, currency="INR")


class FinanceError(Exception):
    """Invalid state transition, validation failure, or approval denial. Same
    discipline as LeadGenError/OutreachError — one error type per domain."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InvoiceService:
    def __init__(self, invoices: CanonicalRepository[Invoice], sequences: SequenceService, activities: CanonicalRepository[Activity]):
        self._invoices = invoices
        self._sequences = sequences
        self._activities = activities

    async def create_invoice(
        self, *, org_id: str, actor: str, customer_account_id: str, line_items: list[LineItem], gst_details: GstDetails, currency: str,
        opportunity_id: str | None = None, due_at: datetime | None = None,
    ) -> Invoice:
        subtotal, tax_total, total = compute_totals(line_items, currency=currency)
        seq = await self._sequences.next(org_id=org_id, sequence_name="INV")
        invoice = await self._invoices.insert(
            Invoice(
                org_id=org_id, created_by=actor, updated_by=actor,
                customer_account_id=customer_account_id, opportunity_id=opportunity_id, invoice_number=f"INV-{seq:06d}",
                line_items=line_items, gst_details=gst_details,
                subtotal=subtotal, tax_total=tax_total, total=total,
                amount_paid=Money(amount_minor=0, currency=currency), balance_due=total, due_at=due_at,
            )
        )
        await self._activity(org_id=org_id, actor=actor, type="invoice_created", subject_id=invoice.id, payload={"total_minor": total.amount_minor})
        return invoice

    async def list_open(self, *, org_id: str) -> list[Invoice]:
        """The deterministic candidate set for AR follow-up and payment matching
        (Slice 17) — an invoice not in `sent`/`partially_paid` has no balance an
        AI-driven decision could meaningfully act on."""
        return await self._invoices.find_all({"org_id": org_id, "status": {"$in": ["sent", "partially_paid"]}})

    async def submit_invoice(self, *, actor: str, invoice_id: str) -> Invoice:
        invoice = await self._get_or_raise(invoice_id)
        if invoice.status != "draft":
            raise FinanceError(f"invoice {invoice_id} must be draft to submit (status={invoice.status})")
        updated = await self._invoices.update(invoice.id, invoice.version, {"status": "pending_approval"}, updated_by=actor)
        await self._activity(org_id=invoice.org_id, actor=actor, type="invoice_submitted", subject_id=invoice.id, payload={})
        return updated

    async def approve_invoice(self, *, identity: ResolvedIdentity, rbac: RBACService, invoice_id: str) -> Invoice:
        invoice = await self._get_or_raise(invoice_id)
        if invoice.status == "approved":
            if invoice.approved_by != identity.user_id:
                raise FinanceError("already approved by a different approver")
            return invoice  # idempotent no-op, per endpoint_catalogue.md
        if invoice.status != "pending_approval":
            raise FinanceError(f"invoice {invoice_id} must be pending_approval to approve (status={invoice.status})")

        allowed = await rbac.can_approve(identity, entity_type="finance.invoice", amount=invoice.total, creator_id=invoice.created_by)
        if not allowed:
            raise FinanceError("approval denied: self-approval, wrong principal type, or ceiling exceeded")

        updated = await self._invoices.update(
            invoice.id, invoice.version,
            {"status": "approved", "approved_by": identity.user_id, "approved_at": _utcnow()},
            updated_by=identity.user_id,
        )
        await self._activity(org_id=invoice.org_id, actor=identity.user_id, type="invoice_approved", subject_id=invoice.id, payload={"total_minor": invoice.total.amount_minor})
        return updated

    async def send_invoice(self, *, actor: str, invoice_id: str) -> Invoice:
        invoice = await self._get_or_raise(invoice_id)
        if invoice.status != "approved":
            raise FinanceError(f"invoice {invoice_id} must be approved to send (status={invoice.status})")
        updated = await self._invoices.update(invoice.id, invoice.version, {"status": "sent"}, updated_by=actor)
        await self._activity(org_id=invoice.org_id, actor=actor, type="invoice_sent", subject_id=invoice.id, payload={})
        return updated

    async def void_invoice(self, *, actor: str, invoice_id: str) -> Invoice:
        invoice = await self._get_or_raise(invoice_id)
        if invoice.status not in ("draft", "pending_approval"):
            raise FinanceError(f"invoice {invoice_id} can only be voided before it is approved (status={invoice.status})")
        updated = await self._invoices.update(invoice.id, invoice.version, {"status": "void"}, updated_by=actor)
        await self._activity(org_id=invoice.org_id, actor=actor, type="invoice_voided", subject_id=invoice.id, payload={})
        return updated

    async def _get_or_raise(self, invoice_id: str) -> Invoice:
        invoice = await self._invoices.get(invoice_id)
        if invoice is None:
            raise FinanceError(f"invoice {invoice_id} does not exist")
        return invoice

    async def _activity(self, *, org_id: str, actor: str, type: str, subject_id: str, payload: dict) -> None:
        await self._activities.insert(
            Activity(org_id=org_id, created_by=actor, updated_by=actor, type=type, subject_type="invoice", subject_id=subject_id, actor_type="user", actor_id=actor, payload=payload)
        )


class BillService:
    def __init__(self, bills: CanonicalRepository[Bill], sequences: SequenceService, activities: CanonicalRepository[Activity]):
        self._bills = bills
        self._sequences = sequences
        self._activities = activities

    async def create_bill(
        self, *, org_id: str, actor: str, vendor_account_id: str, line_items: list[LineItem], gst_details: GstDetails, currency: str,
        due_at: datetime | None = None,
    ) -> Bill:
        subtotal, tax_total, total = compute_totals(line_items, currency=currency)
        seq = await self._sequences.next(org_id=org_id, sequence_name="BILL")
        bill = await self._bills.insert(
            Bill(
                org_id=org_id, created_by=actor, updated_by=actor,
                vendor_account_id=vendor_account_id, bill_number=f"BILL-{seq:06d}",
                line_items=line_items, gst_details=gst_details,
                subtotal=subtotal, tax_total=tax_total, total=total,
                amount_paid=Money(amount_minor=0, currency=currency), balance_due=total, due_at=due_at,
            )
        )
        await self._activity(org_id=org_id, actor=actor, type="bill_created", subject_id=bill.id, payload={"total_minor": total.amount_minor})
        return bill

    async def list_open(self, *, org_id: str) -> list[Bill]:
        """The deterministic candidate set for AP follow-up (Slice 17)."""
        return await self._bills.find_all({"org_id": org_id, "status": {"$in": ["approved", "partially_paid"]}})

    async def submit_bill(self, *, actor: str, bill_id: str) -> Bill:
        bill = await self._get_or_raise(bill_id)
        if bill.status != "draft":
            raise FinanceError(f"bill {bill_id} must be draft to submit (status={bill.status})")
        updated = await self._bills.update(bill.id, bill.version, {"status": "pending_approval"}, updated_by=actor)
        await self._activity(org_id=bill.org_id, actor=actor, type="bill_submitted", subject_id=bill.id, payload={})
        return updated

    async def approve_bill(self, *, identity: ResolvedIdentity, rbac: RBACService, bill_id: str) -> Bill:
        bill = await self._get_or_raise(bill_id)
        if bill.status == "approved":
            if bill.approved_by != identity.user_id:
                raise FinanceError("already approved by a different approver")
            return bill
        if bill.status != "pending_approval":
            raise FinanceError(f"bill {bill_id} must be pending_approval to approve (status={bill.status})")

        allowed = await rbac.can_approve(identity, entity_type="finance.bill", amount=bill.total, creator_id=bill.created_by)
        if not allowed:
            raise FinanceError("approval denied: self-approval, wrong principal type, or ceiling exceeded")

        updated = await self._bills.update(
            bill.id, bill.version,
            {"status": "approved", "approved_by": identity.user_id, "approved_at": _utcnow()},
            updated_by=identity.user_id,
        )
        await self._activity(org_id=bill.org_id, actor=identity.user_id, type="bill_approved", subject_id=bill.id, payload={"total_minor": bill.total.amount_minor})
        return updated

    async def _get_or_raise(self, bill_id: str) -> Bill:
        bill = await self._bills.get(bill_id)
        if bill is None:
            raise FinanceError(f"bill {bill_id} does not exist")
        return bill

    async def _activity(self, *, org_id: str, actor: str, type: str, subject_id: str, payload: dict) -> None:
        await self._activities.insert(
            Activity(org_id=org_id, created_by=actor, updated_by=actor, type=type, subject_type="bill", subject_id=subject_id, actor_type="user", actor_id=actor, payload=payload)
        )


class PaymentService:
    """`record_payment` targets exactly one Invoice or one Bill (never both) — the
    endpoint catalogue's `applied_to[]` multi-invoice split-payment shape is
    deliberately deferred, not silently missing (a real gap, stated once here)."""

    def __init__(
        self,
        payments: CanonicalRepository[Payment],
        invoices: CanonicalRepository[Invoice],
        bills: CanonicalRepository[Bill],
        sequences: SequenceService,
        activities: CanonicalRepository[Activity],
    ):
        self._payments = payments
        self._invoices = invoices
        self._bills = bills
        self._sequences = sequences
        self._activities = activities

    async def record_payment(
        self,
        *,
        org_id: str,
        actor: str,
        direction: str,
        amount: Money,
        method: str,
        idempotency_key: str,
        invoice_id: str | None = None,
        bill_id: str | None = None,
        payer_account_id: str | None = None,
        allow_overpayment: bool = False,
    ) -> Payment:
        existing = await self._payments.find_one({"org_id": org_id, "idempotency_key": idempotency_key})
        if existing:
            return existing

        if amount.amount_minor <= 0:
            raise FinanceError("payment amount must be positive")
        if bool(invoice_id) == bool(bill_id):
            raise FinanceError("record_payment requires exactly one of invoice_id or bill_id")

        if invoice_id:
            target_repo, target = self._invoices, await self._invoices.get(invoice_id)
            if target is None:
                raise FinanceError(f"invoice {invoice_id} does not exist")
            if target.status not in ("sent", "partially_paid"):
                raise FinanceError(f"invoice {invoice_id} must be sent before payments can be recorded (status={target.status})")
            if payer_account_id and payer_account_id != target.customer_account_id:
                raise FinanceError("payer_account_id does not match the invoice's customer_account_id")
        else:
            target_repo, target = self._bills, await self._bills.get(bill_id)
            if target is None:
                raise FinanceError(f"bill {bill_id} does not exist")
            if target.status not in ("approved", "partially_paid"):
                raise FinanceError(f"bill {bill_id} must be approved before payments can be recorded (status={target.status})")

        if target.balance_due.currency != amount.currency:
            raise FinanceError("payment currency does not match the target document's currency")

        new_balance_minor = target.balance_due.amount_minor - amount.amount_minor
        if new_balance_minor < 0 and not allow_overpayment:
            raise FinanceError(f"payment of {amount.amount_minor} exceeds balance due {target.balance_due.amount_minor}")

        new_paid = Money(amount_minor=target.amount_paid.amount_minor + amount.amount_minor, currency=amount.currency)
        new_balance = Money(amount_minor=new_balance_minor, currency=amount.currency)
        new_status = "paid" if new_balance_minor <= 0 else "partially_paid"

        await target_repo.update(
            target.id, target.version,
            {"amount_paid": new_paid, "balance_due": new_balance, "status": new_status},
            updated_by=actor,
        )

        seq_name = "RCV" if direction == "received" else "PAY"
        seq = await self._sequences.next(org_id=org_id, sequence_name=seq_name)
        payment = await self._payments.insert(
            Payment(
                org_id=org_id, created_by=actor, updated_by=actor,
                direction=direction, invoice_id=invoice_id, bill_id=bill_id, payer_account_id=payer_account_id,
                payment_number=f"{seq_name}-{seq:06d}", amount=amount, method=method, idempotency_key=idempotency_key,
            )
        )
        await self._activity(org_id=org_id, actor=actor, type="payment_recorded", subject_id=payment.id, payload={"amount_minor": amount.amount_minor, "direction": direction})
        return payment

    async def reverse_payment(self, *, identity: ResolvedIdentity, rbac: RBACService, payment_id: str) -> Payment:
        payment = await self._payments.get(payment_id)
        if payment is None:
            raise FinanceError(f"payment {payment_id} does not exist")
        if payment.status == "reversed":
            raise FinanceError(f"payment {payment_id} is already reversed")

        allowed = await rbac.can_approve(identity, entity_type="finance.payment", amount=payment.amount, creator_id=payment.created_by)
        if not allowed:
            raise FinanceError("reversal denied: self-approval, wrong principal type, or ceiling exceeded")

        target_repo = self._invoices if payment.invoice_id else self._bills
        target_id = payment.invoice_id or payment.bill_id
        target = await target_repo.get(target_id)
        if target is None:
            raise FinanceError(f"{'invoice' if payment.invoice_id else 'bill'} {target_id} no longer exists")

        new_paid_minor = target.amount_paid.amount_minor - payment.amount.amount_minor
        new_balance_minor = target.balance_due.amount_minor + payment.amount.amount_minor
        base_status = "sent" if payment.invoice_id else "approved"
        new_status = "paid" if new_balance_minor <= 0 else (base_status if new_paid_minor <= 0 else "partially_paid")

        await target_repo.update(
            target.id, target.version,
            {
                "amount_paid": Money(amount_minor=new_paid_minor, currency=payment.amount.currency),
                "balance_due": Money(amount_minor=new_balance_minor, currency=payment.amount.currency),
                "status": new_status,
            },
            updated_by=identity.user_id,
        )

        reversed_payment = await self._payments.update(payment.id, payment.version, {"status": "reversed"}, updated_by=identity.user_id)
        await self._activity(org_id=payment.org_id, actor=identity.user_id, type="payment_reversed", subject_id=payment.id, payload={"amount_minor": payment.amount.amount_minor})
        return reversed_payment

    async def _activity(self, *, org_id: str, actor: str, type: str, subject_id: str, payload: dict) -> None:
        await self._activities.insert(
            Activity(org_id=org_id, created_by=actor, updated_by=actor, type=type, subject_type="payment", subject_id=subject_id, actor_type="user", actor_id=actor, payload=payload)
        )


class ExpenseService:
    def __init__(self, expenses: CanonicalRepository[Expense], activities: CanonicalRepository[Activity]):
        self._expenses = expenses
        self._activities = activities

    async def create_expense(self, *, org_id: str, actor: str, payee_account_id: str, category: str, amount: Money) -> Expense:
        auto_approved = (
            amount.currency == EXPENSE_AUTO_APPROVE_CEILING.currency
            and amount.amount_minor <= EXPENSE_AUTO_APPROVE_CEILING.amount_minor
        )
        expense = await self._expenses.insert(
            Expense(
                org_id=org_id, created_by=actor, updated_by=actor,
                payee_account_id=payee_account_id, category=category, amount=amount,
                requires_approval=not auto_approved,
                approval_status="approved" if auto_approved else "pending",
                approved_by=actor if auto_approved else None,
            )
        )
        await self._activity(org_id=org_id, actor=actor, type="expense_created", subject_id=expense.id, payload={"auto_approved": auto_approved})
        return expense

    async def approve_expense(self, *, identity: ResolvedIdentity, rbac: RBACService, expense_id: str) -> Expense:
        expense = await self._get_or_raise(expense_id)
        if expense.approval_status != "pending":
            raise FinanceError(f"expense {expense_id} is not pending approval (status={expense.approval_status})")

        allowed = await rbac.can_approve(identity, entity_type="finance.expense", amount=expense.amount, creator_id=expense.created_by)
        if not allowed:
            raise FinanceError("approval denied: self-approval, wrong principal type, or ceiling exceeded")

        updated = await self._expenses.update(expense.id, expense.version, {"approval_status": "approved", "approved_by": identity.user_id}, updated_by=identity.user_id)
        await self._activity(org_id=expense.org_id, actor=identity.user_id, type="expense_approved", subject_id=expense.id, payload={})
        return updated

    async def reject_expense(self, *, identity: ResolvedIdentity, rbac: RBACService, expense_id: str) -> Expense:
        expense = await self._get_or_raise(expense_id)
        if expense.approval_status != "pending":
            raise FinanceError(f"expense {expense_id} is not pending approval (status={expense.approval_status})")

        allowed = await rbac.can_approve(identity, entity_type="finance.expense", amount=expense.amount, creator_id=expense.created_by)
        if not allowed:
            raise FinanceError("rejection denied: self-approval, wrong principal type, or ceiling exceeded")

        updated = await self._expenses.update(expense.id, expense.version, {"approval_status": "rejected", "approved_by": identity.user_id}, updated_by=identity.user_id)
        await self._activity(org_id=expense.org_id, actor=identity.user_id, type="expense_rejected", subject_id=expense.id, payload={})
        return updated

    async def _get_or_raise(self, expense_id: str) -> Expense:
        expense = await self._expenses.get(expense_id)
        if expense is None:
            raise FinanceError(f"expense {expense_id} does not exist")
        return expense

    async def _activity(self, *, org_id: str, actor: str, type: str, subject_id: str, payload: dict) -> None:
        await self._activities.insert(
            Activity(org_id=org_id, created_by=actor, updated_by=actor, type=type, subject_type="expense", subject_id=subject_id, actor_type="user", actor_id=actor, payload=payload)
        )


class CreditNoteService:
    def __init__(
        self,
        credit_notes: CanonicalRepository[CreditNote],
        invoices: CanonicalRepository[Invoice],
        sequences: SequenceService,
        activities: CanonicalRepository[Activity],
    ):
        self._credit_notes = credit_notes
        self._invoices = invoices
        self._sequences = sequences
        self._activities = activities

    async def issue_credit_note(self, *, org_id: str, identity: ResolvedIdentity, rbac: RBACService, invoice_id: str, amount: Money, reason: str) -> CreditNote:
        invoice = await self._invoices.get(invoice_id)
        if invoice is None:
            raise FinanceError(f"invoice {invoice_id} does not exist")
        if amount.currency != invoice.total.currency:
            raise FinanceError("credit note currency does not match the invoice's currency")
        if amount.amount_minor > invoice.total.amount_minor:
            raise FinanceError("credit note cannot exceed the invoice total")

        ceiling = await rbac.get_approval_ceiling(identity, "finance.creditnote")
        if ceiling is None or ceiling.currency != amount.currency or amount.amount_minor > ceiling.amount_minor:
            raise FinanceError("credit note denied: issuer lacks sufficient approval ceiling")

        seq = await self._sequences.next(org_id=org_id, sequence_name="CN")
        note = await self._credit_notes.insert(
            CreditNote(
                org_id=org_id, created_by=identity.user_id, updated_by=identity.user_id,
                invoice_id=invoice_id, credit_note_number=f"CN-{seq:06d}", amount=amount, reason=reason, issued_by=identity.user_id,
            )
        )
        await self._activity(org_id=org_id, actor=identity.user_id, type="credit_note_issued", subject_id=note.id, payload={"amount_minor": amount.amount_minor})
        return note

    async def apply_credit_note(self, *, actor: str, credit_note_id: str) -> CreditNote:
        note = await self._get_or_raise(credit_note_id)
        if note.status == "applied":
            raise FinanceError(f"credit note {credit_note_id} is already applied")

        invoice = await self._invoices.get(note.invoice_id)
        if invoice is None:
            raise FinanceError(f"invoice {note.invoice_id} no longer exists")

        new_balance_minor = invoice.balance_due.amount_minor - note.amount.amount_minor
        new_status = "paid" if new_balance_minor <= 0 else invoice.status
        await self._invoices.update(
            invoice.id, invoice.version,
            {"balance_due": Money(amount_minor=new_balance_minor, currency=invoice.balance_due.currency), "status": new_status},
            updated_by=actor,
        )

        applied = await self._credit_notes.update(note.id, note.version, {"status": "applied"}, updated_by=actor)
        await self._activity(org_id=note.org_id, actor=actor, type="credit_note_applied", subject_id=note.id, payload={})
        return applied

    async def _get_or_raise(self, credit_note_id: str) -> CreditNote:
        note = await self._credit_notes.get(credit_note_id)
        if note is None:
            raise FinanceError(f"credit note {credit_note_id} does not exist")
        return note

    async def _activity(self, *, org_id: str, actor: str, type: str, subject_id: str, payload: dict) -> None:
        await self._activities.insert(
            Activity(org_id=org_id, created_by=actor, updated_by=actor, type=type, subject_type="credit_note", subject_id=subject_id, actor_type="user", actor_id=actor, payload=payload)
        )


class BankAccountService:
    def __init__(self, bank_accounts: CanonicalRepository[BankAccount]):
        self._bank_accounts = bank_accounts

    async def add_bank_account(
        self, *, org_id: str, actor: str, owner_type: str, owner_id: str, account_holder_name: str, bank_name: str, account_details_ref: str
    ) -> BankAccount:
        return await self._bank_accounts.insert(
            BankAccount(
                org_id=org_id, created_by=actor, updated_by=actor,
                owner_type=owner_type, owner_id=owner_id, account_holder_name=account_holder_name,
                bank_name=bank_name, account_details_ref=account_details_ref,
            )
        )


class ReconciliationService:
    def __init__(self, records: CanonicalRepository[ReconciliationRecord], payments: CanonicalRepository[Payment]):
        self._records = records
        self._payments = payments

    async def record_external_entry(self, *, org_id: str, actor: str, source: str, external_reference: str, amount: Money) -> ReconciliationRecord:
        return await self._records.insert(
            ReconciliationRecord(org_id=org_id, created_by=actor, updated_by=actor, source=source, external_reference=external_reference, amount=amount)
        )

    async def match(self, *, actor: str, record_id: str, payment_id: str) -> ReconciliationRecord:
        record = await self._records.get(record_id)
        if record is None:
            raise FinanceError(f"reconciliation record {record_id} does not exist")
        if record.status == "matched":
            raise FinanceError(f"reconciliation record {record_id} is already matched")

        payment = await self._payments.get(payment_id)
        if payment is None:
            raise FinanceError(f"payment {payment_id} does not exist")
        if payment.amount.amount_minor != record.amount.amount_minor or payment.amount.currency != record.amount.currency:
            raise FinanceError("reconciliation amount does not match the payment amount")

        return await self._records.update(record.id, record.version, {"status": "matched", "payment_id": payment_id}, updated_by=actor)
