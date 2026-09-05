# Torpedo v2 — Backend

Phase 1 canonical foundation. Built against the specification in `../docs/`:
`business_rules_register.md` (defects/decisions), `entity_map.md`, `data_lineage_map.md`,
`schema_catalogue.md` (§30), `endpoint_catalogue.md` (§31), `screen_catalogue.md` (§32),
`v2_locked_principles.md` (ten locked architecture principles), `phase0_reconciliation.md`
(Phase 0 closure record).

## What this is not

This is not a rewrite-in-place of `../backend/` (v1). v1 stays running and unmodified by
this directory. v2 is built fresh against the reconciled specification, then v1 is migrated
into it per `data_lineage_map.md`'s field-by-field lineage — not copied.

## Stack

Python (FastAPI + Motor), matching v1's language for migration-tooling continuity and the
existing AI-gateway/GPU-broker Python code in `../backend/ai_governance/` and
`../backend/infra/`, per the 2026-09-05 stack decision.

## Status

Phase 1, slice 1: canonical document base (`app/models/base.py`), money value object
(`app/models/money.py`), centrally-declared config/db topology (`app/config.py`,
`app/db.py`). This slice exists to make two of the register's highest-severity findings
structurally impossible to reintroduce, before any domain model is built on top of it:

- **I-6** (`business_rules_register.md` §0.1): "No write path may persist data that has not
  passed through a canonical, collection-bound model." `CanonicalDocument` is that
  enforcement point — see `app/models/base.py`.
- **D-16/D-21** (database topology ambiguity / runtime-selected databases): `app/config.py`
  declares exactly one database name, read once at startup from one env var, with no
  per-module override and no request-supplied database parameter. `app/db.py` exposes a
  single pooled Motor client — no code outside this file may construct `AsyncIOMotorClient`
  directly (locked principle 2, `v2_locked_principles.md`).

**Phase 1, slice 2 (this security-boundary slice): `app/rbac/`** — identity resolution,
permission checks, and approval separation, in one policy service per register §5.7
("no approval logic may be reimplemented inside the invoice, payment, expense, bill,
credit-note, or reward services — all of them call the same policy service"). Tested
directly against the register's own historical findings, not generic RBAC scenarios:

- **D-01** — `RBACService.resolve_identity()` never returns a default role. A user
  with zero `UserRole` grants resolves to zero permissions; v1's operative resolver
  returned `roles=["admin"]` for any verified session token regardless of the database.
- **D-14** — `RBACService.can_approve()` never treats the admin wildcard as approval
  authority. Fixing D-01 alone (a correct resolver) is not sufficient on its own — an
  unqualified wildcard would still silently confer approval the moment real roles
  resolve — so the wildcard is excluded from `APPROVAL_PERMISSIONS` structurally, not
  by convention.
- **register §5.6** self-assignment gap — `assign_role()` refuses a caller granting a
  role to themselves, unconditionally, before the permission check even runs.
- **register §5.7** separation-of-duties rules — self-approval, impersonation, and
  AI/system principals are all refused in the one `can_approve()` method, using
  `real_actor_id` (not `user_id`) specifically so an impersonation session can't be
  used to approve a request its real actor created.

There is no `RBAC_ENABLED` flag anywhere in this module, deliberately — v1's flag
defaulted to `false` and its existence was what let checks be skipped in production.

**Phase 1, slice 3: `app/auth/`** — the session/token boundary that slice 2 deliberately
started after. Closes D-01 **end-to-end**, not just at the service layer: the full chain
`Authorization header -> AuthService.verify_token() -> user_id -> RBACService.resolve_identity()
-> ResolvedIdentity -> permission decision` is now exercised by an actual HTTP request in
`tests/test_auth_dependencies.py::test_d01_end_to_end_fresh_user_is_never_treated_as_admin`
— the one test in this codebase that would fail outright against a resolver shaped like
v1's operative one.

Design choices worth knowing before building on top of this:

- **Session tokens are opaque random strings, never JWTs or anything claims-bearing.**
  This is deliberate, not an oversight — a claims-bearing token invites embedding
  roles/org/permissions *in the token*, which is exactly the failure mode being avoided.
  Every request re-resolves permissions from `RBACService` fresh; a permission change
  takes effect on the caller's next request, not their next login.
- Only a SHA-256 hash of the token is stored (fast hash — the token is already 256 bits
  of random entropy, unlike a password). Passwords use Argon2id (`app/auth/passwords.py`,
  spec §48) — deliberately a *different, slow* hash, because passwords are low-entropy
  and guessable in a way tokens aren't.
- **401 vs 403 are two different dependencies, not two branches of one function** —
  `get_current_identity()` can only raise 401; `require_permission()` can only raise 403.
  A route can't blur the two by construction.
- Impersonation is real (`Session.impersonated_by`), gated behind `rbac.permissions.IMPERSONATE`,
  and cannot be nested. `ResolvedIdentity.real_actor_id` (not `user_id`) is what
  `RBACService.can_approve()` checks, so an impersonation session can never be used to
  approve a request its real actor created.
- **Bug found and fixed while building this**: PyMongo/Motor decode stored datetimes as
  *naive* UTC by default, silently dropping the tzinfo every write in this codebase
  attaches — caught by the session-expiry tests (`can't compare offset-naive and
  offset-aware datetimes`). Fixed once, at the client (`app/db.py`, `tz_aware=True`),
  not per call site — this was the same defect class (naive vs. aware datetimes) v1 had,
  reintroduced by the driver's default rather than by application code.

**Phase 1, slice 4: `app/identity/`** — the canonical identity layer, and the first
real business-domain routers in v2 (`/api/v1/people`, `/api/v1/accounts`), mounted in
`app/main.py`. `Person` and `Account` are the entities everything else attaches to as
a facet or relationship (locked principle 4) — no facet is built yet; this is the
foundation they attach to.

- **Confidence-tiered resolution, never a silent merge below threshold.**
  `IdentityService.resolve_person`/`resolve_account` implement the priority order
  register §4.7 already proved works (LinkedIn 1.0 → email 0.95 → name+domain 0.85 for
  people; domain 1.0 → normalized-name 0.75 for accounts), with everything below
  `AUTO_MATCH_THRESHOLD` (0.90) returned as a **review candidate**, never applied
  automatically. `tests/test_identity_resolution.py` is explicit that some cases
  (two emails, no shared key) correctly produce two `Person` records — that's the
  honest boundary of what's resolvable without more data, not a bug.
- **`AccountBrandRelationship` has no "one brand per account" constraint anywhere** —
  the direct reversal of v1's workaround (D-19), proven by
  `test_account_can_have_multiple_concurrent_brand_relationships`.
- **Merge repoints every known external reference and can't be silently undone.**
  `merge_accounts()` re-points `AccountBrandRelationship` rows before marking the
  loser, and `_follow_merge_chain()` means any later resolution that lands on a
  merged-away record redirects to the primary — the direct fix for D-18, where v1's
  reconcile re-adopted merged accounts as fresh ones because nothing checked status.
  `test_post_merge_loser_cannot_be_resurrected_by_resolution` is the regression test.
- **Org isolation proven through the real HTTP chain**, not just the service layer —
  `test_org_isolation_through_the_actual_http_security_chain` creates a person as one
  authenticated org-A user and confirms a fully-permissioned org-B user gets a 404
  (not 403 — see the comment in `routers.py` on why that distinction matters).
- Scope deliberately excludes: `PATCH` endpoints (same pattern as
  `CanonicalRepository.update`, already proven in Slice 1 — not a fresh design
  question), the brand-relationship HTTP sub-resource (exercised at the service layer
  only), and approval-gating on `POST /accounts/merge` (the endpoint catalogue marks
  merge `[APPROVAL-GATED]`, but `RBACService.can_approve()` requires a Money ceiling
  that has no natural meaning for "merge two accounts" — wiring this needs its own
  non-monetary approval concept, tracked as follow-up rather than faked with a
  placeholder amount).
- **Bug found and fixed while building this**: `create_account`'s domain-normalization
  had a conditional that left `domain` both popped and not-popped depending on branch,
  crashing with a duplicate-keyword `TypeError` the moment a caller omitted a domain.
  Caught immediately by the test suite, not left for a caller to find.

**Phase 1, slice 5: `app/identity/facets.py` + `facet_service.py`** — the composable-
roles layer (locked principle 4). Six facets (`LeadState`, `PanelistProfile`,
`CustomerBilling`, `VendorProfile`, `EmployeeRecord`, `AuthIdentity`), one
`FacetService` that is the only thing allowed to construct any of them.

- **A facet can never create an independent identity.** Every `attach_*` method
  validates its parent `Person`/`Account` exists — and isn't itself merged-away —
  before creating anything. `test_attaching_to_nonexistent_parent_is_rejected` and
  `test_merged_account_cannot_be_resurrected_through_facet_creation` are the two
  regression tests; the second is the facet-attachment version of D-18 (a resolution
  guard alone wasn't enough — attachment needed its own).
- **`org_id` is derived from the parent, never a parameter** — there is no `org_id`
  argument on any `attach_*` method to get wrong, the same "authoritative, never
  caller-selected" pattern used for identity resolution and every permission check
  since Slice 2.
- **Merge now repoints facets too, via a `Protocol`, not a hardcoded list.**
  `IdentityService` gained `AccountReferenceRepointer` — anything that holds an
  `account_id` and wants to survive a merge implements one method and gets passed in
  at construction (`extra_account_repointers=[facet_service]`). `IdentityService`
  still knows nothing about `CustomerBilling` or `VendorProfile` by name — the
  dependency runs the right direction (facets depend on identity, not vice versa).
- **Two structural guard tests encode the invariants most likely to erode silently**:
  `test_no_scalar_brand_field_exists_on_any_facet` (inspects every facet model's
  fields directly — the exact regression class behind the 41,746-enrollment
  incident) and `test_lead_state_has_no_stored_contactability_field` (guards the
  contradiction the Phase 0 reconciliation pass already found and fixed in the spec
  from ever recurring in the actual model).
- `AuthIdentity` is a pure link (`{person_id, username}`), not a copy of what
  `Credential`/`UserRole` already store — building it against the already-shipped
  auth module surfaced that the originally-specified `credential_hash`/`roles[]`/
  `mfa_enabled` fields would have been a second source of truth for state Slices 2-3
  already own correctly. Caught and corrected in `docs/schema_catalogue.md` before
  it became a real duplication, not after.
- Deliberately excluded from this slice, per the "attachment semantics, not facet
  business logic" scope boundary: reward balances, invoice totals, GST fields on
  `CustomerBilling`, full panelist profile/consent fields, and — most deliberately —
  **person-level merge**. Facets reference `person_id`, but there is no
  `merge_people()` yet; that's its own design question, not an accidental gap.

**Phase 1, slice 6: `app/leadgen/`** — the first full vertical, exercising nearly
every foundational piece built so far (identity resolution, facets, RBAC, org
isolation) against one real pipeline: ingest → enrich/qualify → assign → enroll.

- **Architectural gate stated at the top of `app/leadgen/models.py` and held
  throughout**: every write terminates at `LeadGenService`, which itself only writes
  through `CanonicalRepository`/`IdentityService`/`FacetService`. No `db["..."]`
  appears anywhere in this package outside `routers.py`'s provider function.
- **`LeadState` (Slice 5's facet) carries the state machine, not a new parallel
  entity** — `lead_generation_specification.md` §7 was the piece Slice 5
  deliberately left open; this slice fills it in rather than duplicating the facet.
- **AI proposes, the deterministic scorer decides — proven, not just asserted.**
  `test_ai_confidence_alone_cannot_qualify_a_lead` feeds a 0.95-confidence proposal
  with zero qualifying signal and confirms the lead still disqualifies.
  `test_enrichment_ai_outage_never_becomes_qualified_or_disqualified` confirms an
  outage leaves the lead genuinely unresolved (`ENRICHING`, not silently promoted
  either direction) — invariant I-4, enforced by a dedicated `AIUnavailable`
  exception type, not a low-confidence return value a caller could forget to check.
- **The canonical ICP scorer (`scoring.py`) ports B-04's exact decision** — v1's
  3/2/2/1 weights, the empty-industry guard, `QUALIFY_THRESHOLD = 4` — as the one
  scorer, with the module docstring explicit that multi-ICP tie-breaking (the
  *other* v1 incident fix) is deferred, not skipped, until ICP profiles are a
  managed entity.
- **Contactability is checked live at enrollment, not inherited from qualification**
  — `test_contactability_change_after_qualification_is_reflected_at_enrollment`
  qualifies and assigns a lead, suppresses it afterward, and confirms enrollment
  still fails. Backed by a genuinely minimal `Suppression` model (append-only
  `events[]`, the direct structural fix for D-27), deliberately **not** the full
  outreach/suppression vertical — that's its own future slice.
- **Multi-brand enrollment has no "first wins" constraint** — same principle as
  Slice 4's `AccountBrandRelationship`, now applied to lead enrollment via a
  `LeadEnrollment` row per `(lead, brand)` pair rather than a scalar field on the lead.
- **Merge integration reused, not reinvented** — `IdentityService.ensure_brand_relationship`
  (find-or-create, idempotent) is new; the `AccountReferenceRepointer` protocol from
  Slice 5 needed no changes at all for this slice to plug into it.
- Concurrency and idempotency are proven by reusing Slice 1's own mechanisms as this
  pipeline's regression tests (`VersionConflict` on a stale assign; a duplicate
  `(source_type, source_record_id)` or `(lead, brand)` returning the existing record)
  — not reimplemented per-pipeline.
- **DLQ is real**: a failure mid-ingest is recorded to `DeadLetterEvent` *and*
  re-raised to the immediate caller — recorded for later retry, never silently
  swallowed, never silently dropped either.
- **Fixed alongside Slice 7 (tiny hardening item, not a blocker)**: `ingest()` now
  threads `payload.get("title")` through `resolve_person()` into `Person.title` on
  creation — closing the gap noted above. `country` remains untracked; no source
  supplies it yet.
- Person-level merge remains explicitly out of scope, per the user's own
  instruction — `LeadState.person_id` references a `Person`, but there is no
  `merge_people()` anywhere in this codebase.

**Phase 1, slice 7: `app/outreach/`** — the messaging vertical, built as the first of
a three-slice coordinated wave (Outreach → Finance → Survey/Panel), each built and
tested before the next starts. Collapses the register's two competing send pipelines
(D-05, D-06) into one `MessagingFacade.send()` path with no bypass of any gate.

- **`Suppression` and `AiProposal` relocated here from `app/leadgen/`, not
  duplicated.** Both were built in Slice 6 for that slice's one caller; Slice 7 needed
  the same suppression check and the same AI-proposal record for drafting, and a
  second implementation of either would have been exactly the I-1 violation this
  codebase exists to prevent. `Suppression`/`SuppressionService` now live in
  `app/outreach/suppression.py` (their architecturally correct home — outreach is the
  domain that owns sending, leadgen only needs to *ask* whether an address is
  contactable); `AiProposal` moved to `app/models/ai_proposal.py` (app-level,
  cross-domain, per `schema_catalogue.md` §7.1, which always specified it there).
  `app/leadgen/service.py` now imports both from their new locations — nothing about
  Slice 6's behavior changed, only where the shared code lives.
- **One send path, no exceptions, no bypass flag** — `MessagingFacade.send()` runs
  every gate (idempotency replay, mailbox lookup, kill switch, suppression, content
  resolution, CAN-SPAM footer, budget reservation, provider dispatch, unified log) in
  a fixed order for every caller. The register's P1 list names "test-send bypasses
  kill switch" as its own defect — there is no test-send parameter here to bypass.
- **`KillSwitchService` is the D-28 fix**: v1's kill switch was read and failed safe
  to *paused* when its document was missing, but nothing ever wrote it — the register
  suggests this explains the standing outreach pause. The fail-safe-to-paused default
  is *kept* (it's correct, and matches this codebase's existing "no verifiable channel
  = fail closed" philosophy); what's new is `pause()`/`resume()` actually exist.
  `test_send_blocked_by_default_when_kill_switch_has_no_writer_yet` proves the default
  still holds even with a real writer built; `test_kill_switch_resume_actually_writes_and_unblocks`
  proves the writer works.
- **`BudgetService` is the atomic-reservation fix for §5.3's "non-atomic shared
  budget" / "Pipeline 5 budget race"** — a deliberate, documented, narrow exception to
  "every write goes through `CanonicalRepository`" (see the module docstring for why
  `update()`'s version-match semantics can't express a conditional atomic
  upsert-increment-with-cap, and why the exception is auditable rather than a
  loophole). Atomicity comes from MongoDB's own single-document `$inc` guarantee, not
  from anything this service adds — `test_budget_cap_enforced_atomically_across_sends`
  and `test_budget_reservation_released_after_provider_failure` are the regression
  tests, the second proving a failed send doesn't permanently burn cap a retry needs.
- **`Mailbox.credentials_id` is the only field a real mailbox has for authentication
  material** — the direct structural fix for D-26 (v1 stored SMTP passwords, AWS
  keys, and a full Gmail service-account JSON in cleartext, and one endpoint even
  echoed a secret key back to its caller). `test_mailbox_model_has_no_field_that_could_hold_a_secret`
  asserts the model's own field set, not just runtime behavior, so a secret field
  re-added later fails immediately rather than needing a behavioral test to catch it.
- **`record_bounce()` is the D-07 fix** — a provider-reported bounce is suppressed
  through the same canonical `SuppressionService` every send path already checks, not
  a side table other pipelines never consult (register: "hard-bounced addresses stay
  mailable elsewhere"). `test_record_bounce_propagates_to_canonical_suppression`
  proves a bounce actually blocks a subsequent send to that address.
  `test_suppression_reason_is_appended_not_overwritten` is Slice 6's D-27 regression
  test, re-run against the relocated module to prove the move didn't lose it.
- **AI drafting behind the same gateway boundary as `app.leadgen.ai`** —
  `MessageDrafter`/`DraftUnavailable` mirror `AIClassifier`/`AIUnavailable` exactly.
  The property proven, not just asserted: drafted content passes through every gate a
  caller-supplied `subject`/`body` would — `test_drafted_content_still_blocked_by_suppression`
  and `test_drafted_content_still_subject_to_footer_check` both assert the fake
  provider is never called when drafted content should have been blocked.
- **CAN-SPAM footer check is deliberately minimal** — a literal `"unsubscribe"`
  substring must appear in a non-transactional body, exempting `transactional=True`.
  Not a compliance engine (no physical-address check, no `List-Unsubscribe` header);
  the property this slice proves is that the check exists and applies uniformly,
  including to drafted content, not that it's exhaustive.
- **Idempotency caveat stated once, in `service.py`'s module docstring, not left
  implicit**: dedup is a `find_one` lookup before insert, not a unique-index
  constraint — correct for sequential retries, not for true concurrent
  double-submission of the same key, which needs an index this codebase doesn't
  build yet (same caveat as `BudgetService`'s natural-key design).
- Deliberately excluded from this slice: a real SMTP/SES/Gmail adapter
  (`SendProvider` is a `Protocol`, tested against fakes and a `StubSendProvider` HTTP
  stand-in — swapping in a real one is a one-line change to `get_send_provider()`);
  campaign/sequence entities; bounce *ingestion* (a webhook that calls
  `record_bounce()` for you) — `record_bounce()` itself is built and tested, but
  nothing calls it yet from a real provider callback.

**Phase 1, slice 8: `app/finance/`** — Invoice/Bill/Payment/Expense/CreditNote,
built against `endpoint_catalogue.md`'s already-deep-dived Finance section rather
than reinvented: the `draft -> pending_approval -> approved -> sent` invoice
lifecycle, the idempotent-same-approver / rejected-different-approver approval
semantics, and the payment request shape all follow that spec directly.

- **Two different approval checks, used for two different shapes of gate** —
  `RBACService.can_approve()` (two-actor, self-approval-blocked) gates
  `approve_invoice`/`approve_bill`/`reverse_payment`/`approve_expense`, each of which
  has a distinct creator and approver; `RBACService.get_approval_ceiling()`
  (single-actor, no creator/approver split) gates `issue_credit_note`, matching the
  catalogue's single `[APPROVAL-GATED]` creation endpoint rather than inventing a
  submit/approve lifecycle credit notes were never specified to have.
- **D-33 closed by construction, not by validation logic**: `Payment.amount` is a
  `Money`, so `record_payment("abc", ...)` cannot compile a request — the type system
  rejects it before any handler runs. `test_payment_amount_cannot_be_a_non_numeric_string`
  is the direct regression test. Overpayment is refused unless `allow_overpayment=True`
  is explicit (the "unvalidated overpayment" P1 finding); reversal is a real,
  auditable state transition (`Payment.status: recorded -> reversed`), never a delete.
- **D-11 closed the same way Slice 7 closed D-27**: `InvoiceService`/`BillService`
  expose no method that can ever change `line_items`/`subtotal`/`tax_total`/`total`
  after creation — corrections go through `CreditNoteService`, a real instrument, not
  a rewrite. `test_apply_credit_note_reduces_balance_but_never_touches_totals` and
  `test_recording_a_payment_never_mutates_invoice_totals` both assert the untouched
  fields directly, not just the changed ones.
- **D-10 (GST structure)**: `GstDetails.is_reverse_charge`/`is_export`/`is_sez`/
  `lut_number` are real fields on the issued document, not inferred after the fact —
  deliberately not a full tax-rules engine (no HSN/SAC-to-rate lookup); `gst_rate_bps`
  is supplied per line, not derived.
- **D-35 (shared payment-number counter) closed by `SequenceService`** — same
  atomic-`$inc`-on-one-document pattern as `app.outreach.budget.BudgetService`,
  applied to document numbering: `RCV`/`PAY`/`INV`/`BILL`/`CN` each get their own
  counter key, so incrementing one can never skip or collide with another.
  `test_payment_numbers_never_collide_across_directions` is the direct regression
  test.
- **D-37 closed structurally, not just behaviorally**: `ExpenseService.create_expense`
  has no `approval_status`/`requires_approval` parameter at all —
  `test_expense_service_never_accepts_approval_status_from_a_caller` inspects the
  method signature directly, so a parameter re-added later fails immediately rather
  than needing a behavioral test to catch it. The server computes both fields from an
  auto-approve ceiling (`EXPENSE_AUTO_APPROVE_CEILING`, a documented placeholder — no
  configurable-per-org ceiling entity exists yet, same deferred-config pattern as
  `app.leadgen.routers`'s `_DEFAULT_ICP_PROFILE`).
- **D-26 pattern reapplied to bank data**: `BankAccount.account_details_ref` is the
  only field a bank account has for authentication material — the same indirection as
  `app.outreach.models.Mailbox.credentials_id`, and the same kind of model-shape
  regression test (`test_bank_account_model_has_no_field_that_could_hold_a_secret`).
- **D-38's class of defect avoided by design, not by validation**: there is no
  `total_receivables`/`total_payables` rollup scalar anywhere in this slice for a
  `$inc` to drift out of sync with — reporting would query `Invoice`/`Bill`
  directly. `Money.__add__` (Slice 1) already refuses to add mismatched currencies,
  closing the FX-normalization half of the same defect.
- **D-12's missing write path exists now — `RewardLedgerService.clawback()`** — but
  deliberately only as a **boundary**, per the user's own three-slice scope split
  ("Slice 8: rewards ledger boundary. Slice 9: rewards ledger integration"). Balance
  is always derived by summing entries (`test_reward_ledger_entry_has_no_stored_balance_field`
  guards this structurally, not just behaviorally), and `clawback()` is
  approval-gated with no self-approval exception (register §5.7). Nothing in this
  slice calls it yet — wiring "a reversed payment tied to a completed survey reward
  triggers a clawback" needs a completed-survey concept that belongs to Slice 9.
- **Bug found and fixed while building this, in Slice 1's foundation, not this
  slice's own code**: `CanonicalRepository.update()` (`app/models/base.py`) had no
  equivalent of `insert()`'s `to_mongo()` serialization — passing a live `Money`
  object into `changes` raised `bson.errors.InvalidDocument` the moment
  `record_payment` tried to update `amount_paid`/`balance_due`. Fixed once, in
  `update()` itself (every top-level `BaseModel` value is dumped before it reaches
  Mongo), not worked around per call site — the same "fix the enforcement point, not
  every caller" discipline as Slice 3's tz-aware datetime fix.
- Deliberately deferred, stated once rather than silently absent: multi-invoice
  split payments (`applied_to[]` in the endpoint catalogue's payment request shape);
  a distinct customer-refund workflow separate from payment reversal (`finance.refund.approve`
  exists in the closed permission list but has no distinct entity/endpoint yet);
  `finance.account_adjustment.approve` (no general-ledger-adjustment entity exists to
  gate); `PATCH` endpoints (same precedent as every prior slice); vendor-delete
  balance guards (D-34 — no vendor/account-delete endpoint exists in v2 to guard);
  CSV import (D-36 — not applicable, no CSV path in this slice); the ₹10,000 KYC
  payout threshold (D-13 — panel/rewards-specific, Slice 9's scope); a real
  bank-feed/payment-gateway reconciliation ingestion pipeline (`ReconciliationService`
  proves the model and the match invariant, not a live feed).

**Phase 1, slice 9: `app/panel/`** — Survey/Allocation/SurveyResponse/Supplier/
TrafficSource, built directly against schema_catalogue.md §5.1-5.3 and
endpoint_catalogue.md §5's already-deep-dived `POST /traffic/{id}/allocate` deep-dive.
Closes the wave: this is the third and last of the coordinated Slice 7→8→9 build,
each built and tested before the next started.

- **CPX is not merely absent here, it's structurally excluded.** `Survey.provider`
  and `Supplier.provider` can only be a member of `SURVEY_PROVIDERS = ("cint",)` —
  `test_cpx_is_not_a_member_of_the_closed_provider_set` and the two rejection tests
  guard this as a model-shape invariant, not an accident of what got built first.
  v2_locked_principles.md §1.10's full removal scope was never something backend_v2
  had to "remove" — it was never built here in the first place.
- **`AllocationService.allocate()`'s atomicity needs no raw-Motor exception**, unlike
  Slice 7/8's `BudgetService`/`SequenceService`. `CanonicalRepository.update()`'s own
  version-guard is sufficient — decrement is attempted at the version last read, and
  a `VersionConflict` (another caller won the race) is retried against a fresh read.
  This is register §2.2 fixed for real ("no atomic counter for CINT — only a soft
  pacing check reading a cache up to 5-10 minutes stale") and §2.0's dead-but-correct
  engine finally made the *only* path ("`SurveyAllocationService` is atomic... but
  `traffic.py` never calls any method on it" / "`handle_callback`... never calls it").
  `test_allocation_atomically_decrements_quota_and_never_oversells` is the direct
  regression test.
- **A duplicate `respondent_ref` is rejected, not replayed** — a deliberate
  divergence from Slice 7/8's idempotent-replay pattern, because the endpoint
  catalogue names this as a fraud guard, not a retry-safety mechanism: "a duplicate
  `respondent_ref` within the dedup window is rejected, not re-allocated."
- **A provider timeout falls back to the next eligible candidate, never a hardcoded
  default, and releases the slot it reserved** — the endpoint catalogue's own rule,
  proven (not just followed) by `test_provider_failure_falls_back_to_next_candidate_and_releases_the_reserved_slot`,
  which asserts the failed candidate's quota is back to its original value.
- **D-08 and D-23 closed by the same real HMAC verification, not two different
  fixes for what's the same failure shape**: `verify_hmac_signature()`
  (`callback_security.py`) fails closed on a missing secret (`SignatureConfigError`
  — D-23's exact bug was silently skipping validation here) and rejects a mismatched
  signature via `hmac.compare_digest` (D-08's bug was no verification existing at
  all on the production handler). `CallbackService.handle_callback()` calls this
  unconditionally, before anything else in the method runs.
- **`POST /surveys/{id}/callback` is the one endpoint in this codebase that
  deliberately does not go through `get_current_identity`/`require_permission`** — a
  real webhook caller cannot present a Torpedo session. Signature verification is
  its authentication; this is stated explicitly in both `routers.py`'s module
  docstring and a dedicated test
  (`test_callback_endpoint_requires_no_torpedo_session_but_does_require_a_valid_signature`)
  proving the exception is exactly that narrow, not a general auth bypass.
- **D-12's boundary (Slice 8) gets its real caller here — and stops exactly where
  register §5.7 says it must.** A `"complete"` callback credits the reward ledger
  directly (a legitimate system write — crediting was never approval-gated). A
  `"reversed"` callback does **not** call `RewardLedgerService.clawback()` itself —
  it records the `SurveyResponse` and raises a `reward_clawback_needed` Activity
  naming the exact amount, because `RBACService.can_approve()` refuses any
  non-`"user"` principal unconditionally and register §5.7 gives clawback no
  exception. A human still has to call Slice 8's already-built, approval-gated
  `POST /rewards/clawback`. `test_reversed_callback_never_directly_claws_back_only_flags_for_human_approval`
  is the direct regression test — the same I-4 shape ("AI/an external signal
  proposes, a human or a deterministic function decides") applied to a supplier
  webhook instead of an AI classifier.
- **D-38's class of defect avoided again**: eligibility (`AUTHORITATIVE`, Torpedo's
  own decision) and the quota/CPI/conversion-rate projection (`PROJECTION`,
  provider-owned) have two separate writers (`set_eligibility`/`refresh_projection`)
  that never touch each other's fields — proven, not just documented, by
  `test_refresh_projection_never_touches_eligibility_fields` and its mirror.
- **Supplier reconciliation is new construction, not a v1 port** — register §2.8:
  "no reconciliation module, job, or function exists anywhere." `SupplierReconciliationService.reconcile()`
  computes Torpedo's own count, compares it to a supplier-reported figure, and
  **flags disagreement — it never corrects either count** (I-5).
  `test_reconciliation_flags_disagreement_without_correcting_either_count` asserts
  the underlying `SurveyResponse` records are untouched by a reconciliation run.
  Deliberately not built: a live bank-feed/provider-report ingestion pipeline (the
  same honest scope boundary as Slice 8's `ReconciliationService`).
- Deliberately deferred, stated once rather than silently absent: a real Cint HTTP
  adapter (`SurveyProvider` is a `Protocol` tested against fakes, plus a
  `StubSurveyProvider` HTTP stand-in — one-line swap); `Survey.cold_start_score`
  (an AI-generated field per schema_catalogue.md §5.1 — no `AIClassifier`-shaped
  integration built for it this slice); B-09's primary-allocator quality floors
  (still an open business decision — this slice builds the allocation *mechanism*,
  not the specific threshold policy); D-13's ₹10,000 KYC payout threshold; PATCH
  endpoints (same precedent as every prior slice); distinguishing a 409
  (quota-race-lost) from a 422 (no-eligible-survey) at the HTTP layer — `SurveyError`
  isn't yet split into subtypes that could tell the two apart, so `allocate()`
  currently maps both to 422.

**All three coordinated slices (7 Outreach, 8 Finance, 9 Survey/Panel) are complete.**
98 tests before the wave → 184 after, comfortably past the ~150+ target, with one full
integration run (`pytest tests/`) green across all nine slices combined. Identity,
communications, money, and survey/panel economics — the four domains named as v1's
most failure-prone — now each have a real, tested vertical. Remaining work shifts
toward Operations/CRM completion, UI, reconciliation tooling, migration from v1, and
the real external-provider adapters every slice since 6 has deferred behind a
`Protocol`.

**Phase 1, slice 10: `app/crm/` (Opportunity) + two Operations detectors** — the
first increment toward `docs/AI_NATIVE_COMPLETION_CHECKLIST.md`'s AI-native target,
scoped to exactly what's buildable without real external credentials or the AI
Gateway (which itself is blocked on a GPU-broker resourcing decision — see that
checklist).

- **`Opportunity`** (`app/crm/`) built directly against schema_catalogue.md §2.2's
  locked shape. `contact_id` is `person_id` here, applying the already-settled
  "Person, not Contact" naming rather than reintroducing v1's terminology.
  `is_valid_transition()` is a simple rule (any active stage ↔ any other active
  stage, or close `won`/`lost`, terminal means terminal) rather than a full
  transition table — deliberately simpler than `LeadState`'s, since Opportunity
  stages don't carry the same audit-linearity requirement.
- **`convert_to_invoice()` is the endpoint catalogue's integration made real**:
  `POST /opportunities/{id}/convert` calls Slice 8's `InvoiceService.create_invoice()`
  directly — never a second invoice-creation implementation — and only from `won`,
  never repeatable once `Opportunity.converted_invoice_id` is set.
  `test_convert_creates_a_draft_invoice_referencing_the_opportunity` and
  `test_convert_is_not_repeatable` are the direct regression tests.
- **The >20% survey-traffic eligibility gate is real and deterministic**
  (`app.panel.service.CONVERSION_ELIGIBILITY_THRESHOLD`), enforced inside
  `AllocationService._reserve_quota()` so it's re-checked on every version-conflict
  retry, not just the first pass. Deliberately *not* an AI decision — the gate is a
  hard boundary; which eligible survey gets how much traffic is the AI-ranking layer
  this slice does not build.
- **`StudyInactivityService.detect_and_flag()`** is the 7-day-no-traffic trigger,
  idempotent within one inactivity episode (a scheduler running this every few
  minutes won't spam duplicate flags for the same unresolved gap). It only raises a
  `study_inactive_detected` Activity — it never pauses, closes, or reactivates
  anything; that decision is explicitly deferred to the AI Decision Engine.
- **Task/reminder entity deliberately not built**: no locked schema exists for it in
  `schema_catalogue.md`, and inventing one under time pressure would be exactly the
  kind of ungrounded construction this whole rebuild's discipline exists to prevent.

**Phase 1, slice 11: `app/ai/`** — the AI Gateway + Decision Engine, architected per
an explicit user decision after the Slice 10 VM-hardware audit: inference never runs
in-process on the small Torpedo VM (2 vCPU/3.8GB, already resource-tight). Instead:

```text
backend_v2 (this VM)  --HTTP-->  AI Gateway  --acquire()-->  GPU Broker  --rent-->  GPU node (RunPod, elsewhere)
```

- **`app/ai/gpu_lease.py` + `app/ai/gpu_broker.py` are ports, not imports**, of v1's
  already-mature (uncommitted) `backend/infra/gpu_lease.py`/`gpu_broker.py` — v1 and
  v2 run in separate venvs/worktrees/processes, so there's no runtime path to
  `from infra import gpu_lease` without breaking the isolation this whole rebuild is
  built on. `POD_NAME_PREFIX` is `torpedo-v2-glm` (v1 uses `torpedo-glm`) so each
  system's orphan-reaper is blind to the other's pods even if they share one RunPod
  account. The registry lives in v2's own `ai_gpu_leases` collection, not v1's
  `torpedo_settings.gpu_leases` — a deliberate isolation-over-cost-sharing tradeoff.
- **Bug found and fixed while porting, not carried forward**: v1's version used
  `requests` (blocking) and `time.sleep()` in its poll/retry loops — fine from a
  synchronous Celery worker (v1's context), but a real problem in FastAPI's async
  world: a blocking `time.sleep()` inside a coroutine freezes every other request
  that worker is serving, and a cold start is up to 45 minutes. Rewritten with
  `httpx.AsyncClient`/`asyncio.sleep` throughout so provisioning can run inside a
  request handler without stalling the whole process.
- **`GpuBroker` is a documented, narrow exception to "every write goes through
  `CanonicalRepository`"** — the third instance of this pattern (after
  `BudgetService`, `SequenceService`): the registry document is operational
  infrastructure state, and single-flight provisioning needs a conditional atomic
  `update_one` the version-guard can't express.
- **`LLMProvider` is the fifth Protocol-boundary implementation** in this codebase
  (`AIClassifier`, `SendProvider`, `MessageDrafter`, `SurveyProvider`, now this) —
  `GpuBrokerLLMProvider` is the real implementation, tested against a faked
  `httpx.MockTransport`, never a real network call.
- **`DecisionEngine.decide()` never executes an action** — it produces a `Decision`
  (master-prompt §7's schema, field-for-field) and persists it as an `AiProposal`
  (Slice 6/7's model, reused rather than duplicated per I-1). A caller reads the
  `Decision` and acts through whatever permission-gated domain service already
  exists — the same I-4 separation ("AI proposes, a deterministic function or a
  human decides") every prior AI-adjacent slice already held, now applied to a real
  model boundary instead of a fake `PassthroughAIClassifier`.
- **`requires_human_approval=True` is never auto-appliable, regardless of
  confidence** — mirrors `RBACService.can_approve()`'s refusal to let a wildcard or
  system principal stand in for real approval authority. `AiProposal.status` stays
  binary (Slice 6's documented scope); the flag survives inside `proposed_fields`
  rather than being silently collapsed into "rejected" without a trace.
- **The tool registry is deliberately not live LLM-invoked function-calling yet** —
  a caller assembles context using registered tools before calling `decide()`; the
  model doesn't autonomously invoke anything mid-conversation. Real agentic
  tool-calling needs a running model to validate against (which model, whether it
  supports structured tool calls), which needs the credential below.
- Deployed to the VM as part of the same `torpedo-backend-v2.service` — safe,
  because the gateway itself is lightweight orchestration (HTTP calls to RunPod, one
  Mongo document), not the model. Nothing runs a GPU until `GPU_BROKER_ENABLED=true`
  and a real `RUNPOD_API_KEY` are both set, which they deliberately are not yet.

**Phase 1, slices 12-14: real AI-driven business logic**, built per explicit user
instruction not to pause for missing credentials — the internal workflow is real
and tested now, only the external boundary (GSC/email-provider credentials) stays
disabled. All three route through the *same* `DecisionEngine` (no isolated
per-domain decision engines) and every actual write reuses an existing,
already-governed service rather than a new one:

- **Slice 12 (`app/emailai/`)**: `EmailAIService.analyze_and_route()` classifies an
  `InboundEmail` into a closed set (`SALES_LEAD`/`INVOICE`/`UNSUBSCRIBE`/...) via a
  real `DecisionEngine.decide()` call, then deterministically dispatches —
  `SALES_LEAD` calls Slice 6's `LeadGenService.ingest()` (identity resolution/dedup
  reused, not rebuilt), `UNSUBSCRIBE` calls Slice 7's `SuppressionService.suppress()`,
  `INVOICE`/`PAYMENT`/`BILL` calls Slice 8's `ReconciliationService.record_external_entry()`
  (never touches a balance). Idempotent on the email itself — a duplicate analysis
  reconstructs the prior `Decision` from its `AiProposal` rather than re-deciding
  and re-routing. `EmailAIService.decide_followup()` drafts and sends through the
  *real* `MessagingFacade` (`EmailMessageDrafter` implements Slice 7's
  `MessageDrafter` `Protocol`) — suppression/kill-switch/budget/footer/idempotency
  all still enforced; a suppressed address is never sent to even when the AI
  decision says to send.
- **Slice 13 (`app/leadgen/gsc.py` + `ai_leadgen.py`)**: `LeadGenAIService.generate_leads()`
  proposes candidates from GSC signals (`GSCProvider` — the seventh Protocol
  boundary in this codebase), and every candidate becomes a real lead only through
  Slice 6's `ingest()`. A candidate without a model-named `company_domain` is
  skipped, never defaulted — "no fictional companies," enforced structurally.
  `evaluate_icp()` is the AI's classification (`OUTREACH`/`RESEARCH`/`HOLD`/`REJECT`
  + score/fit_reasons/risks in `Decision.extracted_entities`), coexisting with,
  not replacing, `app.leadgen.scoring.score_lead()` — the two answer different
  questions (broad commercial fit vs. B-04's specific qualification threshold).
- **Slice 14 (`app/leadgen/ai_outreach.py`)**: `OutreachAIService.decide_and_act()`
  is the ICP→outreach flow. `LeadEnrollment` gained one field
  (`sequence_state: OUTREACH_READY→CONTACTED→...→STOPPED`) — the AI decides
  transitions, this service only validates the closed set, same discipline as
  `app.crm`'s `Opportunity.stage`. Reuses Slice 6's `check_contactability()` and
  Slice 7's `MessagingFacade` wholesale; contactability is a hard boundary the AI
  cannot override, proven by a direct test. Contact selection among multiple
  contacts at one account is honestly **not built** — `LeadState.person_id` is
  singular in this data model, and faking a selection algorithm over a
  single-item list was rejected as decoration.
- **One schema change enabled all three**: `Decision` (Slice 11) gained
  `extracted_entities: dict` so email entity extraction and ICP scoring share one
  structured-payload field instead of each inventing its own — the same "one
  Decision Engine, one schema" mandate applied to the schema itself, not just the
  engine.

**Phase 1, slice 15 (`app/panel/ai_allocation.py`): AI survey pool + panel
allocation.** Per explicit user instruction: a real `DecisionEngine.decide()`
ranking, not a fixed-weights scoring formula relabeled AI.

- **The >20% conversion gate is enforced by never offering the choice, not by
  trusting the AI to decline it.** `SurveyService.list_eligible()` (one new
  method, reusing the existing `CONVERSION_ELIGIBILITY_THRESHOLD` from Slice 9)
  runs first, and its result is the *entire* candidate set the model is shown —
  a test asserts the model's own received context excludes an ineligible survey
  entirely, which is a stronger guarantee than "the model was told not to pick it."
- **A model choosing outside the eligible set it was actually offered is
  rejected outright**, not silently dropped from a list — the same
  fail-loud-not-silent discipline every other AI-boundary slice already holds.
- **Three real `Survey` fields added** (`category`, `length_minutes`,
  `incentive`) as genuine allocation context — not fabricated data, just
  ordinary survey attributes the model needs to reason about fit.
- **"Decision memory" is real historical data re-queried on every call, not a
  separate learning pipeline**: `historical_completion_rate`/
  `historical_dropout_rate`/`previously_exposed_to_this_survey`/
  `days_since_last_allocation`, computed fresh from `SurveyResponse`/`Allocation`
  records each time — deliberately not a vector store or fine-tuning loop, per
  the user's own "simplest architecture that works reliably" guidance.
- **`AllocationService.allocate()` (Slice 9) executes the AI's ranked choice
  completely unchanged** — the model's top choice plus its fallback ranking
  (`decision.decision` + `decision.entities`, reusing Slice 11's generic schema
  rather than inventing a new one) is handed straight to `allocate()`, which
  already knows how to fall through a ranked list atomically. This slice adds no
  new execution path, only the ranking layer in front of an existing one.
  `Allocation.ai_decision_subject_id` (one new field) traces every AI-driven
  allocation back to the `AiProposal` that chose it.
- **Demographic profile-fit and fraud/risk signals are honestly not modeled** —
  no consent-gated profile system or fraud-detection pipeline exists yet, and
  passing a fabricated value for either was rejected as exactly the
  no-fake-completion failure this rebuild's discipline exists to prevent.

**Phase 1, slice 16 (`app/panel/ai_operations.py`): AI Operations.** Per explicit
user instruction: the 7-day-no-traffic condition (and two more real triggers
added alongside it) is a hard, deterministic trigger — what happens *afterward*
is a real AI decision, not a second layer of hard-coded rules.

- **Three real, computable triggers** feed `OperationsAIService.detect_triggers()`:
  `no_traffic_7_days` (reuses Slice 10's `StudyInactivityService` unchanged),
  `low_conversion` (a nominally-eligible survey whose live `conversion_rate` has
  already fallen to/below Slice 9/15's threshold — meaning the deterministic
  allocation gate is silently refusing it traffic and nobody's looked at why),
  `high_dropout` (a real rate computed from that survey's own `SurveyResponse`
  records, gated by a minimum sample size so five unlucky responses don't trigger
  an investigation).
- **The response is a real `DecisionEngine.decide()` call**, validated against a
  closed action set (`INVESTIGATE`/`REQUEST_CLIENT_STATUS`/`PAUSE`/`CLOSE`/
  `REACTIVATE`/`ESCALATE`/`NO_ACTION`) with a state-validity guard enforced in
  code, not trusted from the model: `CLOSED` is terminal, `REACTIVATE` is only
  valid from `PAUSED`/`PENDING_CLIENT_RESPONSE`. `INVESTIGATE` calls the real
  `SurveyService.refresh_projection()` (Slice 9) to pull fresh provider numbers
  before anything else decides on stale data.
- **Same-day-same-trigger idempotency** — `AiProposal.subject_id` is keyed on
  `(survey_id, trigger_type, date)`, so a future scheduler (Phase 14, not yet
  built) running this hourly won't re-decide, and re-act on, the same
  still-unresolved condition every run.
- **`Survey` gained `operational_status` and `ai_decision_subject_id`** — the
  latter generalizing `Allocation.ai_decision_subject_id` (Slice 15) into a
  repeatable pattern per explicit user instruction: "I would use the same
  pattern throughout the rest of Torpedo." Every AI-driven operational decision
  traces back to the exact `AiProposal` that made it, the same way every
  AI-driven allocation already does.
- **`REQUEST_CLIENT_STATUS` records real state but sends no email** — there is
  no verified path from a `Survey` to a client contact address yet (that
  linkage is Finance/CRM territory, Slices 17-18's problem). Two triggers from
  the fuller wishlist are honestly not built: supplier/provider-failure-rate (no
  persisted failure-rate metric exists — `AllocationService` already silently
  releases quota and moves on for a provider timeout, Slice 9) and
  client-response/deadline-driven triggers (no `Study` entity distinct from
  `Survey`, no deadline field). Fabricating either as a working trigger would be
  exactly the no-fake-completion failure this rebuild's discipline exists to
  prevent.

Not yet built: migrations from v1; actually renting a GPU node (blocked on
`RUNPOD_API_KEY`, confirmed absent — see `docs/AI_NATIVE_COMPLETION_CHECKLIST.md`);
real GSC/Cint/email-provider adapters (all blocked on credentials this environment
doesn't have); a scheduler to run `GpuBroker.sweep()`, `detect_and_flag()`,
`detect_triggers()`, or periodic email/lead-gen/outreach/allocation evaluation on
a cadence (Phase 14 of the checklist — event/scheduler infrastructure); Slices
17-19 (AI finance, Cint+billing+margin, full end-to-end orchestration). See
`docs/schema_catalogue.md` and `docs/endpoint_catalogue.md` for what those will
look like when they land.

## Running

```
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Requires `MONGO_URI` and `MONGO_DB_NAME` in the environment (see `app/config.py`) — there
is no fallback default database name, deliberately, per D-16.
