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
| **Cint API credentials** | No live Cint credentials found in this environment; v1's existing `cint_integration.py`/`cint_service.py` is the exact defective implementation the audit (register D-defects §2.0-2.9) already found broken — reference only, not portable as-is. | Real Cint API credentials + sandbox access. |
| **GSC / Google Search Console** | Only a stub reference in `seo_agent.py`; no working lead-gen pipeline exists in v1 or v2. | Google service-account/OAuth credentials for Search Console API. |
| **Real email sending (SMTP/SES/Gmail)** | `app.outreach.providers.SendProvider` is a tested `Protocol` with only a stub implementation (`StubSendProvider`) in v2. | Real provider credentials (v1's `outreach_engine`/`gmail_service` have some — need audit + credential migration, not reuse of v1's plaintext storage per D-26). |

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
| Actually renting a real GPU node | **NOT_STARTED — blocked on `RUNPOD_API_KEY`**, confirmed absent from this environment. `GPU_BROKER_ENABLED` also unset (off by default, as designed) |
| `LLMProvider` Protocol + `GpuBrokerLLMProvider` (`app.ai.llm`) | **TESTED** — 4 tests, fifth instance of this codebase's Protocol-boundary pattern |
| Central decision-contract schema (`app.ai.decision_engine.Decision`) | **TESTED** — matches master-prompt §7 field-for-field |
| `DecisionEngine.decide()` — context → model → structured decision → audit log | **TESTED** — 9 tests. Never executes an action; a caller reads the `Decision` and acts through existing permission-gated services |
| Tool registry (`app.ai.tools.ToolRegistry`) | **TESTED**, deliberately minimal — a caller-driven context-fetcher registry, not live LLM-invoked function-calling (that needs a real running model to validate against, which needs the credential above) |
| Decision audit log | **DONE** — reuses `AiProposal` (Slice 6/7), not a second entity; `status` stays binary (`approved`/`rejected`) per its documented Slice 6 scope, with `requires_human_approval` preserved inside `proposed_fields` rather than silently collapsed |
| Governance validator (AI never gets unrestricted DB access) | Structurally true by construction — nothing in `app.ai` imports a `CanonicalRepository` for any entity other than `AiProposal` (the audit log itself) |
| `GET /ai/gpu/status`, `POST /ai/gpu/shutdown` | **TESTED** — deployed |
| Real agentic tool-calling (model autonomously invoking registered tools) | NOT_STARTED — needs a running model to validate against |
| Wiring `DecisionEngine.decide()` into real domain callers (email, AR follow-up, survey ranking, ...) | NOT_STARTED — Slices 12-16 |
| Scheduled `sweep()` (idle/orphan reaping on a cadence) | NOT_STARTED — Phase 14 (scheduler infrastructure) |

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
| Model choosing outside the eligible set | **TESTED** — rejected outright, not silently dropped |
| Decision→allocation traceability | **TESTED** — `Allocation.ai_decision_subject_id` links back to the `AiProposal` that chose it |
| Demographic profile-fit / fraud-risk signals in allocation context | **NOT_STARTED, honestly** — no consent-gated profile system or fraud-detection pipeline exists yet; not fabricated as context |
| Panelist→survey suitability ranking | NOT_STARTED |
| Atomic allocation mechanics | **DONE (Slice 9)** — `AllocationService`, tested |

## Phase 10 — Cint adapter

| Item | Status |
|---|---|
| Real `CintProvider` behind `app.panel.providers.SurveyProvider` | NOT_STARTED (blocked — credentials) |
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
| Scheduler entrypoint to run detection periodically | NOT_STARTED — belongs to Phase 14 (event/scheduler infrastructure), not built yet; `detect_triggers()`/`detect_and_flag()` are callable but nothing calls them on a cadence |

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
| Margin (`Client → Study → Completes → Revenue/Cost`) | **NOT_STARTED, honestly, and correctly sequenced** — no `Survey`↔`Invoice` linkage exists beyond `Invoice.opportunity_id` (Slice 10); this is explicitly Slice 18's scope ("Cint + billing + margin"), not fabricated here |

## Phase 13 — Complete → billing → invoice → supplier bill → margin

| Item | Status |
|---|---|
| Survey completion → reward credit | **DONE (Slice 9)** — `CallbackService`, tested |
| Reward clawback on reversal (human-approval-gated) | **DONE (Slice 9)** — tested |
| Complete → client billing rate → invoice linkage | NOT_STARTED |
| Margin/profitability calculation (revenue − supplier cost) | NOT_STARTED |

## Phase 14 — End-to-end orchestration + event bus

| Item | Status |
|---|---|
| Internal event mechanism (`lead.created`, `invoice.overdue`, ...) | NOT_STARTED |
| Scheduler/background continuous loop | NOT_STARTED |
| Idempotent action execution under the event loop | Idempotency patterns exist per-slice (Slice 7/8/9 idempotency keys), not yet a general event-bus guarantee |

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
