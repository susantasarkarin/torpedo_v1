# Local SLM (Qwen2.5-0.5B) cheap-role audit

**Scope: local SLM / cheap role only. Bedrock, smart role, outreach generation,
customer-facing generation, credentials, and production configuration were not
modified except where explicitly noted in §12 (the pilot enable/disable this
audit itself investigated).**

**Final status: FIX BEFORE ENABLEMENT.** See §14.

## 1. Executive summary

The concurrency architecture validated in the previous report
(`LOCAL_SLM_CHEAP_ROLE_VALIDATION.md`) is sound and remains sound — the gate,
timeout separation, and retry classification all behaved exactly as designed
under real production load. But **this audit was triggered by, and confirms,
a real production failure**: during a brief live pilot (enabled, then rolled
back mid-audit — see §12), every single real `cheap`-role call failed. Root
cause: the "cheap" role is not one workload, it's several, with very
different prompt sizes, and the 12s inference timeout tuned against the
shortest of them (lead classification) is routinely exceeded by the longest
(inbound email analysis). A second, independent problem was found in a code
path that has no local-model equivalent at all (batch job submission). Both
are fixable; neither was fixed as part of this audit, per its read-only
scope.

## 2. Complete SLM call inventory

Repo-wide search for `local:qwen2.5`, `SELF_HOSTED_BASE_URL`,
`do_inference_client`, `LocalLLM`, `local_llm_gate`, `role="cheap"`, and
`8003` across `backend/` (excluding tests):

| File | Calls `role="cheap"` | Prompt shape | Notes |
|---|---|---|---|
| `leads/bucket_classifier.py` | Yes (`CLASSIFIER_ROLE_FIRST_PASS`) | Short — fixed lead-profile fields, ~6 lines | Also calls `role="smart"` for escalation — see §9 finding |
| `sales/mail_pool_ai.py` | Yes (`MAIL_AI_ANALYSIS_ROLE`) | **Long — full email body + 15-field nested JSON schema** | Root cause of the production failure, §12 |
| `leads/icp_query_ai.py` | Yes | Short — generates N search query strings | Not load-tested this session; prompt shape suggests low risk |
| `leads/ingestion.py` | Yes | Moderate — extracts leads from search result snippets | Not load-tested this session |
| `leads/ingestion_vm.py` | Yes | Moderate — same extraction, VM variant | Not load-tested this session |
| `leads/backfill_enrich.py` | Yes, but via **Bedrock batch API** (`submit_batch_job`) | N/A | **Incompatible with `local:` prefix — see §7 finding** |
| `ai_governance/ai_gateway.py` | Indirect, via `_call_llm(role="cheap")` default | Varies by caller (classify_email, summarize_email, etc.) | Fixed this session (previously bypassed the gateway entirely — see prior commit `0e326e3`) |

**Direct-bypass check**: `grep` for any caller of `do_inference_client.chat()`
outside `bedrock_client.py` — **none found**. The only call site is
`bedrock_client.py:528` (`_call_self_hosted`), which is gated. No code path
reaches `127.0.0.1:8003` except through `local_llm_gate.py`.

**Dormant risk, not currently active**: `backend/infra/gpu_lease.py`'s
docstring shows an example setting `os.environ["SELF_HOSTED_BASE_URL"]` to
point at a *rented GPU pod* (RunPod), reusing the exact same env var names
this work uses for the local llama-server. `lease_gpu()` has **zero
production callers today** (only its own test file uses it) and the
`os.environ[...]` lines are documentation, not executed code — so there is
no active collision. But if `lease_gpu()` is ever wired into a real feature
without renaming one of the two conventions, it would silently redirect
cheap-role traffic to a GPU pod or vice versa. Worth a rename before that
happens, not urgent today.

## 3. Caller-to-llama-server architecture map

```
bucket_classifier.py ─┐
icp_query_ai.py ───────┤
ingestion.py ──────────┼─► bedrock_client.converse*(role="cheap")
ingestion_vm.py ───────┤        │
ai_gateway._call_llm ──┘        ▼
                         model_for_role("cheap") resolves the chain
                                 │
                    starts with "local:..."?
                          │              │
                         yes             no
                          │              │
                          ▼              ▼
              _call_self_hosted()   _call_converse() (real Bedrock/DO)
                          │
                          ▼
         local_llm_gate.acquire_local_llm_slot()   <- ONLY gate in the codebase
              (Redis BLPOP, capacity 1, queue timeout 5s)
                          │
                          ▼
              do_inference_client.chat(timeout=12s)
                          │
                          ▼
              llama-server 127.0.0.1:8003 (Qwen2.5-0.5B, --parallel 1)

backfill_enrich.py → submit_batch_job(role="cheap") → model_for_role("cheap")
                     used DIRECTLY as an AWS modelId, no gate, no local: check
                     -- NEVER reaches llama-server; would hard-fail against
                     AWS if the resolved value starts with "local:"
```

## 4. Cheap-role usage verification

Confirmed by direct code trace (§2/§3): every synchronous cheap-role caller
routes through `bedrock_client.converse()`/`converse_json_object()` →
`model_for_role("cheap")` → (if `local:`) `_call_self_hosted()` →
`local_llm_gate` → `do_inference_client.chat()`. No caller constructs its own
client or calls the local server's URL directly.

## 5. Forbidden-role verification

`grep`-confirmed and live-verified (both before and after the pilot):
`BEDROCK_MODEL_SMART` was never set to a `local:` value at any point this
session. `models_for_role("smart")` resolved to `['qwen.qwen3-32b-v1:0',
'do:alibaba-qwen3-32b']` throughout — Bedrock/DO only, never local. The
outreach content-generation path (`cold_outreach_router._generate_personalised_email`,
`ai_gateway.generate_email_draft`/`draft_outreach_email`) all call
`role="smart"` explicitly and were rolled back to Bedrock in the prior
session specifically because a local model produced unsafe output there (the
identity-swap incident). Nothing in this audit found any path that could
route outreach/smart-role traffic to the local model.

**One real interaction found, not a violation**: `bucket_classifier.py` has
a `_roles_share_a_model()` check that previously made its smart-role
escalation path dead code (cheap and smart resolved to the same Bedrock
model, so escalating was pointless). With cheap→local and smart→Bedrock
genuinely different, **this escalation path is now live** — low-confidence
leads will generate a real, additional Bedrock smart-role call that
previously never fired. This is correct, intended behavior once the two
roles actually differ, not a bug — but it's a real behavior/volume change
worth knowing about, since it means enabling local-for-cheap doesn't just
change *where* cheap calls go, it also increases real Bedrock smart-role
call volume as a side effect.

## 6. Gate/concurrency verification

Re-confirmed this session (in addition to the prior validation report):
`max_concurrency()` returned `1` throughout. No env var override was set.
Only `bedrock_client._call_self_hosted` acquires the gate; nothing else
imports `local_llm_gate`.

## 7. Timeout/retry/failure audit

- **Queue timeout** (`LOCAL_LLM_QUEUE_TIMEOUT_SECONDS`, default 5s): proven
  correctly bounded in the prior validation report (6 trials at
  concurrency 5/10, every failure landed at 5.05-5.10s, never longer).
- **Inference timeout** (`LOCAL_LLM_INFERENCE_TIMEOUT_SECONDS`, default
  12s): **this is the problem**. It was tuned against
  `bucket_classifier`-shaped prompts (median 1.2-1.4s). `mail_pool_ai`'s
  prompt (full email body + 15-field nested schema) took **21.5s in one
  isolated test and did not complete within 40s in another** (see §8/§12) —
  routinely exceeding 12s by a wide margin, and exceeding even a generous
  40s under real contention.
- **Retry classification**: confirmed correct — `LocalLLMUnavailable` is in
  `_FAILOVER_CODES`, not `_RETRYABLE_CODES`. During the live pilot failure,
  there was no retry storm: each failure was a clean, single attempt,
  correctly classified, no `time.sleep` backoff against the same instance.
- **Failure handling**: confirmed safe. `bucket_classifier`'s own
  "10 consecutive model failures — aborting the batch" logic fired correctly
  and left leads unbucketed for the next run rather than guessing or
  crashing. `mail_pool_ai`'s equivalent ("[mail-ai] Bedrock throttled/outage
  — stopping sender run, leaving senders unmarked for retry") did the same.
  **The failure mode itself is exactly what the architecture was designed
  to produce — the problem is that it fired on essentially 100% of real
  calls during the pilot, not that it fired unsafely.**
- **`backfill_enrich.py`/`submit_batch_job` — not covered by any of the
  above.** This path never reaches `local_llm_gate` or
  `do_inference_client` at all; it calls AWS's `create_model_invocation_job`
  directly with whatever `model_for_role("cheap")` returns. If that's a
  `local:`-prefixed string, this would fail with an AWS API error (invalid
  model ID), not a graceful `LocalLLMUnavailable`. Not exercised during the
  pilot (no batch job happened to run in the window), so this is a code-
  read finding, not an observed failure — but it's real and unguarded.

## 8. Actual runtime usage (live pilot, this session)

A controlled pilot was enabled (`BEDROCK_MODEL_CHEAP=local:qwen2.5-0.5b-instruct`,
`BEDROCK_FALLBACKS_CHEAP=` empty) and monitored for ~30 minutes before being
rolled back once the root cause below was understood.

- **Observed failure rate: effectively 100%.** Every `mail_pool_ai`
  analysis call during the window failed with `LocalLLMUnavailable`; two
  separate `[mail-ai] Bedrock throttled/outage` aborts and one
  `bucket_classifier` "10 consecutive model failures" abort were logged.
- **Root cause, directly verified from `llama-server`'s own log**: every
  task's `launch_slot_` → `cancel task` gap was **exactly ~12 seconds** —
  the client-side inference timeout firing precisely on schedule, not a
  hang or a crash. `n_tokens` on these cancelled tasks (683-1438) was far
  higher than the benchmark's prompts, confirming these were
  `mail_pool_ai`-shaped calls (full email bodies), not
  `bucket_classifier`-shaped ones.
- **Isolated reproduction**: a realistic `mail_pool_ai`-shaped prompt
  (representative RFQ email body, the real system prompt and JSON schema)
  took **21.5s** in one run and **did not complete within 40s** in another
  — genuine variability, both far past the 12s default and the second past
  even a generous manual 40s test.
- **Resource impact during the failing window**: load average peaked at
  2.66 (well under any concerning threshold), backend latency stayed
  12-31ms throughout, swap stayed within its chronic baseline. **The VM
  itself was never at risk** — this was a clean, safe, but 100% failure
  rate, not a repeat of the original overload incident.
- Rolled back mid-audit once the pattern was clear; `cheap` role confirmed
  back on `['qwen.qwen3-32b-v1:0', 'do:alibaba-qwen3-32b']` before this
  document was written.

## 9. Output-quality audit

One anomaly observed, not fully root-caused: an isolated single-word test
call ("Reply with exactly: PONG") returned `'PING 192.0.2.1 2>&1'` instead —
syntactically valid as a string, but semantically unrelated to the prompt
and superficially resembling shell-command/networking-test content. This
does not match any known prompt-injection vector in this codebase and no
other test call reproduced anything similar; it may be a one-off decoding
artifact or `llama-server`'s KV-cache/prompt-prefix reuse ("LCP similarity"
reuse, visible in its own logs) bleeding content across a dissimilar prior
request. Flagged as an open question, not a confirmed defect — worth a
larger sample before trusting output quality broadly, but the *safety* nets
found in §7 (JSON-shape checks, confidence thresholds, the outreach
identity-swap validator) would catch this class of malformed/off-topic
output for any of the structured-JSON callers, since none of them accept a
bare non-JSON string as valid.

No hallucinated-identity or prompt-injection pattern was found in any
successful real classification output reviewed this session.

## 10. Resource audit (while actually in use)

Covered in §8 above and consistent with the prior validation report: load
average 1.0-2.66 across the live pilot window (vs. ~107 in the original
incident), backend latency 12-31ms throughout, no swap deterioration beyond
this VM's chronic baseline. Resource behavior is not the open problem here —
the timeout mismatch is.

## 11. Security audit

Re-confirmed this session:
- API key: rotated (prior session), lives in `/etc/torpedo-v2-llm.env`
  (mode 600) via `EnvironmentFile=`, absent from `ps aux`, absent from
  `journalctl -u torpedo-v2-llm`, never committed to git.
- `llama-server` binds `127.0.0.1` only (confirmed in its systemd unit,
  unchanged) — not reachable off-box.
- No secret appeared in any log line reviewed this session, including the
  failure logs from the pilot (`LocalLLMUnavailable` messages carry no
  key/token content, matching the dedicated regression test).
- Prompt content: `bucket_classifier`/`icp_query_ai` prompts carry lead
  profile fields (name, title, company) — no more sensitive than what
  already flows through Bedrock today. `mail_pool_ai`'s prompt carries full
  inbound email bodies, which may include third-party personal data — this
  is unchanged from its existing behavior calling Bedrock; routing it to a
  self-hosted, on-VM model is arguably a *smaller* data-exposure surface
  than sending it to a third-party API, not a new concern.

## 12. Problems found

1. **(Blocking) Inference timeout mismatch for `mail_pool_ai`.** The global
   `BEDROCK_MODEL_CHEAP` switch conflates short-prompt callers (safe,
   proven fast) with `mail_pool_ai`'s long-prompt caller (unsafe at the
   current 12s default, borderline even at 40s). Caused a ~100% real
   failure rate during this session's pilot. VM stayed healthy throughout —
   this is a correctness/availability problem, not a stability one.
2. **(Blocking for that one path) `backfill_enrich.py`'s batch-job
   submission has no `local:` handling.** `submit_batch_job` passes
   `model_for_role(role)` directly to AWS as a `modelId`; a `local:`-
   prefixed value would be rejected by AWS outright, with no graceful
   fallback (this path never reaches the gate or `LocalLLMUnavailable`
   handling at all).
3. **(Non-blocking, documentation-only) Error logging drops detail.**
   `bedrock_client.py`'s failure log lines record only the exception class
   name (`LocalLLMUnavailable`), not its message — diagnosing today's root
   cause required reproducing the failure manually with full tracebacks
   rather than reading it straight out of the logs.
4. **(Non-blocking, latent) `gpu_lease.py`/local-SLM env-var name
   collision**, described in §2 — zero current risk since `gpu_lease.py`
   has no production callers, but worth a rename before it does.
5. **(Non-blocking, unresolved) One anomalous output** (§9) — not enough
   evidence to call it a defect, not enough to dismiss it either.
6. **(Informational) `bucket_classifier`'s smart-role escalation is now
   live** (§5) — correct behavior, real new Bedrock call volume as a side
   effect worth monitoring if/when this is re-enabled.

## 13. Recommended fixes

For #1: give `mail_pool_ai` its own timeout configuration (or its own role
identifier entirely, e.g. `role="cheap_long"` with an independent
`BEDROCK_MODEL_CHEAP_LONG`), rather than sharing `LOCAL_LLM_INFERENCE_TIMEOUT_SECONDS`
with the short-prompt callers — a single global cheap-role timeout cannot
serve both profiles safely. Alternative: keep `mail_pool_ai` on Bedrock
permanently and enable local routing only for the genuinely short-prompt
callers (`bucket_classifier`, `icp_query_ai`, `ingestion`/`ingestion_vm`).

For #2: make `submit_batch_job` (or `backfill_enrich.py` itself) reject a
`local:`-prefixed model with a clear, immediate error — or better, have it
always resolve to the non-local fallback for batch specifically, since
batch has no local equivalent and never will.

For #3: log `str(exc)` alongside the exception class name in
`converse_meta`'s failure path.

For #4: rename one of the two `SELF_HOSTED_*` conventions before
`gpu_lease.py` gets a real caller.

None of these were implemented as part of this audit, per its read-only
scope — flagged here for a deliberate follow-up decision.

## 14. Final status

**FIX BEFORE ENABLEMENT.**

The concurrency/security architecture from the prior validation report holds
up completely — nothing found here contradicts it. But the *scope* of what
"enable the cheap role" actually means was broader than tested: it silently
included `mail_pool_ai`'s much heavier workload, which failed almost
universally in real use, and `backfill_enrich.py`'s batch path, which was
never exercised by the gate/timeout machinery at all. Fix #1 and #2 above
are both small, targeted, and don't touch Bedrock, smart role, or outreach —
once made, re-running a pilot scoped to the corrected caller set is the
right next step, not a fresh architectural review.

| Component | SLM used? | Purpose | Through gate? | Production-safe? |
|---|---|---|---|---|
| Lead classifier (`bucket_classifier`) | YES | Classification | YES | **YES** (proven, short prompts) |
| ICP query generation (`icp_query_ai`) | YES | Query generation | YES | Likely (not load-tested) |
| Lead extraction (`ingestion`/`ingestion_vm`) | YES | Structured extraction | YES | Likely (not load-tested) |
| Mail pool AI (`mail_pool_ai`) | YES | Inbound email analysis | YES | **NO** — timeout mismatch, §8/§12 |
| Batch enrichment (`backfill_enrich`) | YES (misconfigured) | Batch classification | **NO** — bypasses gate entirely | **NO** — would hard-fail, §7/§12 |
| Outreach (`cold_outreach_router`, `ai_gateway` draft methods) | MUST BE NO | Generation | MUST BE NO | Confirmed NO |
| Smart role (all callers) | MUST BE NO | — | MUST BE NO | Confirmed NO |
