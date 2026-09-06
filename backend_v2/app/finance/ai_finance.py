"""
AIFinanceService — AR/AP follow-up and payment-to-invoice matching, all routed
through the real `DecisionEngine`. Per explicit user instruction, this slice
exists to prove **AI can participate in money movement without becoming the
accounting authority**:

**AI never alters a balance, a ledger, an invoice total, or a payment record.**
The only write paths here are the existing, unchanged Slice 8 services —
`PaymentService.record_payment()` (typed `Money`, atomic version-guarded balance
update, idempotent) and `ReconciliationService.match()`. This module calls them;
it never touches `db["..."]`, and it never re-implements what they already do.
Whether a payment is "partial" or "full" is arithmetic `PaymentService` already
computes deterministically — that was never an AI decision to begin with, and
nothing here second-guesses it.

**Payment matching: deterministic candidates, AI picks, governed service
executes.** `InvoiceService.list_open()` filtered to an exact `total`/
`balance_due` match against the `ReconciliationRecord`'s amount is the *entire*
candidate set the model is shown — the same "offer the walls, don't ask the AI
to build them" pattern as Slice 15/16. A model naming an invoice outside that
set is rejected outright. Only when the model is confident (`is_auto_appliable()`)
does this service call the real `record_payment()` + `match()` — anything else
(`NO_MATCH`, `NEEDS_HUMAN_REVIEW`, or a low-confidence `MATCH`) leaves the
`ReconciliationRecord` `unmatched` for a human to resolve, exactly as Slice 8
already designed it to.

**"Never let AI infer financial truth from an email"** — Slice 12's
`EmailAIService` already only ever calls `ReconciliationService.record_external_entry()`
for a `PAYMENT`/`INVOICE`/`BILL`-classified email (a candidate, `unmatched`,
never `PAID`). This module is the next real step in that same chain: the
candidate this service matches against an invoice can be exactly the one Slice
12 created from an email — the client saying "we've paid invoice 1042" produces
a `ReconciliationRecord`, never a `PAID` invoice, until *this* module's governed
matching (or a human) actually attaches a verified `Payment` to it.

**AP stays recommendation-only, deliberately asymmetric with AR.** Matching an
already-received client payment to an invoice is safe to auto-apply at high
confidence — the money already arrived, this only decides where to record it.
Actually paying a supplier is a real outgoing transaction; `decide_ap_followup()`
only ever recommends `SCHEDULE_PAYMENT` (or another action) — no code path here
ever calls `record_payment(direction="made", ...)` automatically. A human acts
on the recommendation through the existing, unchanged `POST /finance/payments`
endpoint.

**Margin/Cint/billing linkage is explicitly Slice 18's scope, not built here** —
there is no `Survey`↔`Invoice` linkage in the schema yet beyond
`Invoice.opportunity_id` (Slice 10), and building a fabricated one now would be
exactly the no-fake-completion failure this rebuild's discipline exists to
prevent.

**`Invoice`/`Bill.ai_decision_subject_id`** (one field each) trace the last
AR/AP-followup decision back to its `AiProposal` — the same
`Allocation`/`Survey.ai_decision_subject_id` pattern (Slices 15-16), generalized
again per explicit user instruction.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.ai.decision_engine import Decision, DecisionEngine
from app.finance.models import Bill, Invoice, Payment, ReconciliationRecord
from app.finance.service import BillService, FinanceError, InvoiceService, PaymentService, ReconciliationService
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository

AR_FOLLOWUP_ACTIONS = frozenset({"REMINDER", "URGENT_REMINDER", "REQUEST_INFO", "ESCALATE", "HOLD", "NO_ACTION"})
AP_FOLLOWUP_ACTIONS = frozenset({"SCHEDULE_PAYMENT", "REQUEST_CLARIFICATION", "ESCALATE", "HOLD", "NO_ACTION"})
MATCH_SENTINELS = frozenset({"NO_MATCH", "NEEDS_HUMAN_REVIEW"})  # the only non-invoice-id values 'decision.decision' may take

_AR_INSTRUCTIONS = (
    "An open invoice needs a follow-up decision. Decide 'decision', one of: "
    "REMINDER, URGENT_REMINDER, REQUEST_INFO (ask the client something before "
    "chasing payment), ESCALATE (needs urgent human attention — e.g. the amount "
    "or pattern looks anomalous), HOLD (do nothing right now, note why), or "
    "NO_ACTION. Use 'evidence' (balance due, days overdue, payment history) as "
    "real signal. Explain your reasoning in 'reasoning_summary'."
)
_AP_INSTRUCTIONS = (
    "An approved bill needs a follow-up decision. Decide 'decision', one of: "
    "SCHEDULE_PAYMENT (recommend paying it — a human still executes the actual "
    "payment), REQUEST_CLARIFICATION (something about the bill needs checking "
    "with the supplier first), ESCALATE, HOLD, or NO_ACTION."
)
_MATCH_INSTRUCTIONS = (
    "A payment/bank-transaction record needs to be matched to an open invoice. "
    "Choose the best match from 'candidate_invoices' (by invoice_id) as "
    "'decision', or 'NO_MATCH' if none of the candidates are right, or "
    "'NEEDS_HUMAN_REVIEW' if it's ambiguous between more than one. Never name "
    "an invoice_id that is not in 'candidate_invoices'."
)


class AIFinanceError(Exception):
    """Missing invoice/bill/record, the model returned an action outside the
    closed set, or the model matched an invoice outside the candidate set it was
    offered. Same discipline as every other domain's single error type."""


class AIFinanceService:
    def __init__(
        self, decision_engine: DecisionEngine, invoice_service: InvoiceService, bill_service: BillService,
        payment_service: PaymentService, reconciliation_service: ReconciliationService,
        reconciliation_repo: CanonicalRepository[ReconciliationRecord],
        ai_proposals: CanonicalRepository[AiProposal], activities: CanonicalRepository[Activity],
    ):
        self._decision_engine = decision_engine
        self._invoice_service = invoice_service
        self._bill_service = bill_service
        self._payment_service = payment_service
        self._reconciliation_service = reconciliation_service
        self._reconciliation_repo = reconciliation_repo
        self._ai_proposals = ai_proposals
        self._activities = activities

    # ------------------------------------------------------------------ AR

    async def decide_ar_followup(self, *, org_id: str, actor: str, invoice_id: str) -> Decision:
        invoice = await self._invoice_service._invoices.get(invoice_id)
        if invoice is None:
            raise AIFinanceError(f"invoice {invoice_id} does not exist")
        if invoice.status not in ("sent", "partially_paid"):
            raise AIFinanceError(f"invoice {invoice_id} is not in a followup-eligible status (status={invoice.status})")

        subject_id = f"{invoice_id}:ar:{date.today().isoformat()}"
        existing = await self._ai_proposals.find_one({"task": "evaluate_ar_followup", "subject_id": subject_id})
        if existing:
            return Decision.model_validate(existing.proposed_fields)

        days_overdue = (datetime.now(timezone.utc) - invoice.due_at).days if invoice.due_at else None
        context = {
            "task_instructions": _AR_INSTRUCTIONS,
            "evidence": {
                "balance_due_minor": invoice.balance_due.amount_minor, "total_minor": invoice.total.amount_minor,
                "amount_paid_minor": invoice.amount_paid.amount_minor, "currency": invoice.total.currency,
                "days_overdue": days_overdue, "status": invoice.status,
            },
        }
        decision = await self._decision_engine.decide(org_id=org_id, task="evaluate_ar_followup", subject_id=subject_id, context=context)
        if decision.decision not in AR_FOLLOWUP_ACTIONS:
            raise AIFinanceError(f"model returned an unrecognized AR follow-up action {decision.decision!r}")

        await self._invoice_service._invoices.update(invoice.id, invoice.version, {"ai_decision_subject_id": subject_id}, updated_by=actor)
        await self._activities.insert(
            Activity(org_id=org_id, created_by=actor, updated_by=actor, type=f"ar_followup_{decision.decision.lower()}", subject_type="invoice", subject_id=invoice.id, actor_type="system", actor_id=actor, payload={"reasoning": decision.reasoning_summary})
        )
        return decision

    # ------------------------------------------------------------------ AP

    async def decide_ap_followup(self, *, org_id: str, actor: str, bill_id: str) -> Decision:
        bill = await self._bill_service._bills.get(bill_id)
        if bill is None:
            raise AIFinanceError(f"bill {bill_id} does not exist")
        if bill.status not in ("approved", "partially_paid"):
            raise AIFinanceError(f"bill {bill_id} is not in a followup-eligible status (status={bill.status})")

        subject_id = f"{bill_id}:ap:{date.today().isoformat()}"
        existing = await self._ai_proposals.find_one({"task": "evaluate_ap_followup", "subject_id": subject_id})
        if existing:
            return Decision.model_validate(existing.proposed_fields)

        days_overdue = (datetime.now(timezone.utc) - bill.due_at).days if bill.due_at else None
        context = {
            "task_instructions": _AP_INSTRUCTIONS,
            "evidence": {
                "balance_due_minor": bill.balance_due.amount_minor, "total_minor": bill.total.amount_minor,
                "amount_paid_minor": bill.amount_paid.amount_minor, "currency": bill.total.currency,
                "days_overdue": days_overdue, "status": bill.status,
            },
        }
        decision = await self._decision_engine.decide(org_id=org_id, task="evaluate_ap_followup", subject_id=subject_id, context=context)
        if decision.decision not in AP_FOLLOWUP_ACTIONS:
            raise AIFinanceError(f"model returned an unrecognized AP follow-up action {decision.decision!r}")

        await self._bill_service._bills.update(bill.id, bill.version, {"ai_decision_subject_id": subject_id}, updated_by=actor)
        await self._activities.insert(
            Activity(org_id=org_id, created_by=actor, updated_by=actor, type=f"ap_followup_{decision.decision.lower()}", subject_type="bill", subject_id=bill.id, actor_type="system", actor_id=actor, payload={"reasoning": decision.reasoning_summary})
        )
        return decision

    # ------------------------------------------------------------- matching

    async def match_payment_to_invoice(self, *, org_id: str, actor: str, reconciliation_record_id: str, allow_overpayment: bool = False) -> tuple[Decision, Payment | None]:
        record = await self._reconciliation_repo.get(reconciliation_record_id)
        if record is None:
            raise AIFinanceError(f"reconciliation record {reconciliation_record_id} does not exist")
        if record.status == "matched":
            raise AIFinanceError(f"reconciliation record {reconciliation_record_id} is already matched")

        open_invoices = await self._invoice_service.list_open(org_id=org_id)
        candidates = [inv for inv in open_invoices if inv.balance_due.amount_minor == record.amount.amount_minor and inv.balance_due.currency == record.amount.currency]
        candidate_ids = {inv.id for inv in candidates}

        context = {
            "task_instructions": _MATCH_INSTRUCTIONS,
            "record": {"source": record.source, "external_reference": record.external_reference, "amount_minor": record.amount.amount_minor, "currency": record.amount.currency},
            "candidate_invoices": [{"invoice_id": inv.id, "customer_account_id": inv.customer_account_id, "balance_due_minor": inv.balance_due.amount_minor, "invoice_number": inv.invoice_number} for inv in candidates],
        }
        decision = await self._decision_engine.decide(org_id=org_id, task="match_payment_to_invoice", subject_id=record.id, context=context)

        if decision.decision not in MATCH_SENTINELS and decision.decision not in candidate_ids:
            raise AIFinanceError(f"model matched invoice {decision.decision!r}, which was not in the candidate set it was offered")

        if decision.decision in MATCH_SENTINELS or not decision.is_auto_appliable():
            return decision, None

        payment = await self._payment_service.record_payment(
            org_id=org_id, actor=actor, direction="received", amount=record.amount, method=record.source,
            idempotency_key=f"ai-reconciliation:{record.id}", invoice_id=decision.decision, allow_overpayment=allow_overpayment,
        )
        await self._reconciliation_service.match(actor=actor, record_id=record.id, payment_id=payment.id)
        return decision, payment
