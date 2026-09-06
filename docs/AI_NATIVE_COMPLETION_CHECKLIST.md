# AI-Native Completion Checklist

Tracks the gap between Torpedo v2's current state (Slices 1-9, 184 tests, deployed
isolated on the prod VM at `127.0.0.1:8002`) and the "AI-native operating platform"
target: event → context → AI decision → action → state change, across the full
lead-to-cash lifecycle. Status values: `NOT_STARTED` / `IN_PROGRESS` /
`IMPLEMENTED` / `TESTED` / `DEPLOYED` / `VERIFIED`. Nothing is marked past
`IMPLEMENTED` without a passing test proving it; nothing is marked `DEPLOYED`
without being confirmed running on the VM.

## Hard blockers found during audit (2026-09-06)

These are real, not deferred-for-convenience. Each needs a decision or a credential
that only the user can supply — building around them with a mock and calling it done
would violate the no-fake-completion rule this checklist itself exists to enforce.

| Blocker | Detail | Needed to unblock |
|---|---|---|
| **Local LLM inference on the prod VM** | VM is 2 vCPU / 3.8GB RAM, swap already 100% full (2046/2047MB) running v1 + Mongo + 4 Celery workers + SFW panel. No GPU. Cannot safely host even a small quantized model without risking an OOM crash of the live v1 service. | A resourcing decision: reuse the existing (stashed, uncommitted) `backend/infra/gpu_lease.py` on-demand GPU broker instead of in-process local inference, or explicitly approve resizing/adding a GPU to the VM. |
| **Cint API credentials** | `app.panel.cint_provider.CintSurveyProvider` (Slice 18) is a real, non-fake implementation of `SurveyProvider` — built from v1's actual verified `Supply/v1/SupplierLinks` entry-link endpoint/response shape (read from `cint_integration.py`/`cint_service.py` as reference, not copied as-is given register D-defects §2.0-2.9). No live `CINT_API_KEY`/`CINT_SUPPLIER_CODE` found in this environment, so it fails loud (`SurveyProviderUnavailable`) rather than faking a response. `refresh()` honestly does not implement v1's `LEGACY_SURVEY_DETAIL_ENDPOINT` — that endpoint is defined in v1 but never actually called anywhere in v1's own codebase, so its response shape is unverified and was not guessed at. | Real Cint API credentials + sandbox access, and (separately) verification of the legacy survey-detail endpoint's actual response shape before `refresh()` can be implemented for real. |
| **GSC / Google Search Console** | Only a stub reference in `seo_agent.py`; no working lead-gen pipeline exists in v1 or v2. | Google service-account/OAuth credentials for Search Console API. |
| **Real email sending (SMTP)** | `app.outreach.smtp_provider.SmtpSendProvider` (Slice 21) is a real implementation — `get_send_provider()` returns it by default now, not `StubSendProvider` (kept, test-only). Fails loud (`SendProviderUnavailable`) when unconfigured. | Real `SMTP_HOST`/`SMTP_USERNAME`/`SMTP_PASSWORD`, confirmed absent from this environment. Gmail-OAuth (v1's `gmail_service.py`/`gmail_workspace_service.py`) is a separate, larger credential-management scope not built here — SMTP is the practical first real transport. |

## Phase 5 — CRM commercial spine (Opportunity, Task)

| Item | Status |
|---|---|
| `Opportunity` entity (stage pipeline, closed-enum transitions) | **TESTED** (Slice 10, 2026-09-06) — 17 tests, schema_catalogue.md §2.2 |
| `POST /opportunities`, stage transition, close-lost | **TESTED** (Slice 10) |
| `POST /opportunities/{id}/convert` → draft Invoice | **TESTED** (Slice 10) — real cross-domain call into `InvoiceService`, not restated logic |
| Task/reminder entity | NOT_STARTED — no locked schema found in schema_catalogue.md for this; deferred rather than invented ungrounded, per the no-fake-completion rule |

## Phase 2-3 — AI Gateway + Decision Engine

| Item | Status |
|---|---|
| GPU lease manager (`app.ai.gpu_lease`, ported from `backend/infra/gpu_lease.py`) | **TESTED** (2026-09-06) — 11 tests. Ported, not imported (separate venv/worktree); fixed a real bug in the port: v1's `time.sleep()`/`requests` would freeze an async FastAPI worker for the length of a cold start, converted to `httpx.AsyncClient`/`asyncio.sleep` throughout |
| GPU broker / single-flight registry (`app.ai.gpu_broker`, ported from `backend/infra/gpu_broker.py`) | **TESTED** — 11 tests covering the four bugs worth testing (two processes provisioning at once, a node nothing shuts down, a busy node shut down mid-batch, a registry pointing at a dead pod). Own collection (`ai_gpu_leases`, v2's own db) — deliberately not sharing v1's `torpedo_settings.gpu_leases`, so v2's isolation from v1 holds even for this |
| Actually renting a real GPU node | **NOT_STARTED — blocked on `RUNPOD_API_KEY`**, confirmed absent from this environment. `GPU_BROKER_ENABLED` also unset (off by default, as designed). `docs/GPU_ACTIVATION_RUNBOOK.md` is the exact 18-step checklist to run once it's configured server-side |
| Shadow-mode activation safety gate (`Settings.ai_shadow_mode`) | **TESTED** (2026-09-06, Slice 20) — defaults `True` in production; suppresses exactly the five execution points that send an email, allocate a panelist, pause/close a survey, or record a payment match, while `DecisionEngine.decide()` keeps recording every `AiProposal` normally. 5 new regression tests (one per gated service). Built *before* the GPU credential, deliberately — so activation goes straight into the runbook's shadow-mode validation phase rather than a design conversation once the key lands |
| `LLMProvider` Protocol + `GpuBrokerLLMProvider` (`app.ai.llm`) | **TESTED** — 4 tests, fifth instance of this codebase's Protocol-boundary pattern |
| Central decision-contract schema (`app.ai.decision_engine.Decision`) | **TESTED** — matches master-prompt §7 field-for-field |
| `DecisionEngine.decide()` — context → model → structured decision → audit log | **TESTED** — 9 tests. Never executes an action; a caller reads the `Decision` and acts through existing permission-gated services |
| Tool registry (`app.ai.tools.ToolRegistry`) | **TESTED**, deliberately minimal — a caller-driven context-fetcher registry, not live LLM-invoked function-calling (that needs a real running model to validate against, which needs the credential above) |
| Decision audit log | **DONE** — reuses `AiProposal` (Slice 6/7), not a second entity; `status` stays binary (`approved`/`rejected`) per its documented Slice 6 scope, with `requires_human_approval` preserved inside `proposed_fields` rather than silently collapsed |
| Human review queue (approve/reject/modify/defer/escalate) | **TESTED** (2026-09-06, Slice 22) — `app.governance.approvals.ApprovalService` + `GET/POST /governance/proposals`. `reviewed_by`/`reviewed_at`/`review_action`/`review_notes` on `AiProposal` are additive and independent of `status` (the system's own auto-apply verdict) — a human review never rewrites what the system already decided. Deliberately does not (yet) re-execute a shadow-mode-suppressed action on APPROVE — see the module's own docstring for why that's the honest next increment, not built prematurely |
| Governance validator (AI never gets unrestricted DB access) | Structurally true by construction — nothing in `app.ai` imports a `CanonicalRepository` for any entity other than `AiProposal` (the audit log itself) |
| `GET /ai/gpu/status`, `POST /ai/gpu/shutdown` | **TESTED** — deployed |
| Real agentic tool-calling (model autonomously invoking registered tools) | NOT_STARTED — needs a running model to validate against |
| Wiring `DecisionEngine.decide()` into real domain callers (email, AR follow-up, survey ranking, ...) | NOT_STARTED — Slices 12-16 |
| Scheduled `sweep()` (idle/orphan reaping on a cadence) | NOT_STARTED — the Phase 14 scheduler now exists and could call this on the same cadence, but `GpuBroker.sweep()` itself isn't yet one of the seven wired triggers (`EventDetectionService`/`EventOrchestrator`); a real, small follow-up, not fabricated here |

## Phase 6 — GSC lead generation + ICP

| Item | Status |
|---|---|
| `GSCProvider` Protocol + `NullGSCProvider` (fails loud, never a fake empty result) | **TESTED** (2026-09-06, Slice 13) |
| `LeadGenAIService.generate_leads()` — AI proposes candidates from GSC signals, real leads created via Slice 6's `LeadGenService.ingest()` (identity resolution/dedup reused, not rebuilt) | **TESTED** — 9 tests, including a real "different contact, same company → same Account, new Person" dedup proof |
| "No fictional companies" guard — a candidate without a model-named `company_domain` is skipped, never defaulted | **TESTED** |
| `LeadGenAIService.evaluate_icp()` — AI-driven classification (`OUTREACH`/`RESEARCH`/`HOLD`/`REJECT` + score/fit_reasons/risks in `Decision.extracted_entities`), not a fixed arithmetic score | **TESTED** — coexists with, does not replace, `app.leadgen.scoring.score_lead()` (a different question — B-04 qualification threshold vs. broader commercial fit) |
| Actual GSC API data | **NOT_STARTED — blocked on Google credentials**, confirmed absent |

## Phase 7 — AI outreach + email intelligence

| Item | Status |
|---|---|
| Email classification (closed `EMAIL_CLASSIFICATIONS` set, real `DecisionEngine` call) | **TESTED** (Slice 12) — deterministic dict-dispatch routing, never fuzzy string matching |
| Entity extraction | **TESTED** — via `Decision.extracted_entities`, the same field ICP evaluation uses (one schema, per master-prompt §1) |
| Email → CRM (`SALES_LEAD` → Slice 6's `LeadGenService.ingest()`) | **TESTED** |
| Email → Finance (`INVOICE`/`PAYMENT`/`BILL` → Slice 8's `ReconciliationService.record_external_entry()`, never touches a balance) | **TESTED** |
| Email → suppression (`UNSUBSCRIBE` → Slice 7's `SuppressionService.suppress()`) | **TESTED** |
| Duplicate email / duplicate classification → no duplicate action | **TESTED** — idempotent on the email itself, reconstructs the prior `Decision` from its `AiProposal` rather than re-deciding |
| AI-drafted outreach through `MessageDrafter` (Slice 7's `Protocol`) | **TESTED** (Slice 12) — `EmailMessageDrafter` is the real implementation, reused unchanged by Slice 14's outreach drafting too |
| AI follow-up decision → send through the real `MessagingFacade` (suppression/kill-switch/budget/footer/idempotency all still enforced) | **TESTED** — including the direct regression: a suppressed address is never sent to even when the AI decision says to send |
| Follow-up idempotent across a simulated worker restart | **TESTED** |
| Real mailbox polling (`EmailIngestionProvider`) | NOT_STARTED — blocked on email provider credentials, confirmed absent |
| ICP→outreach decision (`OutreachAIService.decide_and_act()`, Slice 14) | **TESTED** — 6 tests. Reuses Slice 6's `check_contactability()` and Slice 7's `MessagingFacade` wholesale; `LeadEnrollment.sequence_state` (one new field) is the persisted outreach-sequence state (`OUTREACH_READY→CONTACTED→...→STOPPED`), the AI decides transitions, this service only validates the closed set |
| Contactability as a hard boundary the AI cannot override | **TESTED** — a suppressed contact is never sent to even when the AI decision says `CONTACTED` + `send_message` |
| Contact selection among multiple contacts at one account | **NOT_STARTED, honestly** — `LeadState.person_id` is singular in this data model; there is no "list every contact at this account" query built yet. Faking a selection algorithm over a single-item list was rejected as decoration, not built as a stand-in |

## Phase 8-9 — Survey Pool AI + panelist allocation AI

| Item | Status |
|---|---|
| Deterministic >20% conversion eligibility gate | **TESTED** (2026-09-06) — `CONVERSION_ELIGIBILITY_THRESHOLD` in `app.panel.service`, enforced inside `_reserve_quota()` so it applies on every retry, not just the first check |
| AI ranking within the eligible set | **TESTED** (2026-09-06, Slice 15) — `app.panel.ai_allocation.PanelAllocationAIService`, real `DecisionEngine.decide()` call, not a fixed-weights formula. The eligible set (`SurveyService.list_eligible()`) is computed *before* the model is ever called, so an ineligible survey is never offered as a choice — proven by asserting the model's own received context excludes it |
| Panelist suitability using real historical signal | **TESTED** — `historical_completion_rate`/`historical_dropout_rate`/`previously_exposed_to_this_survey`/`days_since_last_allocation`, all computed fresh from real `SurveyResponse`/`Allocation` records on every call ("decision memory" without a separate ML/vector pipeline) |
| Real economic context (`client_rate_minor` alongside `cpi_minor`) for margin-aware ranking | **TESTED** (2026-09-06, Slice 18/19) — `_survey_context()` passes both raw figures; deliberately not a computed margin field, the model reasons about revenue-vs-cost from the two numbers directly rather than trusting a value this method would have to fabricate without a billing-service dependency |
| Model choosing outside the eligible set | **TESTED** — rejected outright, not silently dropped |
| Decision→allocation traceability | **TESTED** — `Allocation.ai_decision_subject_id` links back to the `AiProposal` that chose it |
| Demographic profile-fit / fraud-risk signals in allocation context | **NOT_STARTED, honestly** — no consent-gated profile system or fraud-detection pipeline exists yet; not fabricated as context |
| Panelist→survey suitability ranking | NOT_STARTED |
| Atomic allocation mechanics | **DONE (Slice 9)** — `AllocationService`, tested |

## Phase 10 — Cint adapter

| Item | Status |
|---|---|
| Real `CintSurveyProvider` behind `app.panel.providers.SurveyProvider` | **TESTED** (2026-09-06, Slice 18) — 5 tests. Real, verified base URLs/auth header/entry-link endpoint from v1's actual `cint_integration.py`; `get_survey_provider()` now returns this by default (was `StubSurveyProvider`, kept as a test-only double) |
| Actually calling the live Cint API | **NOT_STARTED — blocked on `CINT_API_KEY`/`CINT_SUPPLIER_CODE`**, confirmed absent. `build_redirect_url()` raises `SurveyProviderUnavailable` rather than faking a redirect |
| `refresh()` against Cint's real opportunity/quota data | **NOT_STARTED, honestly** — v1's `opportunities/v1/subscriptions/{supplier_code}` endpoint is a push/webhook subscription mechanism, not a pull-per-survey quota endpoint; v1's `LEGACY_SURVEY_DETAIL_ENDPOINT` is defined but never actually called anywhere in v1's own codebase, so its response shape is unverified and was not guessed at here |
| `SurveyProvider` Protocol + fakes | **DONE (Slice 9)** |

## Phase 11 — Operations: inactive-study intelligence

| Item | Status |
|---|---|
| 7-day-no-traffic trigger | **TESTED** (2026-09-06) — `app.panel.inactivity.StudyInactivityService.detect_and_flag()`, idempotent within one inactivity episode, 5 tests |
| AI investigation/decision (pause/close/reactivate/escalate) | **TESTED** (2026-09-06, Slice 16) — `app.panel.ai_operations.OperationsAIService`, a real `DecisionEngine.decide()` call per trigger, not hard-coded if/else. Three real, computable triggers: `no_traffic_7_days` (reuses the detector above), `low_conversion` (a nominally-eligible survey whose live conversion has fallen to/below the Slice 9/15 threshold), `high_dropout` (real `SurveyResponse`-derived rate, gated by a minimum sample size) |
| Deterministic guardrails around the AI's operational decision | **TESTED** — closed action set (`INVESTIGATE`/`REQUEST_CLIENT_STATUS`/`PAUSE`/`CLOSE`/`REACTIVATE`/`ESCALATE`/`NO_ACTION`), `CLOSED` is terminal, `REACTIVATE` only valid from `PAUSED`/`PENDING_CLIENT_RESPONSE`, same-day-same-trigger idempotency |
| `Survey.operational_status` + `ai_decision_subject_id` (traceability) | **TESTED** — the `Allocation.ai_decision_subject_id` pattern from Slice 15, generalized per explicit user instruction |
| Supplier/provider-failure-rate trigger | **NOT_STARTED, honestly** — no persisted per-provider failure counter exists; `AllocationService` already releases quota and moves on silently on a provider timeout (Slice 9), it doesn't record a failure-rate metric anywhere yet |
| Client-response/deadline/change-request triggers | **NOT_STARTED, honestly** — there is no `Study` entity distinct from `Survey`, no client-contact linkage, no deadline field; `REQUEST_CLIENT_STATUS` records real state but does not send an email, because no verified path from a survey to a client contact exists yet (Finance/CRM territory, Slices 17-18) |
| Scheduler entrypoint to run detection periodically | **TESTED, running** (2026-09-06, Slice 19) — `app.scheduler.detectors.EventDetectionService.detect_survey_operations()` calls `OperationsAIService.detect_triggers()` (which itself calls `StudyInactivityService.detect_and_flag()`) every 5 minutes via the Phase 14 scheduler; see Phase 14 below |

## Phase 12 — Finance AI (AR/AP, reconciliation)

| Item | Status |
|---|---|
| Partial payment accounting | **DONE (Slice 8)** — `PaymentService.record_payment`, tested |
| Payment reversal | **DONE (Slice 8)** — tested |
| AI-driven AR follow-up (vs. fixed-schedule reminders) | **TESTED** (2026-09-06, Slice 17) — `app.finance.ai_finance.AIFinanceService.decide_ar_followup()`, real `DecisionEngine.decide()` call using real evidence (balance due, days overdue via new `Invoice.due_at`, payment history). Proven to never alter the invoice's balance/status/total regardless of the decision — the AI decides the *response*, it never touches the ledger |
| AI-driven AP follow-up | **TESTED** — `decide_ap_followup()`, deliberately asymmetric with AR: `SCHEDULE_PAYMENT` is a recommendation only, no code path here ever calls `record_payment(direction="made", ...)` automatically — proven by a test asserting zero `Payment` records exist after the decision |
| AI-assisted bank↔payment↔invoice reconciliation | **TESTED** — `match_payment_to_invoice()`. Candidates are deterministic (`InvoiceService.list_open()` filtered to an exact amount match against the `ReconciliationRecord`) — the AI picks among the offered set only, a fabricated invoice_id is rejected outright. Auto-apply calls the real, unchanged `PaymentService.record_payment()` + `ReconciliationService.match()` — this module never writes to Mongo directly |
| "Never let AI infer financial truth from an email" | **TESTED end-to-end** — a test simulates Slice 12's exact `PAYMENT`-classification write path (`record_external_entry()` only, invoice untouched) followed by this slice's real matching step, proving an invoice only becomes `paid` through the governed match, never from the email alone |
| Supplier reconciliation | **DONE (Slice 9)** — `SupplierReconciliationService`, flags disagreement, tested |
| Margin (`Client → Study → Completes → Revenue/Cost`) | **TESTED** (2026-09-06, Slice 18) — `app.panel.billing.SurveyBillingService.compute_margin()`; see Phase 13 below |

## Phase 13 — Complete → billing → invoice → supplier bill → margin

| Item | Status |
|---|---|
| Survey completion → reward credit | **DONE (Slice 9)** — `CallbackService`, tested |
| Reward clawback on reversal (human-approval-gated) | **DONE (Slice 9)** — tested |
| Complete → billable completion (supplier-cost snapshot) | **TESTED** (2026-09-06, Slice 18) — `SurveyBillingService.record_billable_completion()`; idempotent against a later `Survey.cpi` change — an already-billable response is never re-costed |
| Billable completions → client invoice | **TESTED** — `generate_client_invoice()`, requires both `Survey.opportunity_id` and `Survey.client_rate` (raises rather than fabricating either); never double-bills an already-invoiced completion; writes only through the real, unchanged `InvoiceService` |
| Billable completions → supplier bill | **TESTED** — `generate_supplier_bill()`, same discipline, writes only through `BillService` |
| Margin/profitability calculation (revenue − supplier cost) | **TESTED** — `compute_margin()`; reports `margin_pct: None` (never a fabricated 0%/100%) when there's no `client_rate` to compute revenue from |
| `Survey.opportunity_id`/`client_rate`, `SurveyResponse.billable`/`supplier_cost`/`client_invoice_id`/`supplier_bill_id` | **TESTED** — new fields, all additive |

## Phase 14 — End-to-end orchestration + event bus

| Item | Status |
|---|---|
| Internal event mechanism (`Event` model — `event_type`/`entity_type`/`entity_id`/`occurred_at`/`processing_status`) | **TESTED** (2026-09-06, Slice 19) — `app.scheduler.models.Event`, a real `CanonicalDocument` |
| Deterministic detection → idempotent `Event` creation | **TESTED** — `app.scheduler.detectors.EventDetectionService`, seven real triggers (see Phase 11/12/6/7 rows below), each reusing an existing detector/query, never reimplementing one |
| Scheduler/background continuous loop | **TESTED, running** — `POST /internal/scheduler/tick` (HMAC-signed, same mechanism as the Cint outcome callback) + a systemd timer (`backend_v2/deploy/torpedo-v2-scheduler.timer`, every 5 minutes) calling it on the same FastAPI process. Deliberately not Celery — the VM's hardware constraints (this checklist's own hard-blockers table) make a broker + worker process real new weight the platform doesn't need yet; `EventOrchestrator` doesn't know or care how it's invoked, so this is swappable later without touching detector/orchestrator code |
| Idempotent action execution under the event loop | **TESTED** — single-flight claiming via `CanonicalRepository.update()`'s existing optimistic-concurrency guarantee (`PENDING/FAILED -> PROCESSING`, a lost race is `VersionConflict`, counted as skipped); a recoverable failure (every real handler call raises `LLMUnavailable` right now, no GPU credential) is recorded on the `Event` and retried up to `MAX_ATTEMPTS` (5), never fabricated as success |
| Observability | **TESTED** — `GET /internal/scheduler/events`, permission-gated, for a human to inspect pending/failed/processed events without shell access |

---

**2026-09-06 progress**: Phase 5 (Opportunity, minus Task — no locked schema found
for Task, deferred rather than invented), the Phase 8 deterministic conversion gate,
and the Phase 11 inactivity detector all landed — each fully unblocked, no
credentials or AI Gateway needed, 24 new tests, 208/208 total. Deployed to the VM
(see deployment log at the bottom of this file once it lands).

**What's next is genuinely blocked, not just unscheduled**: every remaining phase
(6 GSC lead-gen, 7 email AI + real send provider, 10 real Cint adapter, most of 12's
AI-driven AR/AP) needs real third-party credentials this environment doesn't have.
Building any of them against a mock and calling it done would be the exact
no-fake-completion failure this checklist exists to catch — so they stay
`NOT_STARTED` until credentials actually arrive, not because the work was skipped.

**2026-09-06, later the same day**: Slice 11 (Phase 2/3, AI Gateway + Decision
Engine) landed, architected per an explicit user decision — inference never runs
in-process on the small Torpedo VM; `app.ai.gpu_lease`/`app.ai.gpu_broker` (ported
from v1's already-mature, uncommitted `backend/infra/gpu_lease.py`/`gpu_broker.py`)
rent a GPU node elsewhere (RunPod) only for the minutes it's used. The plumbing —
lease/broker/LLM-provider/decision-engine/tool-registry, 38 tests — is real and
deployed; actually renting a node is the one piece still blocked, on
`RUNPOD_API_KEY`, confirmed absent. Test count: 208 → 246.

**2026-09-06, continued — Slices 12/13/14 (real AI-driven business logic, not
scaffolding, per explicit user instruction not to pause for credentials)**: Email
AI (classification/entity-extraction/CRM-routing/finance-routing/follow-up), GSC
lead generation + ICP evaluation, and the ICP→outreach decision flow all landed,
each routed through the *same* `DecisionEngine` (no isolated per-domain decision
engines, per the user's explicit §1 mandate) and each reusing an existing,
already-governed service for every actual write (Slice 6's `LeadGenService.ingest()`,
Slice 7's `MessagingFacade`/`SuppressionService`, Slice 8's
`ReconciliationService.record_external_entry()`). `Decision` gained one field
(`extracted_entities: dict`) so email entity extraction and ICP scoring could reuse
one schema instead of each inventing its own. Every external boundary these three
slices touch (`GSCProvider`, `EmailIngestionProvider`) stays a `Protocol` with a
credential-absent stub that fails loud — nothing pretends a live integration works.
Test count: 246 → 278.

**2026-09-06, continued — Slice 15 (AI Survey Pool + Panel Allocation)**: per
explicit user instruction, this is a real AI ranking, not a deterministic scoring
formula relabeled AI. `SurveyService.list_eligible()` is the hard gate (>20%
conversion, active-in-pool, quota>0) run *before* the model ever sees a candidate
list — a test asserts the model's own received context excludes an ineligible
survey, not just that the model declined it. `Survey` gained three real fields
(`category`, `length_minutes`, `incentive`) as genuine allocation context;
demographic profile-fit and fraud/risk signals are explicitly not modeled yet (no
consent-gated profile system or fraud pipeline exists) and are not faked as
context. "Decision memory" is real historical data (completion/dropout rate, prior
exposure to the same survey, allocation recency) re-queried from
`SurveyResponse`/`Allocation` on every call — no vector store, no fine-tuning
loop, per the user's own "simplest architecture that works reliably" guidance.
`AllocationService.allocate()` (Slice 9) executes the AI's ranked choice
unchanged, including its existing atomic quota/fallback mechanics — this slice
adds no new execution path, only the ranking layer in front of it. Test count:
278 → 289.

**2026-09-06, continued — Slice 16 (AI Operations)**: per explicit user
instruction not to turn every operational workflow into hard-coded rules either.
Three real, computable hard triggers (`no_traffic_7_days`, `low_conversion`,
`high_dropout`) feed a real `DecisionEngine.decide()` call; the response
(`INVESTIGATE`/`REQUEST_CLIENT_STATUS`/`PAUSE`/`CLOSE`/`REACTIVATE`/`ESCALATE`/
`NO_ACTION`) is validated against a closed set and a state-validity guard
(`CLOSED` terminal, `REACTIVATE` only from `PAUSED`/`PENDING_CLIENT_RESPONSE`)
before any write happens. Same-day-same-trigger idempotency prevents a future
scheduler from re-deciding an unresolved condition every run. `Survey` gained
`operational_status` and `ai_decision_subject_id` — the latter generalizing
Slice 15's `Allocation.ai_decision_subject_id` pattern per explicit user
instruction to use it "throughout the rest of Torpedo." Two triggers named in
the user's fuller wishlist (supplier/provider-failure-rate, client-response/
deadline-driven triggers) are honestly NOT_STARTED — no persisted failure-rate
metric and no `Study`/client-contact data model exist yet, and fabricating
either would be exactly the no-fake-completion failure this rebuild's
discipline exists to prevent. Test count: 289 → 307.

**2026-09-06, continued — Slice 17 (AI Finance)**: the user raised the testing
bar explicitly — prove AI can participate in money movement without becoming
the accounting authority. `AIFinanceService` writes to Mongo nowhere; every
actual balance change goes through the real, unchanged Slice 8
`PaymentService`/`ReconciliationService`. AR follow-up and payment matching are
proven never to alter a balance/status except through that governed path — a
direct test simulates the exact "client says they paid invoice 1042" email
scenario (Slice 12's `record_external_entry()`-only write) and shows the
invoice stays `sent`, not `paid`, until this slice's real matching step
executes. AP stays deliberately asymmetric: `decide_ap_followup()` never
initiates an actual outgoing payment, only ever recommends one, proven by
asserting zero `Payment` records exist after a `SCHEDULE_PAYMENT` decision.
`Invoice`/`Bill` gained `due_at` (real, optional — AR/AP follow-up needs it to
mean anything) and `ai_decision_subject_id` (the `Allocation`/`Survey`
traceability pattern, Slices 15-16, generalized again). Margin/Cint/billing
linkage is explicitly NOT started here — correctly sequenced to Slice 18, not
fabricated to look further along. Test count: 307 → 323.

**2026-09-06, continued — Slice 18 (the economic chain: Cint adapter + billing
+ margin) + final security/governance audit + end-to-end integration test**:
closes the loop Slice 17 explicitly deferred. `app.panel.cint_provider.CintSurveyProvider`
is a real (not stubbed) `SurveyProvider` implementation, built from v1's actual
verified `Supply/v1/SupplierLinks` entry-link endpoint/auth-header shape (read
from v1's `cint_integration.py` as reference material, not copied given register
D-defects §2.0-2.9) — `get_survey_provider()` now returns it by default;
`refresh()` honestly raises `SurveyProviderUnavailable` rather than parsing v1's
never-actually-called `LEGACY_SURVEY_DETAIL_ENDPOINT`, whose response shape is
unverified. `app.panel.billing.SurveyBillingService` is the new economic chain
— `record_billable_completion()` (supplier-cost snapshot, idempotent against a
later `Survey.cpi` change), `generate_client_invoice()`/`generate_supplier_bill()`
(both require the real `Survey.opportunity_id`/`client_rate` fields added this
slice, never double-bill, write only through the unchanged Slice 8
`InvoiceService`/`BillService`), and `compute_margin()` (real revenue minus real
supplier cost, `margin_pct: None` rather than a fabricated percentage when there's
no client rate). `PanelAllocationAIService._survey_context()` gained
`client_rate_minor` alongside `cpi_minor` as real margin-aware ranking context.

The `ai_decision_subject_id` traceability pattern (Slices 15-17) was generalized
to three more entities per the user's standing instruction to use it "throughout
the rest of Torpedo": `InboundEmail` (stamped by `EmailAIService.analyze_and_route()`),
`LeadEnrollment` (stamped by `OutreachAIService.decide_and_act()`), and `LeadState`
(stamped by `LeadGenAIService.evaluate_icp()` — deliberately a *different* field
from the pre-existing, locked `icp_score`, which stays owned exclusively by
`app.leadgen.scoring`'s canonical scorer; a test proves both facts at once).

A full security/governance audit (direct DB writes, ungoverned financial writes,
unrestricted sends, suppression/quota bypass, missing authorization/idempotency/
audit records, decisions without proposal records, proposals without entity
traceability, candidate IDs outside the offered set) found one real cleanup item
(an unused `payments_repo` constructor parameter on `AIFinanceService` — all
payment writes already correctly went through the governed `PaymentService`; the
dead parameter was removed) and the three traceability gaps above — everything
else audited clean, by construction, across all seven AI-touched domains.

One comprehensive end-to-end integration test
(`tests/test_end_to_end_business_loop.py`) now proves the full business loop in
one composed run: GSC signal → AI lead generation → real Account/Person → AI ICP
evaluation → (manual, honestly-not-automated) Opportunity creation → Survey →
eligibility gate → AI panel allocation → completion → billable completion →
client invoice → supplier bill → invoice approval/send → client payment →
AI-matched reconciliation → paid invoice → margin → AI operational evaluation →
(manual, honestly-not-automated) outreach enrollment → AI outreach follow-up →
final audit trail (exactly one `AiProposal` per AI decision, all through the
*same* shared `DecisionEngine` instance — the literal, executable proof there is
no second, isolated decision engine anywhere in this loop). Test count: 323 → 345.

**What remains genuinely blocked, not just unscheduled**: `RUNPOD_API_KEY`
(actually renting a GPU node), `CINT_API_KEY`/`CINT_SUPPLIER_CODE` (the live
Cint API), Google Search Console credentials (real GSC signals), and real email
provider credentials (`SendProvider`/`EmailIngestionProvider`) — every code path
behind each of these fails loud with a distinct, named exception rather than a
fabricated success. Software-complete and credential-blocked are two different
statuses, tracked separately throughout this document on purpose.

**2026-09-06, continued — Slice 19 (Phase 14: scheduler/event bus)**: per
explicit user direction after the Slice 18 completion report — build the
autonomous operating loop's heartbeat *before* activating any external
credential, because until something calls `detect_triggers()`/`list_open()`/etc.
on a cadence, every AI decision this rebuild built is still request-triggered
only, never autonomous. `app.scheduler.models.Event` is a real
`CanonicalDocument` (`event_type`/`entity_type`/`entity_id`/`occurred_at`/
`processing_status`, plus `dedupe_key` for idempotency, `payload`/`result` for
detection/processing context). `EventDetectionService` wires up seven real,
computable triggers — `survey_operations_trigger`, `ar_followup_due`,
`ap_followup_due`, `reconciliation_unmatched` (a new
`ReconciliationService.list_unmatched()` method, same "list_open() feeds the
scheduler" pattern as Slice 17's own methods), `lead_icp_evaluation_due` (a
qualified-or-further `LeadState` never ICP-evaluated, using real
`Account.industry`/`domain`/`Person.title` as context), `email_classification_due`,
`outreach_followup_due` (skipped entirely for any org with no active `Mailbox`
configured — never a fabricated `mailbox_id`) — each reusing an existing
detector/query rather than reimplementing one. Two triggers from the user's
fuller wishlist ("new GSC opportunity", "pending panelist allocation") are
honestly not built: no site-registry entity exists in the schema for the
first, and allocation happens per-respondent at request time, not on a
schedule, for the second. `EventOrchestrator` dispatches each `Event` to the
*same* real AI service every prior slice already built — never a new decision
path — claiming single-flight via `CanonicalRepository.update()`'s existing
optimistic-concurrency guarantee, recording a recoverable failure
(`LLMUnavailable`, right now, for every real handler call — no GPU credential
exists yet) as `FAILED`/retryable up to `MAX_ATTEMPTS`, never fabricated as
success. Per explicit user instruction, this is deliberately **not Celery** —
the VM's hardware constraints (this checklist's own hard-blockers table) make
a broker + worker process real new weight; `POST /internal/scheduler/tick`
(HMAC-signed, reusing `app.panel.callback_security` unchanged) plus a systemd
timer (`backend_v2/deploy/torpedo-v2-scheduler.timer`, every 5 minutes)
achieves the same "runs on a cadence, idempotent, restart-safe" outcome on the
same FastAPI process already running — `EventOrchestrator` itself doesn't know
or care how it's invoked, so swapping to Celery later needs zero change to it.
Test count: 345 → 380.

**Recommended roadmap from here, per explicit user direction**: activate
external integrations one at a time, not simultaneously — GPU/local model
first (it proves the actual AI Gateway → DecisionEngine production path every
other activation depends on), then Cint, then email, then GSC — followed by a
controlled production pilot monitoring AI decisions, conversion, margin,
failures, and human overrides. Credentials go into the server's environment
mechanism directly, never into a chat prompt or a commit.

**2026-09-06, continued — Slice 20 (shadow-mode activation safety gate)**:
per explicit user direction, built *before* touching `RUNPOD_API_KEY` (still
confirmed absent) — GPU activation must go through a shadow-mode validation
window first, so the mechanism that enables that has to exist before the
credential does, not be designed under time pressure after it lands.
`Settings.ai_shadow_mode` (default `True` in production) is a single,
narrowly-scoped gate across exactly the five points in this codebase where an
AI decision triggers real external/financial consequence: panel allocation,
survey pause/close/reactivate/escalate + provider refresh, payment matching,
and two email-send paths (email follow-up, outreach follow-up). Every one of
those methods still calls `DecisionEngine.decide()` and still records a real
`AiProposal` — decision-making is completely unaffected — only the
governed-service execution each would otherwise trigger is suppressed.
Deliberately NOT gated: email classification, lead ingestion (CRM record
creation), suppression, reconciliation-candidate recording, and outreach's
`sequence_state` label update — all already informational, protective, or
internal-only by each module's own pre-existing design, not the "sends
emails/allocates traffic/moves money" class of action the user's shadow-mode
instruction named. Every constructor's default is `shadow_mode=False`, so all
385 pre-existing tests (which construct these services directly) are
completely unaffected — only the five real DI providers (one per gated
service, across `panel`/`finance`/`emailai`/`leadgen`'s `routers.py`) read
`Settings.ai_shadow_mode` and wire it through. `GET /api/v1/integrations/status`
now reports `ai_shadow_mode: "ON"/"OFF"`. `docs/GPU_ACTIVATION_RUNBOOK.md` is
the full 18-step checklist (provision → verify model → resilience → full
suite + real end-to-end test against the live model → shadow-mode window →
progressive autonomy) written now, so the moment the credential is configured
server-side, activation goes straight into disciplined validation. Test
count: 380 → 385.

**2026-09-06, continued — master completion-and-productionization audit
(user's 45-section program)**: audited the actual current repository (git
log, live VM state, targeted greps) rather than trusting prior-session
assumptions, per the program's own explicit instruction. Found and flagged
one issue entirely outside Torpedo v2's scope: a live-looking Gmail app
password hardcoded in `scripts/email/test_smtp.py` (a single commit, outside
both `backend/` and `backend_v2/`) — reported to the user directly; rotating
or scrubbing it is the user's call, not something touched unilaterally.
Built a completion matrix across the program's domain list; most items were
already real (verified, not re-guessed) or honestly credential-blocked. Two
concrete gaps were real and tractable, and got fixed this pass:

- **Slice 21 — real SMTP send transport.** `get_send_provider()` had
  returned `StubSendProvider()` unconditionally in production since Slice 7 —
  every AI-decided and human-triggered email send "succeeded" against a
  fabricated `stub-{uuid}` id, even outside shadow mode, exactly the kind of
  appearance-over-reality gap the program's own §43 exists to catch.
  `app.outreach.smtp_provider.SmtpSendProvider` is the real replacement
  (stdlib `smtplib`, wrapped in `asyncio.to_thread()` so it never blocks the
  event loop — no new async-SMTP dependency added, matching the "don't
  over-engineer" instruction), credential-gated via `SMTP_HOST`/
  `SMTP_USERNAME`/`SMTP_PASSWORD` and failing loud (`SendProviderUnavailable`,
  a `SendFailed` subclass — `MessagingFacade.send()`'s existing failure
  handling applies unchanged) when unconfigured, confirmed absent from this
  environment. `GET /integrations/status`'s `email_send_provider` now checks
  the real env vars instead of being hardcoded `NOT_CONFIGURED`.
- **Slice 22 — the human review queue.** `AiProposal`'s own docstring had
  flagged this gap since Slice 6/7 ("never 'pending' yet, no human review
  queue built"). `app.governance.approvals.ApprovalService` +
  `GET/POST /governance/proposals` let a human record a real verdict
  (APPROVE/REJECT/MODIFY/DEFER/ESCALATE + notes) on any AI proposal, with
  reviewer/timestamp captured — additive to, and independent of, `status`
  (the system's own auto-apply verdict), which a review never rewrites.
  Deliberately does not yet re-execute a shadow-mode-suppressed action on
  APPROVE — each of the five gated services has its own idempotency/
  candidate-set discipline, and wiring generic review-triggered re-execution
  before the shadow-mode validation program has actually run would be the
  same half-correct-shortcut failure mode the program's §43 names explicitly.
  This is the honest next increment, not silently pretended to already work.

Test count: 385 → 405. The program's remaining 43 sections span a genuinely
multi-week scope (a full admin/BI frontend doesn't exist in this repository
at all; cost/observability/evaluation-framework infrastructure is real,
valuable, unbuilt work) — not claimed complete here, per the program's own
explicit instruction not to declare completion prematurely.

**2026-09-06, continued — Phase 1 of the dependency-aware program (production
foundations): security audit, fake-provider audit, AI cost/latency tracking,
retry/idempotency hardening, observability.**

- **Security**: re-scanned the whole tracked repository (not just
  `backend_v2`) for hardcoded credentials. Found and reported directly to the
  user — never touched unilaterally — a live-looking Cint API key + supplier
  code (`6777`) hardcoded across six `scripts/cint/`, `scripts/diagnostics/`,
  `scripts/entry_links/` files (in addition to the Gmail app password already
  found last pass). `Campaign_platform/.env.production` was checked and ruled
  out — one line, a public frontend `VITE_API_URL`, not a secret.
- **Fake-provider audit**: grepped `backend_v2/app/` for
  fake/mock/stub/dummy/placeholder classes, TODO/FIXME/HACK markers, and
  hardcoded-success returns. Found exactly two `Stub*` classes
  (`StubSendProvider`, `StubSurveyProvider`) — both already confirmed
  test-only, neither reachable as a production default (verified in the prior
  Slice 21 pass and this one). Confirmed every `Protocol` boundary's actual
  production default: real-and-credential-gated (Cint, SMTP) or
  honestly-`NullXProvider`-and-failing-loud (GSC) — never a silent fake
  success anywhere in production code.
- **AI cost/latency tracking** (`AiProposal.latency_ms`/`prompt_tokens`/
  `completion_tokens`/`total_tokens`, `LLMResponse` gained the same three
  token fields): latency is measured with real wall-clock timing
  (`time.perf_counter()`) around every `DecisionEngine.decide()` call — works
  today even against `FakeLLM` in tests (near-zero, still real, never
  fabricated). Token counts are parsed from the real OpenAI-compatible
  endpoint's own `usage` object (`GpuBrokerLLMProvider` already targets
  `/chat/completions`, which vLLM/most OpenAI-compatible servers populate)
  when present, `None` — never `0`, never invented — when absent. A
  dollar-cost-per-decision figure is deliberately NOT computed: no real GPU
  $/hour rate is configured anywhere in this codebase, and inventing one
  would be exactly the fabricated-data failure this rebuild's discipline
  exists to prevent.
- **Retry/idempotency hardening** (`app.indexes.ensure_indexes()`, called
  from a new FastAPI `lifespan` startup hook — confirmed to never fire
  against `TestClient(app)` used directly, which is how all 405 pre-existing
  tests use it, so this only ever runs against the real deployed database):
  real, enforced compound unique indexes on `(org_id, idempotency_key)` for
  `send_log_entries`/`payments` and on `dedupe_key` for `events` — the exact
  "no index infrastructure exists yet" gap `app.outreach.service`'s own
  module docstring named since Slice 7. Every idempotency check in this
  codebase was already a `find_one`-before-`insert` (correct for the
  practical sequential-retry case); the index is the backstop for genuine
  concurrent races, turning a previously-silent duplicate-write possibility
  into a loud, unswallowed `DuplicateKeyError`.
- **Observability**: extended `GET /integrations/status` (already the
  de facto system-health endpoint) with `scheduler_events` (real
  PENDING/PROCESSING/PROCESSED/FAILED counts from `app.scheduler.models.Event`)
  and `governance_pending_review` (real backlog size from the Slice 22 review
  queue) rather than building a duplicate endpoint — closing the "single
  glance production health" gap on top of infrastructure that already existed
  (`/ai/gpu/status`, `/internal/scheduler/events`).

Test count: 405 → 411. Phase 1 (production foundations) is substantively
complete for what's buildable without a live external credential; Phase 2
(AI production platform / GPU activation) is next, per the program's own
explicit phase order, and remains blocked on `RUNPOD_API_KEY`, confirmed
absent.

**2026-09-06, continued — Phase 2 of the autonomous end-to-end program (AI
production platform), the non-GPU-dependent slice.** Re-verified state (git
log, VM services, `RUNPOD_API_KEY`/`CINT_API_KEY` both still confirmed
absent) before continuing, per the program's own "verify, don't assume"
instruction.

- **Prompt versioning**: `DecisionEngine.PROMPT_VERSION` ("v1") is now
  recorded on every `AiProposal` (`prompt_version` field). Model/model
  version were already captured (Slice 11); this closes the other half —
  "did the prompt change" is now answerable the same way "did the model
  change" already was.
- **Adversarial hardening tests** (`tests/test_ai_decision_engine_adversarial.py`,
  9 tests): the structural prompt-injection guarantee this codebase relies
  on — business data (attacker-influenceable: an email body, a lead's
  company name) is proven to reach only the user message's JSON `context`
  key, byte-for-byte never touching the system prompt — is now an executable
  test, not just an architectural claim. Plus: confidence-threshold boundary
  (exactly 0.70 vs 0.699), a decision object wrapped in a list (rejected, not
  silently unwrapped), extra unexpected fields (accepted, not rejected — not
  the same failure mode as a malformed response), and regression coverage
  for the new latency/token/prompt-version telemetry.
- **AI evaluation harness** (`app.ai.evaluation.EvalCase`/`run_evaluation`/
  `summarize`, `tests/test_ai_evaluation.py`, 4 tests): a real, reusable
  harness — any `LLMProvider` in, a pass/fail/hallucination-rate summary out.
  Runs against `FakeLLM` today (no real model exists yet); the exact same
  harness runs against the real `GpuBrokerLLMProvider` with zero code change
  the moment `RUNPOD_API_KEY` is configured — this is
  `IMPLEMENTED — LIVE CREDENTIAL REQUIRED` for actual evaluation-against-a-
  real-model, but the infrastructure itself is complete and tested now. Its
  honest scope: fixture-specific acceptance + candidate-set-hallucination
  detection, not general business-correctness scoring (that needs Phase 12's
  real decision→outcome data, not a fixed fixture set).
- **Everything else on Phase 2's list was already real**, verified rather
  than re-built: GPU broker/lease (Slice 11, 38 tests, never run against real
  hardware), structured JSON + schema validation (`Decision`'s own Pydantic
  model), hallucinated-ID/candidate-set enforcement (per-domain, tested since
  Slices 15-18), tool authorization (`ToolRegistry` is caller-driven only —
  nothing is currently model-invoked, so "unauthorized tool call" risk is
  zero by construction, confirmed via the existing
  `test_tool_registry_is_described_to_the_model_but_never_auto_invoked`
  test), duplicate-decision protection (per-domain idempotency, Slices 15-18),
  AI cost/latency tracking (Phase 1, this same pass). Stale-proposal
  protection needed no new work: date-scoped subject_ids (AR/AP/Operations)
  already can't go stale by construction, and single-shot subject_ids
  (allocation/match) don't recur by construction either.

Test count: 411 → 424. GPU activation itself remains
`IMPLEMENTED — LIVE CREDENTIAL REQUIRED`, per `docs/GPU_ACTIVATION_RUNBOOK.md`
— everything achievable without `RUNPOD_API_KEY` is now done. Phase 3
(lead/sales/opportunity engine) is next.

**2026-09-06, continued — Phase 3 (lead/sales/opportunity engine): AI-driven
Lead → Opportunity conversion.** This closes the single most consistently-
flagged gap across this entire rebuild — every README/checklist entry since
Slice 18 named "no automatic Lead→Opportunity conversion anywhere in the
codebase" as an honest, documented gap. `app.leadgen.ai_conversion.LeadConversionAIService`
is the real fix, same architecture as every prior AI slice.

- **Deterministic eligibility, same "offer the walls" discipline**: only a
  `LeadState` already `QUALIFIED`/`ASSIGNED`/`ENROLLED` (cleared
  `app.leadgen.scoring`'s canonical qualification bar) with a real
  `account_id` is ever offered to the model as a candidate at all —
  `list_conversion_eligible()`.
- **A real architectural conflict was found and resolved, not papered
  over**: `LeadState.ai_decision_subject_id` was already owned by ICP
  evaluation (Slice 13). Reusing it for conversion would have silently
  overwritten the ICP trace the moment a lead was evaluated for conversion.
  Fixed by adding a second, distinct field —
  `ai_conversion_decision_subject_id` — so two different AI decisions can
  independently touch the same `LeadState` without one erasing the other's
  audit trail.
- **`LeadState.state = CONVERTED` was a reserved value with zero writers
  anywhere in this codebase before this slice** (defined Slice 4/6, excluded
  from `LeadGenService.ingest()`'s "reuse a non-terminal lead" query, but
  never actually set). This is the first real writer.
- **Shadow-mode gated — the sixth service this applies to.** Creating a real
  `Opportunity` is consequential (it can become a real `Invoice` downstream
  via `OpportunityService.convert_to_invoice()`), so `CONVERT` is held back
  in shadow mode exactly like the other five gated execution points. HOLD/
  REJECT/shadow-suppressed decisions still stamp
  `ai_conversion_decision_subject_id` — the same "every decision is
  auditable" discipline every other domain applies, and also what keeps
  Phase 14's scheduler from re-offering the same lead on every single tick
  (a human calling `POST /leads/{id}/ai/convert` directly has no such
  one-shot gate, and can always reconsider a HELD lead on demand).
- **Wired as an eighth Phase 14 scheduler trigger** (`lead_conversion_due`),
  the same detect→event→orchestrator-dispatch pattern as the other seven.

Test count: 424 → 440.

**2026-09-06, continued — Phase 4 (AI outreach): deterministic reply
detection.** Audited Phase 4's list against what already existed
(sequencing/follow-up/scheduling/suppression/bounce/budget/kill-switch/
idempotency were all already real, from Slices 7/14/19) and found one
concrete, honest gap: `LeadEnrollment.sequence_state` could reach
`RESPONDED`, but nothing ever set it from a real inbound reply — only the
AI's own scheduled `evaluate_outreach()` re-evaluation could *guess* at it
from indirect context (contactability, ICP score), never from the actual
fact that someone replied.

- **`EMAIL_CLASSIFICATIONS` gained `OUTREACH_REPLY`.** When
  `EmailAIService._route()` sees it, it deterministically (no AI judgment
  involved in the *action*, only in the classification itself) looks up the
  sender via a new `IdentityService.find_person_by_email()` — a pure,
  read-only lookup, deliberately distinct from `resolve_person()`, which
  would incorrectly create a new `Person` for a stranger who happens to
  email in. If a matching, non-`STOPPED` `LeadEnrollment` exists, its
  `sequence_state` is set to `RESPONDED` — a real fact, recorded the moment
  it's known, not inferred later on a schedule.
- **A second, separate finding from the same pass**: `classify_email` had
  no `task_instructions` at all — unlike every other AI task in this
  codebase, the model was never explicitly told what `EMAIL_CLASSIFICATIONS`'
  actual values are. Fixed with `_CLASSIFY_TASK_INSTRUCTIONS`, enumerating
  the full closed set plus `extracted_entities` guidance for SALES_LEAD/
  INVOICE/PAYMENT/BILL — a real correctness fix that predates and is
  independent of the `OUTREACH_REPLY` addition, surfaced by the same
  "why isn't this classification obviously reachable" audit question.
- **Multi-contact outreach remains honestly not built** — `LeadState.person_id`
  is still singular in this data model (unchanged since Slice 14's own note);
  faking a selection algorithm over what's still a single-item list would be
  decoration, not a feature.

Test count: 440 → 445.
