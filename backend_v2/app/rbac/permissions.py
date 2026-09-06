"""
Closed permission-code list — spec §31: "no wildcard permissions." A new permission
is a new constant here, never invented inline at a call site the way v1's codes were
scattered across `rbac/permissions.py`, individual routers, and ad-hoc string literals.

`APPROVAL_PERMISSIONS` is the D-14 fix. v1's `admin` role held the literal wildcard
`"*"` (`rbac/simple.py`), which under the B-07 approval policy would silently confer
unlimited financial approval authority the moment D-01 (the identity-resolver bug that
hardcoded every session to `admin`) was fixed and `admin` became a real, reachable role
again. The register states this as a single mandatory Phase 1 gate (§0.2): fixing the
resolver without excluding these codes from any wildcard satisfies neither half.
"""

from __future__ import annotations

ADMIN_WILDCARD = "*"

# The eight operations register §5.7 / decision B-07 names as requiring approval.
APPROVAL_PERMISSIONS: frozenset[str] = frozenset(
    {
        "finance.invoice.approve",
        "finance.bill.approve",
        "finance.payment.approve",
        "finance.expense.approve",
        "finance.creditnote.approve",
        "finance.refund.approve",
        "rewards.clawback.approve",
        "finance.account_adjustment.approve",
    }
)

# Representative non-approval permissions exercised by this slice's tests. The closed
# list grows alongside each domain as it's built (Person, Account, Invoice, ...) —
# not meant to be exhaustive yet.
PERSON_READ = "person.read"
PERSON_CREATE = "person.create"
PERSON_RESOLVE = "person.resolve"
ACCOUNT_READ = "account.read"
ACCOUNT_CREATE = "account.create"
ACCOUNT_RESOLVE = "account.resolve"
ACCOUNT_MERGE = "account.merge"
ROLE_ASSIGN = "role.assign"
IMPERSONATE = "auth.impersonate"

LEAD_INGEST = "lead.ingest"
LEAD_READ = "lead.read"
LEAD_QUALIFY = "lead.qualify"
LEAD_ASSIGN = "lead.assign"
LEAD_ENROLL = "lead.enroll"

OUTREACH_SEND = "outreach.send"
OUTREACH_ADMIN = "outreach.admin"  # kill switch pause/resume — deliberately separate
# from OUTREACH_SEND: the person allowed to send mail is not automatically the person
# allowed to shut off sending org-wide (register §5.4: "kill switch has known
# bypasses" — a coarse, shared permission would be one more).
OUTREACH_SUPPRESS = "outreach.suppress"

# Finance — endpoint_catalogue.md §Finance. The *.approve codes already sit in
# APPROVAL_PERMISSIONS above; these are the surrounding non-approval permissions the
# catalogue names for the same entities (create/submit/send/reverse/apply), kept
# distinct so holding one never implies the other.
INVOICE_CREATE = "finance.invoice.create"
INVOICE_SUBMIT = "finance.invoice.submit"
INVOICE_SEND = "finance.invoice.send"
BILL_CREATE = "finance.bill.create"
BILL_SUBMIT = "finance.bill.submit"
PAYMENT_CREATE = "finance.payment.create"
PAYMENT_REVERSE = "finance.payment.reverse"
EXPENSE_CREATE = "finance.expense.create"
CREDITNOTE_CREATE = "finance.creditnote.create"
CREDITNOTE_APPLY = "finance.creditnote.apply"
BANKACCOUNT_MANAGE = "finance.bankaccount.manage"
RECONCILIATION_MANAGE = "finance.reconciliation.manage"
FINANCE_READ = "finance.read"

REWARDS_CREDIT = "rewards.credit"  # system — from survey completion (Slice 9's caller)
REWARDS_DEBIT = "rewards.debit"
REWARDS_READ = "rewards.read"
# rewards.clawback.approve already exists in APPROVAL_PERMISSIONS above.

# Panel/Survey — endpoint_catalogue.md §5.
SURVEY_MANAGE = "survey.manage"  # create + eligibility toggle
SURVEY_READ = "survey.read"
SURVEY_ALLOCATE = "survey.allocate"  # system — called from the public traffic-redirect
# endpoint after its own rate-limit/fraud gates, never exposed to a plain user session
SURVEY_RECONCILE = "survey.reconcile"  # system/cron
SUPPLIER_MANAGE = "supplier.manage"

# CRM — schema_catalogue.md §2.2 / endpoint_catalogue.md's Opportunity rows.
OPPORTUNITY_CREATE = "opportunity.create"
OPPORTUNITY_UPDATE = "opportunity.update"
OPPORTUNITY_READ = "opportunity.read"
OPPORTUNITY_CONVERT = "opportunity.convert"

# AI Gateway / GPU broker — docs/AI_NATIVE_COMPLETION_CHECKLIST.md Phase 2/3.
AI_READ = "ai.read"  # broker status — safe, no cost implication
AI_ADMIN = "ai.admin"  # kill switch — same "separate from ordinary read" pattern as OUTREACH_ADMIN

# Email AI — Slice 12.
EMAIL_INGEST = "email.ingest"  # system — the (future) mailbox-polling caller
EMAIL_ANALYZE = "email.analyze"
EMAIL_READ = "email.read"

# GSC lead generation / ICP — Slice 13.
LEADGEN_AI_GENERATE = "leadgen.ai.generate"  # system — the (future) scheduled caller
LEADGEN_AI_EVALUATE_ICP = "leadgen.ai.evaluate_icp"

# AI outreach — Slice 14.
OUTREACH_AI_DECIDE = "outreach.ai.decide"  # system — the (future) scheduled caller

# AI panel allocation — Slice 15.
SURVEY_AI_ALLOCATE = "survey.ai.allocate"  # system — called from the public traffic-redirect path, same as SURVEY_ALLOCATE

# AI operations — Slice 16.
SURVEY_AI_OPERATIONS = "survey.ai.operations"  # system — the (future) scheduled caller

# AI finance — Slice 17.
FINANCE_AI_AR = "finance.ai.ar_followup"  # system — the (future) scheduled caller
FINANCE_AI_AP = "finance.ai.ap_followup"
FINANCE_AI_MATCH = "finance.ai.match_payment"

# Survey billing/margin — Slice 18.
SURVEY_BILLING_MANAGE = "survey.billing.manage"
SURVEY_MARGIN_READ = "survey.margin.read"

# Integration/diagnostics status — Slice 18/19.
INTEGRATIONS_STATUS_READ = "integrations.status.read"
