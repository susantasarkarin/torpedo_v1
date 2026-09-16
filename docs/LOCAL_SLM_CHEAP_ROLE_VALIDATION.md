# Local SLM (Qwen2.5-0.5B) validation for the "cheap" role

**Status: SAFE TO ENABLE (cheap role only). Not yet enabled in production —
awaiting a deliberate go-ahead for the staged rollout below.**

**Bedrock and the smart role (outreach generation) are untouched by this work,
per explicit instruction. This document covers the cheap role only.**

## A. Root cause of the 2026-09-16 incident (VM load average ~107)

Four things compounded, confirmed from code and logs, not guessed:

1. **No admission control.** `torpedo-sales-worker.service` runs Celery with
   `--concurrency=2` — two forked processes could call the cheap role
   simultaneously with nothing stopping either from hitting `llama-server` at
   the same time.
2. **`llama-server --parallel 1`** serves exactly one request at a time;
   anything else queues invisibly at the HTTP layer.
3. **A 60s blanket timeout shared with real DigitalOcean calls**
   (`DO_INFERENCE_TIMEOUT`) let a queued/slow local call block for up to a
   full minute before the client even noticed a problem.
4. **A retry storm, not a fix.** That 60s timeout raised `DOThrottled`, which
   was in `_RETRYABLE_CODES` — so each worker independently retried the
   *same already-overloaded* local instance up to 3 times with exponential
   backoff, instead of backing off from it.

Not a model-size problem. A concurrency / timeout / retry-classification
problem.

## B. Final architecture

```
CHEAP  -> Qwen2.5-0.5B local -> Redis-backed bounded queue (BLPOP, capacity 1) -> max 1 inference
SMART  -> unchanged (Bedrock/DO -- untouched throughout this work)
```

- `backend/leads/local_llm_gate.py` (new): cross-process concurrency gate.
  Redis list pre-seeded with `LOCAL_LLM_MAX_CONCURRENCY` tokens (default 1).
  Acquire = `BLPOP` (real blocking wait, native timeout =
  `LOCAL_LLM_QUEUE_TIMEOUT_SECONDS`, default 5s) — not a polling loop.
  Seeding uses a `WATCH`/`MULTI` transaction keyed off a *separate* capacity
  marker, not the list's live length — a real bug caught during development
  (`test_second_caller_blocks_while_first_holds_the_slot`): topping up
  "whenever the list looks short" would hand a concurrent caller a
  freshly-minted token instead of making it genuinely wait, since a
  checked-out slot also makes the list short.
- `do_inference_client.chat()`: new optional `timeout` param, additive —
  real DigitalOcean calls unaffected. The local path uses its own, shorter
  `LOCAL_LLM_INFERENCE_TIMEOUT_SECONDS` (default 12s) instead of the 60s
  default meant for a real remote provider.
- `bedrock_client._call_self_hosted()`: wraps the call in the gate. Any
  failure (queue timeout, inference timeout, transport error) is wrapped as
  the new `LocalLLMUnavailable` and classified in `_FAILOVER_CODES`, never
  `_RETRYABLE_CODES` — move to the next chain entry immediately instead of
  retrying the same overloaded local instance.
- `BEDROCK_FALLBACKS_CHEAP` set to explicitly empty — the cheap-role chain
  never touches Bedrock at all, per instruction to treat it as unavailable.

## C. Final llama-server config

**Unchanged from the original**: `--threads 2 --parallel 1 --ctx-size 2048`.

Tested alternatives (each with a full 10-sequential-request benchmark,
config reverted immediately after each test):

| Config | median latency | notes |
|---|---|---|
| `--threads 2 --ctx-size 2048` (current) | 1.29s | baseline |
| `--threads 1 --ctx-size 1024` | 2.29s | ~2x worse, no resource benefit |
| `--threads 2 --ctx-size 1024` | 1.20s | statistically indistinguishable from baseline |

Neither alternative justified a change.

## D. Performance

Real cheap-role-shaped prompt (`bucket_classifier.py`'s own
`SYSTEM_PROMPT`/`build_prompt` against a representative lead), not a toy
prompt.

| | min | median | p95 | max |
|---|---|---|---|---|
| Raw, sequential (n=10) | 1.18s | 1.29s | 1.41s | 1.41s |
| Gated, concurrency=1 (5 separate runs) | 1.22s | 1.24s | 1.27s | 1.27s |

Gate overhead is negligible (~0). Occasional outliers (8-17s, roughly 1 in
10-15 calls) appeared across *every* config tested, including the
unmodified raw path — consistent with shared-VM background contention
unrelated to this work.

## E. Resource usage

Swap sits at ~95-99% full **at rest**, chronically, unrelated to this work
and unchanged by it (this VM's baseline condition — see the separate
[Shared Fate infra audit]). Across every concurrency trial run for this
validation (six total: three at concurrency=5/10 each): load average never
exceeded 1.36, generally sat between 0.4 and 1.1. Compare to ~107 in the
original incident. `llama-server` RSS stayed 146-635MB (cap: 768MB).
Backend response time stayed 7-31ms throughout every trial, no exceptions.

## F. Concurrency behavior (2 trials each at 5 and 10, plus the original single trials)

| Callers | Trial | Success | Load before -> after | Backend latency |
|---|---|---|---|---|
| 1 | (5 runs) | 5/5 | n/a (single call each) | n/a |
| 2 | 1 | 2/2 | 0.89 -> 1.75 | 29ms |
| 5 | orig | 4/5 | 1.36 -> 1.41 | 29ms |
| 5 | 1 | 4/5 | 0.38 -> 0.51 | 31ms |
| 5 | 2 | 3/5 | 0.51 -> 0.71 | — |
| 10 | orig | 5/10 | 1.01 -> 1.09 | 14ms |
| 10 | 1 | 3/10 | 0.81 -> 0.99 | 12ms |
| 10 | 2 | 3/10 | 0.99 -> 1.07 | 18ms |

Every failure across every trial landed at 5.05-5.10s — precisely the
configured `LOCAL_LLM_QUEUE_TIMEOUT_SECONDS=5` boundary, no variance, no
hangs, no accumulation. **Directly verified from llama-server's own
`journalctl` log** (not inferred): every `launch_slot_` event for a new task
follows the previous task's `release` by single-digit milliseconds, never
overlapping — max concurrent inference is genuinely 1 at the source, not
just at the application layer.

**Real production load is 2 concurrent Celery workers** — that scenario
succeeded 100% (2/2) across its trial, with load average never exceeding
1.75 and backend latency unaffected. The 5/10-caller trials exist to prove
graceful degradation *beyond* real production load, which they do.

## G. Security

New key generated (`openssl rand -hex 32`), moved to
`/etc/torpedo-v2-llm.env` (mode 600, root:root) via `EnvironmentFile=`,
removed from `ExecStart` entirely. Confirmed: absent from `ps aux`, absent
from `journalctl -u torpedo-v2-llm` history, never committed to git. A
dedicated test (`test_api_key_never_appears_in_failure_exception`) proves
it can't leak through an exception message either. Old (exposed) key is
dead — rotated, no longer valid.

## H. Test suite

775 tests passing (762 pre-existing + 13 new in `test_local_llm_gate.py`),
run fresh on the VM after every change, twice. Zero regressions.

## Production recommendation: SAFE TO ENABLE

For the cheap role only, with the staged rollout below.
`LOCAL_LLM_MAX_CONCURRENCY` should stay at 1 unless future evidence (real
production monitoring data) justifies raising it — do not raise it
speculatively.

## Staged rollout (not yet executed)

1. Set `BEDROCK_MODEL_CHEAP=local:qwen2.5-0.5b-instruct`,
   `BEDROCK_FALLBACKS_CHEAP=` (empty), `SELF_HOSTED_BASE_URL`,
   `SELF_HOSTED_API_KEY` (new, rotated key) in `backend/.env`, restart
   `torpedo-backend`/`torpedo-sales-worker`/`torpedo-lead-gen-mcp`.
2. Monitor for a defined window: `journalctl -u torpedo-sales-worker | grep
   "LocalLLMUnavailable\|cheap classification call failed"` for real failure
   rate, `uptime`/`free -h` for load/swap, backend latency.
3. **Rollback trigger** (any one of): local-role failure rate climbing
   materially above what's expected from a single-slot server at real
   traffic volume; backend latency increasing beyond its normal baseline;
   load average persistently above ~3-4; swap free dropping toward 0 and
   staying there. Rollback = remove the four env vars, restart the same
   three services — proven fast and clean in the original incident.
4. No fallback exists in the chain by design (Bedrock excluded per
   instruction) — a local failure surfaces to the caller as "AI
   unavailable," which `bucket_classifier`/`mail_pool_ai` already handle as
   "leave unmarked, retry later," not a crash.
