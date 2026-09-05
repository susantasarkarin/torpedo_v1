# Torpedo v2 — Endpoint Catalogue (spec §31)

> Generated: 2026-09-05 | Phase 0 deliverable
> Depends on: [schema_catalogue.md](schema_catalogue.md) (every entity/field referenced here, not restated), [lead_generation_specification.md](lead_generation_specification.md) (lead state machine), [business_rules_register.md](business_rules_register.md) (B-07 approval policy, money/state-machine decisions, defects this catalogue closes by construction)
> Precedes: Screen Catalogue (§32) — screens reference these endpoints rather than inventing calls inline.

## 0. Governing rules (apply to every endpoint unless an entry overrides one explicitly)

These are stated once here rather than repeated per row, because repeating them per endpoint is exactly the pattern that let v1's conventions erode silently (register §0.2: a rule stated nowhere structural is a rule that gets skipped somewhere).

| Rule | Statement |
|---|---|
| **Route convention** | `/api/v1/{resource}`. No unprefixed routes, no per-router path style (v1 had `/api/x`, bare `/x`, and double-mounted routers coexisting — codebase_inventory.md §1). |
| **Auth** | Every endpoint resolves the caller's effective permissions from the canonical role model, server-side, deny-by-default. **No endpoint may accept a database, organization, or role as a client-supplied parameter** — this is the structural fix for D-01, D-14, and D-15 (the outreach router's caller-controlled `db_name`) in one rule. |
| **Org scope** | Every query is filtered by the caller's `org_id` server-side. Never trust a client-supplied `org_id`. |
| **Idempotency** | Every mutating endpoint accepts an `Idempotency-Key` header. **Required, not optional**, on any endpoint touching money, sends, or identity resolution — closes D-04 (no payment idempotency) and D-15's sibling class of defects by making the omission a schema violation, not a review-time judgment call. |
| **Concurrency** | Updates require `If-Match: "{version}"` against the entity's `version` field (schema_catalogue.md §0). A mismatch is `409 Conflict`, not a silent last-write-wins — closes the read-after-write payment race (register §1.4) at the protocol level. |
| **Errors** | RFC 9457 `problem+json` throughout (spec §38). One error shape, not per-router ad hoc dicts. |
| **Pagination** | Cursor-based (`limit` + `cursor`), never offset/skip on collections that can grow past a page (v1's unbounded reports were TOR-20; cursor pagination is the structural prevention, not just the fix). |
| **Activity** | Every mutating endpoint emits **exactly one** `Activity` record (schema_catalogue.md §2.3) per logical state change — not zero (v1's dominant pattern), not many uncoordinated writes to competing audit stores (register §2.7). State-machine endpoints that cause multiple transitions in one call emit one Activity per transition, explicitly noted where it applies. |
| **Approval** | Any endpoint marked **[APPROVAL-GATED]** routes through the single B-07 approval-policy service (`RBACService.get_approval_authority()`/`can_approve_amount()`). No endpoint reimplements approval logic locally — a second implementation is a defect by construction (I-1). |
| **Rate limits** | Stated per endpoint only where it deviates from the org-wide default (spec §49) — most endpoints inherit the default; sends, sends-adjacent, and public/unauthenticated endpoints always get an explicit limit. |
| **External-provider calls** | Any endpoint that calls an external provider (Cint, Gmail, SES) does so through a provider adapter (spec §17) with a stated timeout and a stated fallback-on-failure — never a bare provider SDK call inline in the handler, which was v1's dominant pattern outside the one or two places that got it right. |

---

## 1. Identity Domain

| Method + path | Entity | Operation | Permission | Idempotent | Notes |
|---|---|---|---|---|---|
| `POST /people` | `Person` | Create | `person.create` | Required | Internal use only (identity resolution creates people; see deep-dive) |
| `GET /people/{id}` | `Person` | Read | `person.read` | — | |
| `PATCH /people/{id}` | `Person` | Update | `person.update` | — | Concurrency-checked |
| `POST /people/resolve` | `Person` | Identity resolution | `person.resolve` (internal/system) | Required | See deep-dive below — the fix for D-22 |
| `POST /accounts` / `GET /accounts/{id}` / `PATCH` | `Account` | Standard CRUD | `account.*` | create: required | |
| `POST /accounts/merge` | `Account` | Entity-wide merge | `account.merge` | Required | **[APPROVAL-GATED]** — merge is consequential and irreversible-in-spirit; unlike v1 (register D-18: merge doesn't update external references and is silently undone by reconcile), this endpoint updates every referencing collection **in one transaction or not at all** |
| `POST /accounts/{id}/brand-relationships` | `AccountBrandRelationship` | Create | `account.brand.manage` | Required | No "one brand per account" constraint — locked principle 5 |
| `DELETE /accounts/{id}/brand-relationships/{rel_id}` | `AccountBrandRelationship` | End relationship | `account.brand.manage` | — | Soft — sets `status: ended`, never hard-deletes the relationship history |

### Deep-dive: `POST /people/resolve`

| Field | Value |
|---|---|
| Request schema | `{source_type, source_record_id, candidate_identity: {email?, linkedin_url?, name?, company_domain?}}` |
| Response schema | `{person_id, account_id, matched: bool, matched_rule, confidence, is_new_person}` |
| Permission | System-internal — called by the ingestion pipeline (lead_generation_specification.md §2-3), never directly by an external client |
| Org scope | Resolution is scoped within `org_id` — no cross-org identity matching |
| Idempotency | Required. Same `(source_type, source_record_id)` resolves to the same `person_id` every time, even under retry |
| Activity generated | One `identity_resolved` Activity, recording `matched_rule` and `confidence` — this is what makes "why did this event attach to this person" answerable, which v1 could never answer (data_lineage_map.md Domain 1) |
| State transitions | None on `Person` itself unless `is_new_person` — then one `Person` + `Account` pair is created |
| Validation | Resolution priority is fixed (lead_generation_specification.md §3: LinkedIn → email → domain+name); below-threshold matches do not auto-resolve — they return `matched: false` and route to a review queue, never silently create a duplicate or silently merge |
| Errors | `422` if `candidate_identity` has no usable field at all |
| Rate limit | Inherits ingestion pipeline's per-source cap (lead_generation_specification.md §14) |
| Concurrency | Resolution against a candidate under simultaneous review is serialized per `(source_type, source_record_id)` — two concurrent identical events must not create two people |
| External-provider behavior | N/A |

---

## 2. CRM Domain

| Method + path | Entity | Operation | Permission | Idempotent | Notes |
|---|---|---|---|---|---|
| `POST /leads` | `LeadRelationship` | Create (via ingestion, see lead_generation_specification.md §2) | `lead.create` | Required | Never called by an untrusted client directly — sources go through `/leads/ingest` |
| `POST /leads/ingest` | `RawLeadEvent` → `LeadRelationship` | Ingest | `lead.ingest` (per-source token) | Required | Full pipeline: §2-§3-§4-§5 of the lead-gen spec in one call chain |
| `POST /leads/{id}/qualify` | `LeadRelationship` | State transition | `lead.qualify` | — | `ENRICHING → QUALIFIED` or `→ DISQUALIFIED(reason)`. Reason is a closed enum (lead_generation_specification.md §7) — no free-text disqualification reasons, closing the "no maintained metric for gate attrition" gap (register §4.4) by construction |
| `POST /leads/{id}/assign` | `LeadRelationship` | State transition | `lead.assign` | — | `QUALIFIED → ASSIGNED` |
| `GET /leads/{id}/contactability` | — | Contactability check | `lead.read` | — | **Always evaluated live** against the canonical `Suppression` store — never reads a cached field on the lead itself (lead_generation_specification.md §9, the direct fix for the 41,746-enrollment incident) |
| `POST /leads/{id}/enroll` | `LeadRelationship` → `Campaign` enrollment | State transition | `lead.enroll` | Required | Requires `QUALIFIED + ASSIGNED + CONTACTABLE` re-evaluated at call time, not inherited from an earlier state read. Routes to the outreach domain's send facade only (§6) |
| `POST /opportunities` / `PATCH /opportunities/{id}` | `Opportunity` | Standard + stage transition | `opportunity.*` | create: required | Stage transitions validated against the closed enum |
| `POST /opportunities/{id}/convert` | `Opportunity` (won) | Convert to invoice draft | `opportunity.convert` | Required | Creates a `draft` `Invoice` referencing the opportunity — never an already-`sent` document |
| `GET /activities?subject_id=...` | `Activity` | List | `activity.read` | — | Cursor-paginated, the one canonical timeline read |

---

## 3. Finance Domain

Every mutating endpoint in this domain that touches an amount is money-schema-validated per schema_catalogue.md §0 — this closes D-33 (unvalidated payment JSON) and the client-controlled-`tax_amount` defect (register §1.1) at the type level, not by endpoint-specific logic.

| Method + path | Entity | Operation | Permission | Idempotent | Notes |
|---|---|---|---|---|---|
| `POST /invoices` | `Invoice` | Create (`draft`) | `finance.invoice.create` | Required | Line items validated server-side; `subtotal`/`tax_total`/`total` are always server-derived, never accepted from the client (closes the client-controlled tax defect) |
| `POST /invoices/{id}/submit` | `Invoice` | `draft → pending_approval` | `finance.invoice.submit` | — | |
| `POST /invoices/{id}/approve` | `Invoice` | `pending_approval → approved` | `finance.invoice.approve` | — | **[APPROVAL-GATED]** — see deep-dive |
| `POST /invoices/{id}/send` | `Invoice` | `approved → sent` | `finance.invoice.send` | Required | **The entity becomes immutable at this transition** — every field-level write attempt after this call is rejected at the service layer (closes the P0 "sent invoice freely rewritable" defect, register §1.3) |
| `PATCH /invoices/{id}` | `Invoice` | Update | `finance.invoice.update` | — | **Rejected with `409` if `status >= sent`.** Corrections after `sent` go through `POST /credit-notes`, never this endpoint |
| `POST /credit-notes` | `CreditNote` | Create | `finance.creditnote.create` | Required | **[APPROVAL-GATED]** — new entity, no v1 precedent (D-11) |
| `POST /bills`, `/estimates`, `/purchase-orders` | respective | Standard + same state-machine pattern as invoices | `finance.{entity}.*` | create: required | |
| `POST /payments` | `Payment` | Record a payment | `finance.payment.create` | **Required** | See deep-dive below — the direct fix for D-33 |
| `POST /payments/{id}/reverse` | `Payment` | Create linked reversal | `finance.payment.reverse` | Required | **[APPROVAL-GATED]** — v1 had no reversal path at all; a mis-keyed payment was permanent |
| `POST /expenses` | `Expense` | Create | `finance.expense.create` | Required | `approval_status` is **never** client-settable — always computed by the approval service, closing D-37 (self-approval-by-omitting-a-boolean) |
| `GET /accounts/{id}/statement` | `CustomerBilling`/`VendorProfile` | Derived statement | `finance.read` | — | Computed from the ledger at read time — never reads the old `total_receivables` `$inc` field, because that field no longer exists (it's `DERIVED` per schema_catalogue.md §3.1) |

### Deep-dive: `POST /invoices/{id}/approve`

| Field | Value |
|---|---|
| Request schema | `{}` (no body — the approver is the authenticated caller, never a request parameter) |
| Response schema | `{invoice_id, status: "approved", approved_by, approved_at, activity_id}` |
| Permission | `finance.invoice.approve`, evaluated through `RBACService.can_approve_amount(caller, invoice.total)` |
| Org scope | Standard |
| Idempotency | A second approval call on an already-approved invoice is a no-op `200`, not an error — but a call from a *different* approver than the one recorded is rejected |
| Activity generated | One `invoice_approved` Activity, immutable, naming the approver and the amount at time of approval |
| State transitions | `pending_approval → approved` only. Any other starting state is `409` |
| Validation | **Requester cannot approve their own invoice, regardless of role** (register §5.7's acceptance test #1). **Approver's ceiling must cover the amount** (acceptance test #2). **`admin` role does not bypass this check** — the approval permission is carved out of the admin wildcard per D-14/v2_locked_principles.md §5.7, closing the compound defect where fixing the auth resolver alone would still leave unlimited approval authority |
| Errors | `403` self-approval attempt; `403` ceiling exceeded; `409` wrong starting state |
| Rate limit | Default |
| Concurrency | `version`-checked; a concurrent edit to the invoice between submission and approval invalidates the approval request (register §5.7: material modification returns the document to `pending_approval`) |
| External-provider behavior | N/A |

### Deep-dive: `POST /payments`

| Field | Value |
|---|---|
| Request schema | `{invoice_id or bill_id, amount: {amount_minor: int, currency: str}, applied_to: [{invoice_id, amount}], idempotency_key}` — **`amount` is a typed money object, not `Dict[str, Any]`.** This alone closes D-33: there is no code path by which an unparsed string or NaN reaches Mongo, because the type system rejects it before the handler runs |
| Response schema | `{payment_id, status, balance_due_after: money, activity_id}` |
| Permission | `finance.payment.create` |
| Org scope | Standard; additionally validates `invoice_id`'s `account_id` matches the payment's declared payer — closing the "payment applied to any invoice regardless of customer" defect (register §1.4) |
| Idempotency | **Required, enforced at the database layer via a unique index on `idempotency_key`** — not merely documented, closing D-04 |
| Activity generated | One `payment_recorded` Activity |
| State transitions | May trigger the invoice's `sent → partially_paid` or `→ paid` transition as a **derived** consequence, computed from the ledger, never a separate `$inc` write that can drift from reality |
| Validation | `amount` cannot exceed remaining `balance_due` unless an explicit `allow_overpayment` flag is set and separately permissioned — v1 allowed unlimited silent overpayment (register §1.4) |
| Errors | `422` type/schema violation (structurally cannot be a string); `409` idempotency key reused with different payload; `403` account mismatch |
| Rate limit | Default |
| Concurrency | Two concurrent payments against the same invoice are serialized through the invoice's `version` field — the read-after-write race in v1 (register §1.4) is closed by requiring the second writer to retry against the updated balance, not silently double-apply |
| External-provider behavior | N/A (payment gateway integration, if any, is a separate provider-adapter concern not yet in scope) |

---

## 4. Panel / Rewards Domain

| Method + path | Entity | Operation | Permission | Idempotent | Notes |
|---|---|---|---|---|---|
| `POST /panelists/{id}/rewards/credit` | `RewardLedgerEntry` | Earn | `rewards.credit` (system, from survey completion) | Required | The bridge v1 never built (data_lineage_map.md §2.1) — a completed `SurveyResponse` produces exactly one `earned` ledger entry |
| `POST /panelists/{id}/rewards/redeem` | `RewardLedgerEntry` | Redeem | `rewards.redeem` | **Required** | See deep-dive — the endpoint that doesn't exist anywhere in v1 |
| `POST /panelists/{id}/rewards/clawback` | `RewardLedgerEntry` | Clawback | `rewards.clawback` | Required | **[APPROVAL-GATED]**, no self-approval (register §5.7 explicitly names clawback as always requiring approval) |
| `GET /panelists/{id}/rewards/balance` | — | Derived balance | `rewards.read` | — | Sum of ledger entries at read time — never a stored field |

### Deep-dive: `POST /panelists/{id}/rewards/redeem`

| Field | Value |
|---|---|
| Request schema | `{amount: money, method}` |
| Response schema | `{redemption_id, status: "pending"|"approved"|"paid", activity_id}` |
| Permission | `rewards.redeem` — the panelist redeeming their own balance, or an admin on their behalf |
| Org scope | Standard |
| Idempotency | Required — closes the "double-click redeems twice" gap that was moot in v1 only because no redemption endpoint existed at all |
| Activity generated | One `reward_redemption_requested` Activity, a second `reward_redemption_completed` on payout |
| State transitions | `pending → approved → paid`, or `pending → rejected` |
| Validation | **Balance can never go negative** — the redemption amount is checked against the derived balance at request time, and the ledger entry that debits it is the same atomic operation that checks it (no read-then-write gap) |
| Errors | `422` amount exceeds balance; `422` below minimum redemption threshold (per register B-13's currency/threshold decisions once resolved) |
| Rate limit | Per-panelist daily cap |
| Concurrency | Redemption requests for the same panelist are serialized — the balance check and the ledger debit happen inside one transaction |
| External-provider behavior | Payout method (gift card, bank transfer) is a provider adapter; failure does not silently mark the redemption `paid` |

---

## 5. Survey Domain

| Method + path | Entity | Operation | Permission | Idempotent | Notes |
|---|---|---|---|---|---|
| `POST /traffic/{id}/allocate` | `TrafficSource` → `Survey` | Allocate respondent | `survey.allocate` (system) | — | **The single, atomic allocation path** — v1 had two engines and production used neither correctly (register §2.0); v2 has exactly one, and this endpoint *is* it |
| `POST /surveys/{id}/callback` | `SurveyResponse` | Provider outcome callback | signed webhook | Required (`(provider, external_event_id)`) | **Signature-verified** — the direct fix for D-08 (v1's Cint outcome callback had zero signature verification, allowing forged completes) |
| `GET /surveys/{id}/metrics` | `Survey.metrics` | Derived read | `survey.read` | — | |
| `POST /suppliers/{id}/reconcile` | — | Reconciliation job trigger | `survey.reconcile` (system/cron) | — | **New — v1 had no reconciliation between Torpedo's counts and any supplier's** (D-defect, register §2.8/I-5). Surfaces disagreement, never silently corrects it |

### Deep-dive: `POST /traffic/{id}/allocate`

| Field | Value |
|---|---|
| Request schema | `{vendor_id, country_code, respondent_ref}` |
| Response schema | `{survey_id, redirect_url, allocation_id}` |
| Permission | System — called from the public traffic-redirect endpoint after its own rate-limit/fraud gates, never exposed directly |
| Org scope | N/A (single traffic namespace) |
| Idempotency | The allocation itself is not retried — a duplicate `respondent_ref` within the dedup window is rejected, not re-allocated (closing the entry-guard logic v1 had, correctly, and generalizing it past CPX per v2_locked_principles.md §1.10's D-21 finding — the fraud-guard mechanism survives even though CPX does not) |
| Activity generated | One `respondent_allocated` Activity |
| State transitions | Decrements the survey's quota **atomically** via `findOneAndUpdate` — this is v1's `SurveyAllocationService` pattern, which was architecturally correct and simply never wired to production (register §2.2); v2 makes it the only path, not an unused one |
| Validation | Quality-floor thresholds are config, not hardcoded per-branch magic numbers (register §2.3); country/quota checks happen inside the same atomic operation as the decrement, not as a separate read-then-write |
| Errors | `409` quota exhausted (race lost); `422` no eligible survey |
| Rate limit | Per-vendor, per-IP |
| Concurrency | This is the operation invariant I-3 exists for — two concurrent respondents cannot both win the last slot |
| External-provider behavior | The redirect URL is built through the provider adapter (§0); a provider timeout falls back to the next-best eligible survey, never to a hardcoded default survey |

---

## 6. Outreach Domain

**Every send-capable endpoint in this domain routes through the one canonical send facade — no exceptions.** This is the structural closure of the P0 finding that v1 had five send pipelines, two of which had zero suppression/budget/kill-switch enforcement (register §5.1, D-05/D-06).

| Method + path | Entity | Operation | Permission | Idempotent | Notes |
|---|---|---|---|---|---|
| `POST /campaigns` / `PATCH` | `Campaign` | Standard | `outreach.campaign.*` | create: required | |
| `POST /outreach/send` | `SendLogEntry` | Send one message | `outreach.send` | **Required** | See deep-dive — the single facade endpoint. **There is no second way to send mail in v2.** |
| `POST /suppressions` | `Suppression` | Add suppression event | `outreach.suppress` | Required | Appends to `events[]` — never overwrites (closes D-27) |
| `GET /suppressions/{email}` | `Suppression` | Check | `outreach.read` | — | The only read every send path is permitted to trust |
| `POST /outreach/kill-switch` | — | Global send gate | `outreach.admin` | — | **This document must exist and this is its only writer** — directly closes D-28 (v1's kill switch had a reader and no writer anywhere) |

### Deep-dive: `POST /outreach/send`

| Field | Value |
|---|---|
| Request schema | `{recipient_email, template_id or body, campaign_id, transactional: bool}` |
| Response schema | `{send_id, status: "sent"|"suppressed"|"budget_blocked", activity_id}` |
| Permission | `outreach.send` — held only by the send facade's internal callers, never granted broadly |
| Org scope | Standard, plus brand scope via `AccountBrandRelationship` where the recipient is tied to an account |
| Idempotency | Required — a retried send with the same key returns the original result, never sends twice |
| Activity generated | One `message_sent` (or `_suppressed`/`_budget_blocked`) Activity — the outcome is always recorded, even when nothing was sent, closing the observability gap where v1's non-facade pipelines left no trace at all |
| State transitions | None on the message itself beyond `SendLogEntry` creation |
| Validation, in order, atomically: | (1) global kill switch, (2) suppression check, (3) atomic per-identity/per-org budget check-and-increment (never read-then-write — this is the direct generalization of v1's one correctly-built atomic mailbox cap, register §5.3, made the *only* budget mechanism instead of one of two disagreeing ones), (4) CAN-SPAM footer construction for non-transactional mail, refusing to send rather than sending without one |
| Errors | `403` suppressed; `429` budget exhausted; `503` kill switch active |
| Rate limit | The budget check *is* the rate limit — not a separate middleware layer that can disagree with it |
| Concurrency | The budget increment is atomic (`findOneAndUpdate` + `$inc`), closing the race that let v1 overshoot its own 2,000-send daily cap (register §5.3) |
| External-provider behavior | Gmail/SES chosen by provider adapter based on the mailbox record; a provider failure returns `status: "failed"` with the provider error attached — never silently retried into a different provider without a new idempotency key |

---

## 7. Governance / AI Domain

| Method + path | Entity | Operation | Permission | Idempotent | Notes |
|---|---|---|---|---|---|
| `POST /ai/proposals` | `AiProposal` | Create (system, from a model call) | `ai.propose` (system) | Required | Every AI output that could change business state lands here first — never a direct write |
| `POST /ai/proposals/{id}/apply` | `AiProposal` | Apply | `ai.proposal.apply` | Required | **[APPROVAL-GATED]** for anything touching money, permissions, identity, or suppression (spec §28); auto-apply permitted only for pre-approved low-risk task classes |
| `POST /ai/proposals/{id}/reject` | `AiProposal` | Reject | `ai.proposal.reject` | — | |
| `GET /ai/usage` | — | Cost/usage read | `ai.admin` | — | Per spec §47/§53 — cost per 1,000 requests, per accepted proposal, GPU utilization |

No deep-dive needed beyond §0 and the Finance domain's approval pattern — this domain's entire design *is* "route everything through the same approval mechanism used everywhere else," which is the point.

---

## 7.5 Entities with no dedicated endpoint table above

`Task`, `Project`, `Brand`, `Message`/`Thread`, `Mailbox`, and `File` (schema_catalogue.md §2.4, §1.9, §6.2, §6.3, §7.2) get standard `POST`/`GET`/`PATCH` CRUD under the §0 governing rules with no domain-specific state machine or deep-dive — that's a deliberate omission, not a gap the reconciliation pass should treat as orphaned. `File` in particular is upload-via-presigned-URL per spec §34, not a body upload to this API.

## 8. What this catalogue leaves open

- Exact rate-limit numbers per endpoint class are policy, not architecture — deferred to ops configuration, consistent with schema_catalogue.md leaving B-11/B-14 open rather than defaulting them.
- Payment gateway provider adapter (§3, `POST /payments`) is named but not specified — no gateway integration has been decided yet; this is a Phase 3 detail, not a Phase 0 gap.

## What this unblocks

The Screen Catalogue (§32) can now map every screen's actions directly to a named endpoint here, rather than inventing a call shape per screen. After that, the final cross-document reconciliation pass (business rules ↔ entity map ↔ lineage ↔ schema ↔ endpoints ↔ screens) becomes possible for the first time, since it needs all six documents to exist before it can check for orphans and contradictions between them.
