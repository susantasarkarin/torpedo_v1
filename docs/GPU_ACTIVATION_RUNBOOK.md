# GPU / Local Model Activation Runbook

Written 2026-09-06, before `RUNPOD_API_KEY` was configured — this is the
checklist to execute *after* it lands, not a record of having run it. Per
explicit user instruction: activate one external integration at a time, GPU
first, because until this is proven, the AI Gateway → `DecisionEngine`
production path has never actually run against a real model — only against
`FakeLLM` test doubles. Do not activate Cint/email/GSC until this entire
runbook is green.

**Never paste `RUNPOD_API_KEY` (or any credential) into a chat prompt or a
commit.** It goes directly into `/var/www/torpedo-v2/backend_v2/.env` on the
VM, read once by `app.config.Settings` at process start.

## Preconditions (already true, verified this session)

- [x] `app.ai.gpu_lease`/`app.ai.gpu_broker` ported from v1, async, tested (38 tests)
- [x] `GpuBrokerLLMProvider`/`DecisionEngine` tested against `FakeLLM` (never a live model)
- [x] `app.config.Settings.ai_shadow_mode` defaults to `True` — every one of the
      five consequential execution points (panel allocation, survey operations,
      payment matching, email follow-up send, outreach send) is suppressed by
      default until this runbook's shadow-mode phase (steps 15-17) passes and a
      human explicitly flips it off
- [x] `/api/v1/integrations/status` reports `gpu_credential`/`gpu_broker`/`ai_shadow_mode`
      — the one place to check current state without shell access

## Phase A — Provision and verify the inference backend

1. **Provision the external GPU** (RunPod, per `app.ai.gpu_lease.RunPodDriver`).
   Set `RUNPOD_API_KEY` and `GPU_BROKER_ENABLED=true` in the VM's `.env`.
   Restart `torpedo-backend-v2.service` to pick them up.
2. **Select and download the Hugging Face model** onto the pod image/volume
   per whatever `RunPodDriver`'s pod template already specifies (v1's
   `gpu_lease.py` reference, ported unchanged in Slice 11) — do not change the
   model choice as part of this runbook; that's a separate decision.
3. **Verify model checksum/version** against what the pod template declares —
   a silently-swapped model would invalidate every decision made afterward.
4. **Start the inference server** and confirm `GpuBroker.acquire()` reaches
   `state: "ready"` (`GET /api/v1/ai/gpu/status`, `AI_READ` permission).
5. **Verify structured JSON responses**: call `DecisionEngine.decide()` once,
   directly (not through a business flow yet), with a hand-built context, and
   confirm the response validates as a real `Decision` — not a `FakeLLM` echo.

## Phase B — Resilience, under real network/hardware conditions

6. **Cold start**: measure and record actual time-to-ready from a cold
   `acquire()` (v1's docstring cites up to ~45 minutes worst case) — confirm
   `wait_for_ready()`'s timeout is still sane against the real number, not the
   value chosen when only `FakeLLM`/`httpx.MockTransport` existed.
7. **GPU lease/release**: confirm `touch()` correctly defers idle shutdown
   under real load, and `shutdown_now()`/the idle sweeper actually tear down a
   real pod (verify in the RunPod console, not just Torpedo's own registry
   state — the two must agree).
8. **Timeout/retry**: kill the pod mid-request; confirm `LLMUnavailable` is
   raised (not a hang, not a fabricated decision) and that Phase 14's
   `EventOrchestrator` correctly records the resulting `Event` as `FAILED`,
   retryable.
9. **Malformed model output**: confirm a non-JSON or schema-invalid real
   response raises `DecisionEngineError`, not a crash and not a silently
   accepted partial `Decision`.
10. **Hallucinated entity IDs**: confirm a real model naming a `survey_id`/
    `invoice_id`/etc. outside the candidate set it was actually offered is
    rejected by each service's own candidate-set check (`PanelAllocationAIError`/
    `AIFinanceError`/etc.) — these checks are already tested against
    `FakeLLM`; this step proves a real model's actual failure mode (not a
    contrived test string) still hits the same guard.
11. **Confidence thresholds**: observe real confidence values a live model
    returns across a range of real contexts — confirm they're not clustered
    at exactly `DECISION_CONFIDENCE_THRESHOLD` (0.70) in a way that makes
    `is_auto_appliable()` behave like a coin flip; if so, the threshold itself
    (not the mechanism) may need revisiting — a human decision, not Sonnet's.
12. **Human-review routing**: confirm a `requires_human_approval=True` real
    response is still never auto-applied regardless of confidence (already
    enforced in code — `Decision.is_auto_appliable()`), and that it's visible
    somewhere a human actually looks (`AiProposal.status="rejected"`,
    `proposed_fields.requires_human_approval` preserved).

## Phase C — Regression, against the real backend

13. **Run the full test suite** (482 as of Rev 41, 2026-09-08 — check
    `docs/business_rules_register.md`'s latest changelog entry for the
    current count rather than trusting this number, which will drift) —
    unchanged, still against `FakeLLM`/test doubles (they test the *code*,
    not the live model; that's Phase A/B's job).
14. **Run `tests/test_end_to_end_business_loop.py`'s scenario manually against
    the real model** — same business loop, real GPU — comparing the real
    model's decisions at each of the six AI-decision hops against the fake
    ones the automated test scripted. Record disagreements; they are data,
    not necessarily bugs.

## Phase D — Shadow mode (production data, no consequential execution)

15. **Confirm `ai_shadow_mode` is still `True`** in the VM's `.env`
    (`GET /api/v1/integrations/status` → `"ai_shadow_mode": "ON"`) before
    enabling the Phase 14 scheduler timer against real data, or before
    pointing any real request traffic at an AI-decided endpoint.
16. **Run in shadow mode against real business events** for an explicitly
    agreed window (the systemd timer already runs every 5 minutes; let it run
    unattended) — every `AiProposal` created is real decision-making against
    real Torpedo data, with zero consequential writes (no allocation, no send,
    no payment match, no survey pause/close).
17. **Compare AI proposals against expected/governed outcomes** — pull
    `AiProposal` records for the window (`org_id`, `task`, `confidence`,
    `proposed_fields`) and a human reviews them against what a human operator
    would have decided. This is the actual validation the entire rebuild has
    been building toward — no test suite substitutes for it. Built and tested
    ahead of this step (2026-09-08, before `RUNPOD_API_KEY` existed, so this
    tooling itself only runs against real shadow-mode data once GPU
    activation reaches this point): `GET /api/v1/governance/proposals/report?since=...&until=...&task=...`
    (`GOVERNANCE_READ`) — every `AiProposal` in the window, reviewed or not,
    unlike `GET /governance/proposals`'s live unreviewed-queue view. `since`/`until`
    are timezone-aware ISO-8601 datetimes; `task` narrows to one AI task.

## Phase E — Progressive autonomy (only after Phase D is reviewed and approved)

18. **Enable selected autonomous actions**, one category at a time, by
    flipping `ai_shadow_mode` to `False` — but per the user's own instruction,
    finance stays separately, permanently governed regardless: AP was already
    architected recommendation-only (`decide_ap_followup()` never calls
    `record_payment()`), and AR/payment-matching's auto-apply threshold
    (`DECISION_CONFIDENCE_THRESHOLD`) is a deliberate, separate dial from the
    shadow-mode switch — both exist, both matter, neither substitutes for the
    other. A suggested progression, not a hard rule:
    - Panel allocation (lowest external-facing risk — reversible, no money, no message sent)
    - Survey operations (pause/close/reactivate — reversible, internal-only)
    - Outreach/email send (external-facing — a human should review a sample of shadow-mode sends first)
    - Payment matching (last — reuses `record_payment()`'s existing idempotency/reversal path, but touches real money)

Only after this entire runbook is green — and only for GPU — does the
project move to Cint, then email, then GSC, one at a time, with the same
shadow-mode discipline applied fresh to each.
