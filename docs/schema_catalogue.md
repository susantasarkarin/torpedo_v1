# Torpedo v2 — Schema Catalogue (spec §30)

> Generated: 2026-09-05 | Phase 0 deliverable
> Depends on: [entity_map.md](entity_map.md) (entity list, dispositions), [data_lineage_map.md](data_lineage_map.md) (field-level provenance, PII, migration source), [lead_generation_specification.md](lead_generation_specification.md) (`LeadRelationship`), [v2_locked_principles.md](v2_locked_principles.md) (invariants), [business_rules_register.md](business_rules_register.md) (money/state-machine decisions)
> Precedes: Endpoint Catalogue (§31), Screen Catalogue (§32) — both reference the entities and fields defined here rather than inventing shapes inline.

## 0. Governing rules

Every canonical document in this catalogue carries these fields unless explicitly noted as a facet/embedded type that inherits them from its parent:

| Field | Type | Rule |
|---|---|---|
| `_id` | ObjectId | — |
| `org_id` | string (ref) | Mandatory per spec §8/§10, even for a currently-single-tenant deployment — v1's total absence of any tenancy field is why brand modeling failed (D-19). Scoping every query by `org_id` from day one is cheaper than retrofitting it. |
| `created_at` | datetime (UTC, tz-aware) | Mandatory. v1 mixed naive/aware and `utcnow()`/`now()` inconsistently (data_lineage_map.md D2, D3) — v2 stores tz-aware UTC only, no exceptions. |
| `created_by` | string (ref → AuthIdentity) | Mandatory. Present in only 6 of 48 v1 models (register, model-catalogue pass). |
| `updated_at` | datetime | Mandatory. |
| `updated_by` | string (ref) | Mandatory. **Present in 0 of 48 v1 models** — this is new discipline, not a migration. |
| `version` | int | Mandatory, optimistic-concurrency counter, incremented on every write. Present in 1 of 48 v1 models, and that one had non-standard semantics (AI classification revision, not document version). |
| `schema_version` | int | Mandatory. **Zero occurrences anywhere in v1.** |
| `deleted_at` | datetime \| null | Mandatory on every entity that supports soft delete (i.e., everything except pure log/event types, which are append-only and never deleted). v1 used three different field names for this (`deleted_at`/`is_deleted`/`is_archived`) with inconsistent pairing. |

**Money.** Every monetary field is `{amount_minor: int, currency: ISO4217 str}` — never a bare float, never a string, never a nested provider-shaped dict. This is invariant I-6 applied to the single defect category (float/string money) that appeared in every domain of the lineage map.

**Enums** are closed lists, versioned by the schema itself — no enum is a free string with a comment describing "allowed" values, which was the single most repeated defect pattern in the v1 model catalogue (CampaignStatus, EmailStatus, SeniorityLevel, ClassificationStatus each had 2-3 conflicting definitions).

**PII tiers**, carried over from the entity-map/lineage-map findings, applied consistently here:
- **Tier 1 — direct identifier**: email, phone, name, address, IP, government id, banking detail
- **Tier 2 — sensitive/special-category**: inferred protected characteristics, message content, device fingerprint, behavioral tracking
- **Tier 3 — secret**: credentials, tokens, API keys (never migrated per v2_locked_principles.md §3.4 — always re-issued)

**Ownership class** per entity uses the lineage map's classification: `AUTHORITATIVE` / `DERIVED` / `PROJECTION` / `HISTORICAL`.

---

## 1. Core Identity Domain

### 1.1 `Person`

*Replaces (per entity_map.md §2.1): `leads_enriched`, `leads_raw`, `panelists`, `vendor_leads`, `contacts` (both `crm_db` and `email_automation`), the person-subtype rows of `finance_db.customers`, `email_automation.users` (via `AuthIdentity` facet).*

| Field | Type | Null | Default | Enum | Class | PII | Notes |
|---|---|---|---|---|---|---|---|
| `primary_email` | string | no | — | — | AUTHORITATIVE | Tier 1 | Lowercased, trimmed. Unique per person, **not** the identity itself (I-6: no business identity depends on email — this is a contact channel, `person_id` is the identity) |
| `given_name`, `family_name` | string | yes | — | — | AUTHORITATIVE | Tier 1 | Collapses v1's three-field `first_name`/`last_name`/`name` overlap |
| `phone` | string | yes | — | — | AUTHORITATIVE | Tier 1 | |
| `linkedin_url` | string | yes | — | — | AUTHORITATIVE | Tier 1 | Normalized (protocol/www/query stripped). `mailto:` values rejected at migration (a v1 pollution — synthetic values written to satisfy a unique index) |
| `title`, `location`, `timezone` | string | yes | — | — | AUTHORITATIVE | Tier 1 (title only if role-identifying) | |
| ~~`identity_resolution_log`~~ | — | — | — | — | — | — | **Corrected during Phase 1 Slice 4 implementation (2026-09-05):** this catalogue originally specified an embedded log array here. Building it revealed that's a second, competing audit trail alongside `Activity` (§2.3) — exactly the pattern the register found and rejected in v1 (§2.7: two live `audit_log` collections, two orphaned governance logs). Resolution/merge decisions are recorded as `Activity` records instead (`type="identity_resolved"` / `"account_merged"`, `subject_id` = the person/account), never as a field on the entity itself. |
| *(gender, or any inferred protected characteristic)* | — | — | — | — | — | — | **Not modeled.** v1's AI-inferred `gender` field is `REJECTED` at the entity level, not just at migration — no v2 write path may persist an inferred protected characteristic without an explicit, separately-approved business requirement |

**Facets** (composable per locked principle 4 — never a copy, always a relationship to the same `person_id`):

### 1.2 `AuthIdentity` (facet)

**Corrected during Phase 1 Slice 5 implementation (2026-09-05):** `credential_hash`,
`roles[]`, and `mfa_enabled` below were the original spec, but building this facet
against the already-shipped `app/auth` module (Slices 2-3) revealed they'd be a
second copy of state `Credential`/`UserRole` already own — the exact "second source
of truth" pattern I-1 exists to forbid. The facet actually built is a pure **link**:
`{person_id, username}`, where `username` is the same string `Credential`/`Session`/
`UserRole` already key on. Credentials, roles, and MFA state stay owned by `app.auth`
and `app.rbac` respectively; this facet only answers "which Person does this login
identity belong to."

| Field | Type | Null | Class | PII |
|---|---|---|---|---|
| `person_id` | ref | no | AUTHORITATIVE | — |
| `username` | string | no, unique | AUTHORITATIVE | Tier 1 |

### 1.3 `LeadState` (facet)
Defined fully in [lead_generation_specification.md](lead_generation_specification.md) §7 (the qualification state machine) and §4 (enrichment provenance). Not restated here; referenced. Implemented in Slice 5 as `{person_id, account_id?, source_type, state, disqualify_reason?, owner?}` — deliberately excludes any `contactable`/`is_contactable` field, per §7's own corrected diagram (a stored contactability field is exactly the mistake that produced the 41,746-enrollment incident).

### 1.4 `PanelistProfile` (facet)

**Scope note (Slice 5):** only `{person_id, country, language, status}` are implemented so far — `double_opt_in_completed_at`, `external_state`, and the full sensitive `profile.*` block below remain specified but not yet built, per this slice's deliberate scope boundary ("establish attachment semantics, not full facet business logic" — the reward/panel vertical is Slice 6+). `status` is independent of `Person.status` by design, proven by `test_panelist_status_is_independent_of_person_status`.

| Field | Type | Null | Class | PII |
|---|---|---|---|---|
| `person_id` | ref | no | AUTHORITATIVE | — |
| `country`, `language` | string | yes | AUTHORITATIVE | Tier 1 |
| `status` | enum(`active`,`suspended`,...) | no, default `active` | AUTHORITATIVE | — |
| `double_opt_in_completed_at` | datetime | yes | AUTHORITATIVE | — | *(not yet implemented)* |
| `external_state` | object (SFW mirror) | yes | **PROJECTION** | — | Re-fetched, never authoritative (data_lineage_map.md §11 finding: `sfw_*` fields are a mirror) — *(not yet implemented)* |
| `profile.{dob, gender, income_range, ...}` | object | yes | AUTHORITATIVE | Tier 1/2 | Full sensitive profile set, gated by explicit consent capture (not modeled in v1 at all — new discipline) — *(not yet implemented)* |

### 1.5 `CustomerBilling` (facet) / `VendorProfile` (facet)

**Correction (Slice 5):** `VendorProfile` attaches to *either* `person_id` *or*
`account_id` (mutually exclusive, exactly one required) — v1 modeled the same
individual-vs-company vendor duality with a `customer_type: "individual"` fallback
flag layered over an otherwise account-shaped collection (data_lineage_map.md §2);
here it's two explicit reference fields instead. `CustomerBilling` stays
account-only, as originally specified. Both facets below are still minimal for this
slice — `gstin`/`pan`/`bank_details`/`credit_limit`/`total_receivables` are Finance
vertical scope (Slice 6+), not yet built.

| Field | Type | Null | Class | PII |
|---|---|---|---|---|
| `account_id` (CustomerBilling) / `person_id` **xor** `account_id` (VendorProfile) | ref | no | AUTHORITATIVE | — |
| `gst_treatment` | enum(`registered_regular`,`registered_composition`,`unregistered`,`export`,`sez`) | no, default `unregistered` | AUTHORITATIVE | — | Extended from v1's 3-value enum per B-01/§1.2 compliance requirement |
| `gstin`, `pan` | string | yes | AUTHORITATIVE | Tier 1 (tax id) | Format-validated at write, not just on one code path (v1: only the API path validated; CSV/AI paths didn't) |
| `bank_details.{account_number, ifsc, bank_name}` | object | yes | AUTHORITATIVE | Tier 1 (banking) | **Encrypted at rest** — v1 stored these in plaintext (data_lineage_map.md §2, D-26-adjacent finding) |
| `credit_limit`, `payment_terms_days` | money / int | yes | AUTHORITATIVE | — | |
| `total_receivables` / `total_payables` | money | — | **DERIVED** | — | Recomputed from the ledger, never `$inc`-maintained (v1's version drifted, mixed currencies with no FX normalization — D-38) |
| `opening_balance` | money | yes | AUTHORITATIVE | — | `[OPEN — B-14]` whether this folds into the derived total or stands alone |

### 1.6 `EmployeeRecord` (facet)
**New construction — does not exist in v1 in any form** (data_lineage_map.md Domain 1). Minimal viable shape: `person_id`, `department`, `manager_id`, `employment_status`. Full design deferred to whenever HR/staff-management scope is confirmed — not blocking Phase 1.

### 1.7 `Account`

*Replaces: `crm_db.accounts`, `sales_accounts`, `email_automation.accounts` ("Unified Account"), `finance_db.customers`/`vendors` (company subtype), `clients`.*

| Field | Type | Null | Class | PII |
|---|---|---|---|---|
| `name`, `name_normalized` | string | no | AUTHORITATIVE | — | `name_normalized` is a derived index field, not user-facing |
| `domain` | string | yes | AUTHORITATIVE | — | **Preferred match key over name** where available (entity_map.md §2.2 finding: v1 almost never keys companies by domain, and paid for it in duplicate accounts) |
| `industry`, `segment` | string | yes | AUTHORITATIVE | — | |
| `parent_account_id` | ref, self | yes | AUTHORITATIVE | — | Hierarchy, replacing v1's bolt-on `consolidate_accounts.py` script |
| `status` | enum(`active`,`merged`) | no, default `active` | AUTHORITATIVE | — | **Added during Slice 4 implementation.** `merged` is set exclusively by the merge operation, never accepted from a client — the direct fix for D-18, where v1's merge updated no external references and nothing distinguished a merged-away account from a live one |
| `merged_into` | ref, self | yes | AUTHORITATIVE | — | Set alongside `status="merged"`. Every resolution path must follow this to the primary before treating a match as live (`_follow_merge_chain` in `app/identity/service.py`) — this is what stops a merged account from being silently re-adopted, which is exactly what v1's nightly reconcile did |

### 1.8 `AccountBrandRelationship`

**New entity — does not exist in v1** (locked principle 5, D-19). This is the single most consequential new construction item in the schema, given the production incident it directly fixes.

| Field | Type | Null | Class | Notes |
|---|---|---|---|---|
| `account_id` | ref | no | AUTHORITATIVE | |
| `brand_id` | ref → `Brand` | no | AUTHORITATIVE | |
| `relationship_type` | enum(`prospect`,`client`,`vendor`,`churned`) | no | AUTHORITATIVE | |
| `status` | enum(`active`,`paused`,`ended`) | no, default `active` | AUTHORITATIVE | |
| `owner` | ref → Person | yes | AUTHORITATIVE | |
| *(no "first brand wins" constraint)* | — | — | — | An account may have any number of concurrent `AccountBrandRelationship` rows — this is the explicit reversal of v1's workaround, per locked principle 5 |

### 1.9 `Brand`
| Field | Type | Null | Class |
|---|---|---|---|
| `code` | enum(`sfw`,`cogentix`,`bimwave`, ...) | no | AUTHORITATIVE |
| `name`, `internal_domains[]` | string / string[] | no | AUTHORITATIVE |

---

## 2. CRM Domain

### 2.1 `LeadRelationship`
Fully specified in [lead_generation_specification.md](lead_generation_specification.md) (§7 state machine, §8 ownership, §9 contactability). Attaches to `Person` + `Account`; never a standalone copy. Not restated here.

### 2.2 `Opportunity`
*Replaces: `crm_db.opportunities`, `email_automation.rfqs` (superseded per entity_map.md §2.9 finding — `crm_db.opportunities` already declared the single source in v1's own code comments).*

| Field | Type | Null | Default | Enum | Class |
|---|---|---|---|---|---|
| `account_id`, `contact_id` | ref | yes | — | — | AUTHORITATIVE |
| `stage` | enum(`new`,`rfq`,`qualified`,`proposal`,`negotiation`,`won`,`lost`) | no | `new` | closed | AUTHORITATIVE |
| `amount` | money | yes | — | — | AUTHORITATIVE |
| `probability` | float 0-1 | yes | — | — | AUTHORITATIVE, constrained (v1's version was an unconstrained float) |
| `loss_reason` | string | yes | — | — | AUTHORITATIVE | Explicit `UNSET` sentinel semantics per the register's TOR-16 fix — `None` clears it, never ambiguous |

### 2.3 `Activity`
*Replaces: `crm_db.activities`, `email_automation.activities`, `crm_db.ai_decisions` (as a subtype), plus the entity-map's designated destination for v1's embedded email threads and click/open events (data_lineage_map.md §3.2 finding: click events belong in Activity, not as an unbounded array on a send record).*

| Field | Type | Null | Enum | Class |
|---|---|---|---|---|
| `type` | enum, closed | no | (email_sent, email_opened, call, note, status_change, ai_decision, ...) | AUTHORITATIVE |
| `subject_type`, `subject_id` | polymorphic ref | no | — | AUTHORITATIVE | Points at Person/Account/Opportunity/LeadRelationship/etc. |
| `actor_type`, `actor_id` | polymorphic ref | no | (`user`,`system`,`ai_agent`) | AUTHORITATIVE | Every automated transition names its actor — closes the "why does this value exist" gap (spec §29) |
| `payload` | object | yes | — | AUTHORITATIVE | Append-only; never mutated post-write |

One append-only stream. Not four competing audit stores.

### 2.4 `Task`, `Project`
*Replace v1's triple-store situation (`crm_db.projects`, `torpedo_settings.projects`, `email_automation` legacy) — one store each, per I-1.* Standard fields, no unusual findings beyond the general audit-field gap.

---

## 3. Finance Domain

Governing decisions already locked: B-01 (statutory GST issuer), B-05 (state machine, immutable at `sent`), B-07 (approval policy), all in the register.

### 3.1 `Invoice` / `Bill` / `Estimate` / `PurchaseOrder`

| Field | Type | Null | Default | Enum | Class | Notes |
|---|---|---|---|---|---|---|
| `number` | string | no | server-generated | — | AUTHORITATIVE | **Atomic sequence generation** (`findOneAndUpdate` counter, not `estimated_document_count()+1`) — v1's non-atomic generator is D-defect-class, already fixed in principle by I-3 |
| `status` | enum | no | `draft` | Per B-05: `draft→pending_approval→approved→sent→partially_paid→paid`; `overdue` is **derived**, never stored | AUTHORITATIVE | |
| `line_items[]` | array of `{item_id, description, quantity, unit_price:money, tax_rate, tax_amount:money}` | no | `[]` | — | AUTHORITATIVE | **One shape** — v1 had `items` vs `line_items` as two incompatible arrays depending on write path (D-36-adjacent) |
| `subtotal`, `tax_total`, `total` | money | no | — | — | **DERIVED** from `line_items` | Recomputed on every read/write, never independently settable — closes v1's "client posts arbitrary tax_amount" defect |
| `tax_breakdown.{cgst, sgst, igst}` | money | conditional | — | — | **DERIVED** | Per B-01 — computed from party GST treatment + state codes, not a flat `tax_rate` |
| `balance_due` | money | no | — | — | **DERIVED** | `total - sum(applied payments)`, never `$inc`-maintained directly |
| `currency` | ISO4217 | no | org default | — | AUTHORITATIVE | One default across the whole system — v1 had `INR` in most places and `USD` in the spine mirror (D unresolved inconsistency) |
| `immutable_after` | computed | — | — | — | — | Any field-level write attempt once `status >= sent` is rejected at the schema/service layer, not just by convention (fixes the P0 "sent invoice freely rewritable" defect) |
| `approval` | ref → approval record | conditional | — | — | AUTHORITATIVE | Per B-07's policy service — not reimplemented per-entity |
| `tds_amount` | money | `[OPEN — B-06]` | — | — | — | Not modeled — v1 only ever wrote this from a one-off Zoho CSV import, never from a live path (data_lineage_map.md §2, item 14.3). Whether TDS is a first-class v2 concept at all is still open; adding the field now would be defaulting an open decision, which this catalogue deliberately avoids elsewhere (§8) |

### 3.2 `CreditNote`
**New entity — does not exist in v1 in any form** (register §1.6, D-11). Required by B-01. Fields mirror `Invoice` with an added `original_invoice_id` and `reason` (enum, closed).

### 3.3 `Payment`
| Field | Type | Null | Class | Notes |
|---|---|---|---|---|
| `amount` | money | no | AUTHORITATIVE | **Schema-validated, not raw client JSON** — directly closes D-33 (unvalidated `amount` corrupting four fields via blind `$inc`) |
| `applied_to[]` | array of `{invoice_id, amount:money}` | no | AUTHORITATIVE | Supports partial/split application; v1 allowed unchecked overpayment with no cap |
| `idempotency_key` | string | no | AUTHORITATIVE | Unique-indexed — v1 had none (D-04) |
| `reversal_of` | ref, self | yes | AUTHORITATIVE | **Payments are reversible via a linked reversal record, never mutated or deleted** — v1 had no void/reversal path at all |

### 3.4 `Expense`
| Field | Type | Null | Default | Class |
|---|---|---|---|---|
| `amount` | money | no | — | AUTHORITATIVE |
| `approval` | ref → approval record | conditional | — | AUTHORITATIVE | Per B-07 — **no self-approval-by-omission**, closing D-37 where v1 defaulted to `"approved"` unless a client explicitly flagged otherwise |

---

## 4. Panel / Rewards Domain

### 4.1 `RewardLedgerEntry`
**New entity — 100% greenfield per data_lineage_map.md §2.1 (`panel_rewards` has zero write sites in v1).**

| Field | Type | Null | Enum | Class |
|---|---|---|---|---|
| `person_id` | ref | no | — | AUTHORITATIVE |
| `type` | enum(`earned`,`redeemed`,`clawback`,`expired`) | no | closed | AUTHORITATIVE |
| `amount` | money | no | — | AUTHORITATIVE | Append-only |
| `source_activity_id` | ref → Activity | yes | — | AUTHORITATIVE | Links a completed survey response to the credit it produced |
| `balance` | — | — | — | **DERIVED, never stored** | Sum of ledger entries at read time — per I-3, this is the fix for v1's permanently-`0.0`, never-incremented `rewards_balance` field |

---

## 5. Survey Domain

### 5.1 `Survey`
*Replaces (merged, per entity_map.md §2.6): `cint_research.cint_surveys` (provider-owned fields re-fetched, Torpedo-owned fields migrated per data_lineage_map.md §4.2), `survey_allocation.surveys` (dead, not migrated). CPX: removed entirely.*

| Field | Type | Null | Class | Notes |
|---|---|---|---|---|
| `provider` | enum(`cint`, ...) | no | AUTHORITATIVE | Provider-adapter boundary (spec §17) — adding a second provider must not touch domain logic |
| `external_id` | string | no | AUTHORITATIVE | One name, one type (v1 had `survey_id` as both `int` and `str`, plus a fourth alias `external_id`) |
| `quota_remaining`, `cpi`, `conversion_rate` | int / money / float | yes | **PROJECTION** | Provider-owned, re-fetched, explicitly labeled stale-risk if not refreshed within a defined window |
| `eligibility.{is_active_in_pool, activated_at}` | object | — | AUTHORITATIVE | Torpedo-owned decision, migrated (not re-fetched) per data_lineage_map.md §4.2 |
| `cold_start_score` | object `{score, confidence, model_version}` | yes | AUTHORITATIVE | AI-generated; provenance-tagged per lead_generation_specification.md §6 pattern applied here too |

### 5.2 `SurveyResponse`
*Replaces `cint_research.cint_respondent_outcomes` — migrated in full per data_lineage_map.md §4.2 (Cint's outcomes subscription is push-only, no history endpoint; this is Torpedo's only copy).*

| Field | Type | Null | Class | PII |
|---|---|---|---|---|
| `respondent_ref` | string | no | AUTHORITATIVE | Tier 1 |
| `final_status` | enum(`complete`,`terminated`,`overquota`,`quality_term`) | no | AUTHORITATIVE | — |
| `payout` | money | yes | AUTHORITATIVE | — | With currency — v1's version defaulted currency to `"USD"` when the source object was absent, a guess on a money field |

### 5.3 `Supplier`, `TrafficSource`
Standard entities per entity_map.md §2.6/§2.9. `TrafficSource` replaces `traffic_flow_db.url_parameters` with the three type/casing inconsistencies (D2 in the lineage map) normalized at the schema level, not left to application discipline.

---

## 6. Outreach / Email Domain

### 6.1 `Suppression`
*Merges the three v1 stores per data_lineage_map.md §3.1 — safe because every enforcement read only ever checked `email`.*

| Field | Type | Null | Enum | Class |
|---|---|---|---|---|
| `email` | string | no | — | AUTHORITATIVE |
| `events[]` | array of `{reason, source, actor, occurred_at}` | no, default `[]` | reason: closed enum, one vocabulary | **AUTHORITATIVE, append-only** | Directly resolves B-10 as an append-only event list — v1's `$set`-overwritten single `reason` field destroyed the record of *why* an address was suppressed (D-27) |
| `currently_suppressed` | bool | — | — | **DERIVED** | `true` iff `events` is non-empty; never independently set |

### 6.2 `Message` / `Thread`
*Replaces `email_sync.EmailDocument`, `outreach_engine.EmailSend` body fields, and the 300-char reply snippet v1 persisted into the send log.*

| Field | Type | Null | Class | PII |
|---|---|---|---|---|
| `body_html`, `body_plain` | string | per B-11 | AUTHORITATIVE | Tier 2 | **Retention policy explicit, not accidental** — `[OPEN — B-11]` on whether bodies are retained at all and for how long. Schema supports either answer; the field exists conditionally on that decision, not by default |
| `raw_headers` | object | no, minimal | AUTHORITATIVE | Tier 1 (contains IP) | Stripped to routing-relevant headers only — v1 stored the full `Received:` chain "for debugging" |

### 6.3 `Campaign` / `SendLogEntry` / `Mailbox`
One shape each (I-1) — v1 had 2-3 competing schemas per collection (data_lineage_map.md §3.2). `Mailbox.credentials_id` references a secrets store by indirection; **no credential field is ever stored on the entity itself** (closes D-26).

---

## 7. Governance / AI Domain

### 7.1 `AiProposal`
Per spec §28's pipeline. `{task, model, model_version, prompt_version, confidence, input_digest, proposed_change, status(pending/approved/rejected/auto_applied), decided_by}`. No AI-touched field anywhere in this catalogue is written outside this record's approval flow.

### 7.2 `File`
Object storage reference only — `{storage_key, checksum, mime_type, scan_status, uploaded_by}`. Never bytes in Mongo (v1 mostly followed this already; formalized here).

---

## 8. What this catalogue leaves open

- **B-11 (message body retention)** gates the final shape of `Message` — noted inline rather than blocking the rest of the catalogue.
- **B-14 (opening balance)** gates one field on `CustomerBilling` — same treatment.
- **B-06 (is TDS deduction required)** gates whether `Invoice`/`Bill` carry a `tds_amount` field at all — same treatment (§3.1), added during the six-document reconciliation pass since the original catalogue omitted it silently rather than marking it open.
- `EmployeeRecord` (§1.6) is a placeholder pending confirmed HR scope — not a Phase 1 blocker since nothing else references it yet.

## What this unblocks

The Endpoint Catalogue (§31) can now define every operation against named entities and fields instead of inline shapes — each endpoint's request/response contract, permission requirement, and idempotency behavior references this document rather than restating it.
