"""
Finance domain models — Invoice, Bill, Payment, Expense, CreditNote, BankAccount,
ReconciliationRecord. Every monetary field is a `Money` (schema_catalogue.md §0
shape), never a float or client-supplied string (data_lineage_map.md §2; D-33).

**Invoice/Bill totals are always server-derived, never accepted from the client**
(endpoint_catalogue.md §Finance: "closes the client-controlled tax defect"). Nothing
in this module exposes a way to set `subtotal`/`tax_total`/`total` directly — see
`app.finance.totals.compute_totals()`, the one function that produces them, and
`FinanceService` (never a router, never a caller) is the only thing that calls it.

**GST structure closes D-10** ("zero-rated and RCM supplies indistinguishable on the
issued document"): `GstDetails.is_reverse_charge`/`is_export`/`is_sez`/`lut_number`
are real, queryable fields on the document itself, not inferred after the fact.

**`BankAccount.account_details_ref` never stores a plaintext account/IBAN number** —
the same indirection pattern as `app.outreach.models.Mailbox.credentials_id` (the
D-26 fix), applied here because the finance domain has the same class of exposure a
real deployment would need to guard.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.base import CanonicalDocument
from app.models.money import Money


class LineItem(BaseModel):
    description: str
    quantity: int
    unit_price_minor: int  # same currency as the parent document
    hsn_sac: str | None = None
    gst_rate_bps: int = 0  # basis points — 1800 == 18.00%


class GstDetails(BaseModel):
    place_of_supply: str
    is_reverse_charge: bool = False
    is_export: bool = False
    is_sez: bool = False
    lut_number: str | None = None  # required by GST rule when is_export/is_sez —
    # not enforced here (no rules engine in this slice); the field exists so the
    # distinction is representable at all, which v1 never was (D-10).


class Invoice(CanonicalDocument):
    customer_account_id: str
    invoice_number: str
    status: str = "draft"  # draft -> pending_approval -> approved -> sent (immutable
    # from here on) -> partially_paid -> paid ; or -> void (only from draft/pending_approval)
    line_items: list[LineItem]
    gst_details: GstDetails
    subtotal: Money
    tax_total: Money
    total: Money
    amount_paid: Money
    balance_due: Money
    approved_by: str | None = None
    approved_at: datetime | None = None


class Bill(CanonicalDocument):
    vendor_account_id: str
    bill_number: str
    status: str = "draft"  # draft -> pending_approval -> approved (immutable, payable) -> partially_paid -> paid ; or -> void
    line_items: list[LineItem]
    gst_details: GstDetails
    subtotal: Money
    tax_total: Money
    total: Money
    amount_paid: Money
    balance_due: Money
    approved_by: str | None = None
    approved_at: datetime | None = None


class Payment(CanonicalDocument):
    direction: str  # "received" | "made"
    invoice_id: str | None = None
    bill_id: str | None = None
    payer_account_id: str | None = None  # validated to match invoice.customer_account_id when set
    payment_number: str
    amount: Money
    method: str
    status: str = "recorded"  # recorded | reversed — never deleted, see FinanceService.reverse_payment
    idempotency_key: str


class Expense(CanonicalDocument):
    payee_account_id: str
    category: str
    amount: Money
    requires_approval: bool  # server-computed at creation, never client-settable — D-37
    approval_status: str  # pending | approved | rejected — server-computed, never client-settable — D-37
    approved_by: str | None = None


class CreditNote(CanonicalDocument):
    invoice_id: str
    credit_note_number: str
    amount: Money
    reason: str
    status: str = "issued"  # issued -> applied
    issued_by: str = ""  # who held approval authority at issuance — see FinanceService


class BankAccount(CanonicalDocument):
    owner_type: str  # "org" | "vendor" | "employee"
    owner_id: str
    account_holder_name: str
    bank_name: str
    account_details_ref: str  # opaque reference only — see module docstring
    is_active: bool = True


class ReconciliationRecord(CanonicalDocument):
    source: str  # "bank_statement" | "payment_gateway" | "manual"
    external_reference: str
    payment_id: str | None = None
    status: str = "unmatched"  # unmatched | matched
    amount: Money
