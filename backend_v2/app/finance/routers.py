"""
HTTP surface for finance. Same discipline as `app.leadgen.routers`/`app.outreach.routers`:
`org_id` always derives from the resolved identity, every write permission-gated,
approval decisions made only inside the service layer (never re-implemented here).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.ai.decision_engine import Decision, DecisionEngine
from app.ai.llm import get_llm_provider
from app.ai.tools import ToolRegistry
from app.auth.dependencies import get_current_identity, get_rbac_service, require_permission
from app.db import get_database
from app.finance.ai_finance import AIFinanceError, AIFinanceService
from app.finance.analytics import FinanceAnalyticsService
from app.finance.models import Bill, BankAccount, CreditNote, Expense, GstDetails, Invoice, LineItem, Payment, ReconciliationRecord
from app.finance.rewards_ledger import RewardLedgerEntry, RewardLedgerError, RewardLedgerService
from app.finance.sequence import SequenceService
from app.finance.service import BankAccountService, BillService, CreditNoteService, ExpenseService, FinanceError, InvoiceService, PaymentService, ReconciliationService
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.models.money import Money
from app.rbac.identity import ResolvedIdentity
from app.rbac.permissions import (
    BANKACCOUNT_MANAGE,
    BILL_CREATE,
    BILL_SUBMIT,
    CREDITNOTE_APPLY,
    CREDITNOTE_CREATE,
    EXPENSE_CREATE,
    FINANCE_AI_AP,
    FINANCE_AI_AR,
    FINANCE_AI_MATCH,
    FINANCE_ANALYTICS_READ,
    FINANCE_READ,
    INVOICE_CREATE,
    INVOICE_SEND,
    INVOICE_SUBMIT,
    PAYMENT_CREATE,
    PAYMENT_REVERSE,
    RECONCILIATION_MANAGE,
    REWARDS_CREDIT,
    REWARDS_DEBIT,
    REWARDS_READ,
)
from app.rbac.service import RBACService

router = APIRouter()


def get_sequence_service() -> SequenceService:
    return SequenceService(get_database()["finance_sequences"])


def get_invoice_service() -> InvoiceService:
    db = get_database()
    return InvoiceService(CanonicalRepository(db["invoices"], Invoice), get_sequence_service(), CanonicalRepository(db["activities"], Activity))


def get_bill_service() -> BillService:
    db = get_database()
    return BillService(CanonicalRepository(db["bills"], Bill), get_sequence_service(), CanonicalRepository(db["activities"], Activity))


def get_finance_analytics_service() -> FinanceAnalyticsService:
    db = get_database()
    return FinanceAnalyticsService(CanonicalRepository(db["invoices"], Invoice), CanonicalRepository(db["bills"], Bill))


def get_payment_service() -> PaymentService:
    db = get_database()
    return PaymentService(
        CanonicalRepository(db["payments"], Payment), CanonicalRepository(db["invoices"], Invoice), CanonicalRepository(db["bills"], Bill),
        get_sequence_service(), CanonicalRepository(db["activities"], Activity),
    )


def get_expense_service() -> ExpenseService:
    db = get_database()
    return ExpenseService(CanonicalRepository(db["expenses"], Expense), CanonicalRepository(db["activities"], Activity))


def get_credit_note_service() -> CreditNoteService:
    db = get_database()
    return CreditNoteService(CanonicalRepository(db["credit_notes"], CreditNote), CanonicalRepository(db["invoices"], Invoice), get_sequence_service(), CanonicalRepository(db["activities"], Activity))


def get_bank_account_service() -> BankAccountService:
    db = get_database()
    return BankAccountService(CanonicalRepository(db["bank_accounts"], BankAccount))


def get_reconciliation_service() -> ReconciliationService:
    db = get_database()
    return ReconciliationService(CanonicalRepository(db["reconciliation_records"], ReconciliationRecord), CanonicalRepository(db["payments"], Payment))


def get_ai_finance_service() -> AIFinanceService:
    from app.config import get_settings

    db = get_database()
    llm = get_llm_provider(db)
    ai_proposals = CanonicalRepository(db["ai_proposals"], AiProposal)
    engine = DecisionEngine(llm, ToolRegistry(), ai_proposals)
    return AIFinanceService(
        engine, get_invoice_service(), get_bill_service(), get_payment_service(), get_reconciliation_service(),
        CanonicalRepository(db["reconciliation_records"], ReconciliationRecord),
        ai_proposals, CanonicalRepository(db["activities"], Activity),
        shadow_mode=get_settings().ai_shadow_mode,
    )


def get_reward_ledger_service() -> RewardLedgerService:
    db = get_database()
    return RewardLedgerService(CanonicalRepository(db["reward_ledger_entries"], RewardLedgerEntry))


class CreateInvoiceRequest(BaseModel):
    customer_account_id: str
    line_items: list[LineItem]
    gst_details: GstDetails
    currency: str


class CreateBillRequest(BaseModel):
    vendor_account_id: str
    line_items: list[LineItem]
    gst_details: GstDetails
    currency: str


class RecordPaymentRequest(BaseModel):
    direction: str
    amount: Money
    method: str
    idempotency_key: str
    invoice_id: str | None = None
    bill_id: str | None = None
    payer_account_id: str | None = None
    allow_overpayment: bool = False


class CreateExpenseRequest(BaseModel):
    payee_account_id: str
    category: str
    amount: Money


class IssueCreditNoteRequest(BaseModel):
    invoice_id: str
    amount: Money
    reason: str


class AddBankAccountRequest(BaseModel):
    owner_type: str
    owner_id: str
    account_holder_name: str
    bank_name: str
    account_details_ref: str


class RecordExternalEntryRequest(BaseModel):
    source: str
    external_reference: str
    amount: Money


class MatchRequest(BaseModel):
    payment_id: str


class RewardLedgerRequest(BaseModel):
    panelist_person_id: str
    amount: Money
    reference_type: str
    reference_id: str


class ClawbackRequest(RewardLedgerRequest):
    creator_id: str  # whoever created the thing being clawed back — see RewardLedgerService.clawback


def _finance_error_to_http(exc: FinanceError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


# --------------------------------------------------------------------------- invoices


@router.get("/finance/invoices/{invoice_id}", response_model=Invoice)
async def get_invoice(invoice_id: str, identity: ResolvedIdentity = Depends(require_permission(FINANCE_READ)), svc: InvoiceService = Depends(get_invoice_service)) -> Invoice:
    invoice = await svc._invoices.get(invoice_id)
    if invoice is None or invoice.org_id != identity.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice not found")
    return invoice


@router.get("/finance/bills/{bill_id}", response_model=Bill)
async def get_bill(bill_id: str, identity: ResolvedIdentity = Depends(require_permission(FINANCE_READ)), svc: BillService = Depends(get_bill_service)) -> Bill:
    bill = await svc._bills.get(bill_id)
    if bill is None or bill.org_id != identity.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "bill not found")
    return bill


@router.post("/finance/invoices", response_model=Invoice)
async def create_invoice(body: CreateInvoiceRequest, identity: ResolvedIdentity = Depends(require_permission(INVOICE_CREATE)), svc: InvoiceService = Depends(get_invoice_service)) -> Invoice:
    return await svc.create_invoice(org_id=identity.org_id, actor=identity.user_id, customer_account_id=body.customer_account_id, line_items=body.line_items, gst_details=body.gst_details, currency=body.currency)


@router.post("/finance/invoices/{invoice_id}/submit", response_model=Invoice)
async def submit_invoice(invoice_id: str, identity: ResolvedIdentity = Depends(require_permission(INVOICE_SUBMIT)), svc: InvoiceService = Depends(get_invoice_service)) -> Invoice:
    try:
        return await svc.submit_invoice(org_id=identity.org_id, actor=identity.user_id, invoice_id=invoice_id)
    except FinanceError as exc:
        raise _finance_error_to_http(exc) from exc


@router.post("/finance/invoices/{invoice_id}/approve", response_model=Invoice)
async def approve_invoice(
    invoice_id: str,
    identity: ResolvedIdentity = Depends(get_current_identity),
    rbac: RBACService = Depends(get_rbac_service),
    svc: InvoiceService = Depends(get_invoice_service),
) -> Invoice:
    if not rbac.has_permission(identity, "finance.invoice.approve", target_org_id=identity.org_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing permission: finance.invoice.approve")
    try:
        return await svc.approve_invoice(identity=identity, rbac=rbac, invoice_id=invoice_id)
    except FinanceError as exc:
        raise _finance_error_to_http(exc) from exc


@router.post("/finance/invoices/{invoice_id}/send", response_model=Invoice)
async def send_invoice(invoice_id: str, identity: ResolvedIdentity = Depends(require_permission(INVOICE_SEND)), svc: InvoiceService = Depends(get_invoice_service)) -> Invoice:
    try:
        return await svc.send_invoice(org_id=identity.org_id, actor=identity.user_id, invoice_id=invoice_id)
    except FinanceError as exc:
        raise _finance_error_to_http(exc) from exc


# ------------------------------------------------------------------------------ bills


@router.post("/finance/bills", response_model=Bill)
async def create_bill(body: CreateBillRequest, identity: ResolvedIdentity = Depends(require_permission(BILL_CREATE)), svc: BillService = Depends(get_bill_service)) -> Bill:
    return await svc.create_bill(org_id=identity.org_id, actor=identity.user_id, vendor_account_id=body.vendor_account_id, line_items=body.line_items, gst_details=body.gst_details, currency=body.currency)


@router.post("/finance/bills/{bill_id}/submit", response_model=Bill)
async def submit_bill(bill_id: str, identity: ResolvedIdentity = Depends(require_permission(BILL_SUBMIT)), svc: BillService = Depends(get_bill_service)) -> Bill:
    try:
        return await svc.submit_bill(org_id=identity.org_id, actor=identity.user_id, bill_id=bill_id)
    except FinanceError as exc:
        raise _finance_error_to_http(exc) from exc


@router.post("/finance/bills/{bill_id}/approve", response_model=Bill)
async def approve_bill(
    bill_id: str,
    identity: ResolvedIdentity = Depends(get_current_identity),
    rbac: RBACService = Depends(get_rbac_service),
    svc: BillService = Depends(get_bill_service),
) -> Bill:
    if not rbac.has_permission(identity, "finance.bill.approve", target_org_id=identity.org_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing permission: finance.bill.approve")
    try:
        return await svc.approve_bill(identity=identity, rbac=rbac, bill_id=bill_id)
    except FinanceError as exc:
        raise _finance_error_to_http(exc) from exc


# --------------------------------------------------------------------------- payments


@router.post("/finance/payments", response_model=Payment)
async def record_payment(body: RecordPaymentRequest, identity: ResolvedIdentity = Depends(require_permission(PAYMENT_CREATE)), svc: PaymentService = Depends(get_payment_service)) -> Payment:
    try:
        return await svc.record_payment(
            org_id=identity.org_id, actor=identity.user_id, direction=body.direction, amount=body.amount, method=body.method,
            idempotency_key=body.idempotency_key, invoice_id=body.invoice_id, bill_id=body.bill_id,
            payer_account_id=body.payer_account_id, allow_overpayment=body.allow_overpayment,
        )
    except FinanceError as exc:
        raise _finance_error_to_http(exc) from exc


@router.post("/finance/payments/{payment_id}/reverse", response_model=Payment)
async def reverse_payment(
    payment_id: str,
    identity: ResolvedIdentity = Depends(get_current_identity),
    rbac: RBACService = Depends(get_rbac_service),
    svc: PaymentService = Depends(get_payment_service),
) -> Payment:
    if not rbac.has_permission(identity, PAYMENT_REVERSE, target_org_id=identity.org_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing permission: {PAYMENT_REVERSE}")
    try:
        return await svc.reverse_payment(identity=identity, rbac=rbac, payment_id=payment_id)
    except FinanceError as exc:
        raise _finance_error_to_http(exc) from exc


# --------------------------------------------------------------------------- expenses


@router.post("/finance/expenses", response_model=Expense)
async def create_expense(body: CreateExpenseRequest, identity: ResolvedIdentity = Depends(require_permission(EXPENSE_CREATE)), svc: ExpenseService = Depends(get_expense_service)) -> Expense:
    return await svc.create_expense(org_id=identity.org_id, actor=identity.user_id, payee_account_id=body.payee_account_id, category=body.category, amount=body.amount)


@router.post("/finance/expenses/{expense_id}/approve", response_model=Expense)
async def approve_expense(
    expense_id: str,
    identity: ResolvedIdentity = Depends(get_current_identity),
    rbac: RBACService = Depends(get_rbac_service),
    svc: ExpenseService = Depends(get_expense_service),
) -> Expense:
    if not rbac.has_permission(identity, "finance.expense.approve", target_org_id=identity.org_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing permission: finance.expense.approve")
    try:
        return await svc.approve_expense(identity=identity, rbac=rbac, expense_id=expense_id)
    except FinanceError as exc:
        raise _finance_error_to_http(exc) from exc


# ----------------------------------------------------------------------- credit notes


@router.post("/finance/credit-notes", response_model=CreditNote)
async def issue_credit_note(
    body: IssueCreditNoteRequest,
    identity: ResolvedIdentity = Depends(get_current_identity),
    rbac: RBACService = Depends(get_rbac_service),
    svc: CreditNoteService = Depends(get_credit_note_service),
) -> CreditNote:
    if not rbac.has_permission(identity, CREDITNOTE_CREATE, target_org_id=identity.org_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing permission: {CREDITNOTE_CREATE}")
    try:
        return await svc.issue_credit_note(org_id=identity.org_id, identity=identity, rbac=rbac, invoice_id=body.invoice_id, amount=body.amount, reason=body.reason)
    except FinanceError as exc:
        raise _finance_error_to_http(exc) from exc


@router.post("/finance/credit-notes/{credit_note_id}/apply", response_model=CreditNote)
async def apply_credit_note(credit_note_id: str, identity: ResolvedIdentity = Depends(require_permission(CREDITNOTE_APPLY)), svc: CreditNoteService = Depends(get_credit_note_service)) -> CreditNote:
    try:
        return await svc.apply_credit_note(org_id=identity.org_id, actor=identity.user_id, credit_note_id=credit_note_id)
    except FinanceError as exc:
        raise _finance_error_to_http(exc) from exc


# ------------------------------------------------------------------------ bank accounts


@router.post("/finance/bank-accounts", response_model=BankAccount)
async def add_bank_account(body: AddBankAccountRequest, identity: ResolvedIdentity = Depends(require_permission(BANKACCOUNT_MANAGE)), svc: BankAccountService = Depends(get_bank_account_service)) -> BankAccount:
    return await svc.add_bank_account(
        org_id=identity.org_id, actor=identity.user_id, owner_type=body.owner_type, owner_id=body.owner_id,
        account_holder_name=body.account_holder_name, bank_name=body.bank_name, account_details_ref=body.account_details_ref,
    )


# ---------------------------------------------------------------------- reconciliation


@router.post("/finance/reconciliation/entries", response_model=ReconciliationRecord)
async def record_external_entry(body: RecordExternalEntryRequest, identity: ResolvedIdentity = Depends(require_permission(RECONCILIATION_MANAGE)), svc: ReconciliationService = Depends(get_reconciliation_service)) -> ReconciliationRecord:
    return await svc.record_external_entry(org_id=identity.org_id, actor=identity.user_id, source=body.source, external_reference=body.external_reference, amount=body.amount)


@router.post("/finance/reconciliation/entries/{record_id}/match", response_model=ReconciliationRecord)
async def match_reconciliation_entry(record_id: str, body: MatchRequest, identity: ResolvedIdentity = Depends(require_permission(RECONCILIATION_MANAGE)), svc: ReconciliationService = Depends(get_reconciliation_service)) -> ReconciliationRecord:
    try:
        return await svc.match(org_id=identity.org_id, actor=identity.user_id, record_id=record_id, payment_id=body.payment_id)
    except FinanceError as exc:
        raise _finance_error_to_http(exc) from exc


# -------------------------------------------------------------------------- rewards


@router.post("/rewards/credit", response_model=RewardLedgerEntry)
async def credit_rewards(body: RewardLedgerRequest, identity: ResolvedIdentity = Depends(require_permission(REWARDS_CREDIT)), svc: RewardLedgerService = Depends(get_reward_ledger_service)) -> RewardLedgerEntry:
    try:
        return await svc.credit(org_id=identity.org_id, actor=identity.user_id, panelist_person_id=body.panelist_person_id, amount=body.amount, reference_type=body.reference_type, reference_id=body.reference_id)
    except RewardLedgerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/rewards/debit", response_model=RewardLedgerEntry)
async def debit_rewards(body: RewardLedgerRequest, identity: ResolvedIdentity = Depends(require_permission(REWARDS_DEBIT)), svc: RewardLedgerService = Depends(get_reward_ledger_service)) -> RewardLedgerEntry:
    try:
        return await svc.debit(org_id=identity.org_id, actor=identity.user_id, panelist_person_id=body.panelist_person_id, amount=body.amount, reference_type=body.reference_type, reference_id=body.reference_id)
    except RewardLedgerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/rewards/clawback", response_model=RewardLedgerEntry)
async def clawback_rewards(
    body: ClawbackRequest,
    identity: ResolvedIdentity = Depends(get_current_identity),
    rbac: RBACService = Depends(get_rbac_service),
    svc: RewardLedgerService = Depends(get_reward_ledger_service),
) -> RewardLedgerEntry:
    if not rbac.has_permission(identity, "rewards.clawback.approve", target_org_id=identity.org_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing permission: rewards.clawback.approve")
    try:
        return await svc.clawback(
            org_id=identity.org_id, actor=identity.user_id, identity=identity, rbac=rbac,
            panelist_person_id=body.panelist_person_id, amount=body.amount,
            reference_type=body.reference_type, reference_id=body.reference_id, creator_id=body.creator_id,
        )
    except RewardLedgerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/rewards/{panelist_person_id}/balance", response_model=Money)
async def get_reward_balance(panelist_person_id: str, currency: str, identity: ResolvedIdentity = Depends(require_permission(REWARDS_READ)), svc: RewardLedgerService = Depends(get_reward_ledger_service)) -> Money:
    return await svc.get_balance(panelist_person_id, currency=currency)


# -------------------------------------------------------------------------- AI finance


class MatchPaymentRequest(BaseModel):
    allow_overpayment: bool = False


class MatchPaymentResponse(BaseModel):
    decision: Decision
    payment: Payment | None = None


@router.post("/finance/invoices/{invoice_id}/ai/ar-followup", response_model=Decision)
async def decide_ar_followup(invoice_id: str, identity: ResolvedIdentity = Depends(require_permission(FINANCE_AI_AR)), svc: AIFinanceService = Depends(get_ai_finance_service)) -> Decision:
    try:
        return await svc.decide_ar_followup(org_id=identity.org_id, actor=identity.user_id, invoice_id=invoice_id)
    except AIFinanceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/finance/bills/{bill_id}/ai/ap-followup", response_model=Decision)
async def decide_ap_followup(bill_id: str, identity: ResolvedIdentity = Depends(require_permission(FINANCE_AI_AP)), svc: AIFinanceService = Depends(get_ai_finance_service)) -> Decision:
    try:
        return await svc.decide_ap_followup(org_id=identity.org_id, actor=identity.user_id, bill_id=bill_id)
    except AIFinanceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/finance/reconciliation/entries/{record_id}/ai-match", response_model=MatchPaymentResponse)
async def ai_match_payment(
    record_id: str, body: MatchPaymentRequest,
    identity: ResolvedIdentity = Depends(require_permission(FINANCE_AI_MATCH)),
    svc: AIFinanceService = Depends(get_ai_finance_service),
) -> MatchPaymentResponse:
    try:
        decision, payment = await svc.match_payment_to_invoice(org_id=identity.org_id, actor=identity.user_id, reconciliation_record_id=record_id, allow_overpayment=body.allow_overpayment)
    except AIFinanceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return MatchPaymentResponse(decision=decision, payment=payment)


@router.get("/finance/analytics/ar-ageing")
async def ar_ageing(identity: ResolvedIdentity = Depends(require_permission(FINANCE_ANALYTICS_READ)), svc: FinanceAnalyticsService = Depends(get_finance_analytics_service)) -> dict:
    return await svc.ar_ageing(org_id=identity.org_id)


@router.get("/finance/analytics/ap-ageing")
async def ap_ageing(identity: ResolvedIdentity = Depends(require_permission(FINANCE_ANALYTICS_READ)), svc: FinanceAnalyticsService = Depends(get_finance_analytics_service)) -> dict:
    return await svc.ap_ageing(org_id=identity.org_id)
