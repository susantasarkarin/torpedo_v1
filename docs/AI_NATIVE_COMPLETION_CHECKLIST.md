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
| GSC data ingestion | NOT_STARTED (blocked — credentials) |
| AI ICP scoring reusing `app.leadgen.scoring` | NOT_STARTED |

## Phase 7 — AI outreach + email intelligence

| Item | Status |
|---|---|
| Email classification/extraction/summarization | NOT_STARTED |
| AI-drafted outreach through `MessageDrafter` (already a tested `Protocol`, Slice 7) | Protocol exists, no real drafter |

## Phase 8-9 — Survey Pool AI + panelist allocation AI

| Item | Status |
|---|---|
| Deterministic >20% conversion eligibility gate | **TESTED** (2026-09-06) — `CONVERSION_ELIGIBILITY_THRESHOLD` in `app.panel.service`, enforced inside `_reserve_quota()` so it applies on every retry, not just the first check |
| AI ranking within the eligible set | NOT_STARTED — blocked on AI Gateway (Phase 2/3) |
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
| AI investigation/decision (pause/close/reactivate/escalate) | NOT_STARTED — blocked on AI Gateway (Phase 2/3); the detector only flags via one `study_inactive_detected` Activity, it never acts |
| Scheduler entrypoint to run detection periodically | NOT_STARTED — belongs to Phase 14 (event/scheduler infrastructure), not built yet; `detect_and_flag()` is callable but nothing calls it on a cadence |

## Phase 12 — Finance AI (AR/AP, reconciliation)

| Item | Status |
|---|---|
| Partial payment accounting | **DONE (Slice 8)** — `PaymentService.record_payment`, tested |
| Payment reversal | **DONE (Slice 8)** — tested |
| AI-driven AR follow-up (vs. fixed-schedule reminders) | NOT_STARTED |
| AI-driven AP follow-up | NOT_STARTED |
| AI-assisted bank↔payment↔invoice reconciliation | NOT_STARTED — `ReconciliationService` (Slice 8) proves the model + match invariant only, no matching intelligence |
| Supplier reconciliation | **DONE (Slice 9)** — `SupplierReconciliationService`, flags disagreement, tested |

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
