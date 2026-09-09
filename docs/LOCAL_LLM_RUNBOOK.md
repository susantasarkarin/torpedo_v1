# Local LLM Runbook

Real, locally-running open-weight inference for Torpedo v2's AI gateway — no
Anthropic, OpenAI, AWS Bedrock, or RunPod required for normal operation. This
replaces the previous state (`app.ai.gpu_broker`/`GpuBrokerLLMProvider`, a
RunPod-only path) as the *preferred* backend; the RunPod path is unchanged and
still exists as a fallback (see "Provider selection" below).

## Why this exists

The VM this runs on (`139.59.32.72`, `torpedo-prod`) hosts v1's live production
service, MongoDB, Celery workers, and SFW panel — v2's AI gateway had real,
tested decision code (`app.ai.decision_engine`) but nothing to actually call.
`RUNPOD_API_KEY` was never set (v1 never used RunPod), and v1's own AWS
Bedrock credential lacks Bedrock IAM permission. This runbook closes that gap
with a real, downloaded, locally-running model — deliberately small, because
the host has **2 vCPUs and 3.8GB RAM, with swap already fully exhausted** at
the time this was built. See "Hardware constraint" below before ever
considering a larger model on this box.

## Exact model

| | |
|---|---|
| Model | Qwen2.5-0.5B-Instruct |
| Format / quantization | GGUF, Q4_K_M |
| Source | `Qwen/Qwen2.5-0.5B-Instruct-GGUF` on Hugging Face |
| File | `qwen2.5-0.5b-instruct-q4_k_m.gguf` |
| Disk size | ~491MB |
| Observed RSS after a real inference call | ~480MB (mmap-based — idle RSS is much lower, ~100-270MB) |

**Why this size, not bigger**: the user's own priority order was reliability →
structured-output fidelity → speed → resource efficiency → quality, but the
binding constraint discovered on inspection was the VM's memory, not a
preference — 122MB free RAM and 0MB free swap at the time of setup, shared
with v1's production service. A 1.5B+ model would have meaningfully better
instruction-following, at roughly 2-3x the memory footprint; that tradeoff
was rejected here specifically because of this VM's headroom, not in general.
If a dedicated inference host or a VM with more RAM ever becomes available,
revisiting the model size is a real, worthwhile option — see "Known
limitation" below for the concrete quality cost of staying this small.

**llama.cpp's grammar-constrained `json_object` mode matters more than model
size for *syntactic* JSON validity** — the runtime rejects the possibility of
truncated/malformed JSON syntax by construction, regardless of model size.
What model size affects is *semantic* correctness within that valid JSON
(picking the right field values) — see "Known limitation."

## Inference runtime

**llama.cpp**, prebuilt CPU-only Ubuntu x64 binary, build `b10868`
(`llama-b10868-bin-ubuntu-x64.tar.gz` from
`github.com/ggml-org/llama.cpp/releases`). CPU-only because the VM has no
compute-capable GPU (only a `virtio` virtual display adapter). AVX2+FMA
confirmed present on the host CPU (`DO-Premium-AMD`), which this build uses.

Not compiled from source: with ~120MB free RAM at setup time, a parallel
`make`/`cmake` build was judged too risky to run on this box — a prebuilt
release binary avoided that entirely.

## Where it runs

- Binary + libraries: `/opt/torpedo-v2-llm/runtime/llama-b10868/`
- Model file: `/opt/torpedo-v2-llm/models/qwen2.5-0.5b-instruct-q4_k_m.gguf`
- Runs as systemd unit **`torpedo-v2-llm.service`**, under a **dedicated
  unprivileged system user** (`torpedo-llm`, `nologin` shell) — created
  specifically for this service; v1's and v2's own existing services still
  run as `root` and were left exactly as they were (never touch v1).
- Listens on **`127.0.0.1:8003`** only — never bound to a public interface.
  A separate bearer API key gates it (`LOCAL_LLM_API_KEY` in
  `backend_v2/.env`, never committed, never logged, never printed in any
  script output).

### Hardware constraint — read before changing anything here

At setup time: 2 vCPUs, 3.8GB total RAM, **122MB free**, **swap 100%
exhausted** (2.0GB/2.0GB used), load average 1.3-1.5. This is a genuinely
resource-constrained shared production box, not a dedicated inference host.
Every choice below exists because of that:

- **`MemoryHigh=600M` / `MemoryMax=768M` / `MemorySwapMax=0`** on the systemd
  unit — a hard cgroup ceiling. If the process ever tries to exceed 768MB,
  the cgroup kills *that process specifically*, not an arbitrary victim the
  kernel's OOM killer might otherwise pick on this box (which could easily be
  MongoDB or v1's own backend). This is the single most important line in
  the unit file — do not remove it without a real reason and a fresh memory
  check.
- **`--ctx-size 2048 --threads 2 --parallel 1`** — a small context window (bounds
  KV-cache growth), thread count matched to the 2 real vCPUs, and exactly one
  concurrent inference slot (serializes requests rather than letting several
  land at once and multiply memory/CPU pressure).
- Before making this bigger (bigger model, bigger context, more parallelism,
  raising the memory cap), re-run the same hardware inspection this runbook
  started from: `free -h`, `swapon --show`, `nproc`, and check what v1 is
  currently using (`ps aux --sort=-%mem | head`). Don't just raise the
  numbers because the current setup feels small.

## How the model is downloaded (reproducible)

```bash
mkdir -p /opt/torpedo-v2-llm/runtime /opt/torpedo-v2-llm/models
cd /opt/torpedo-v2-llm/runtime
curl -sL -o llama.tar.gz \
  https://github.com/ggml-org/llama.cpp/releases/download/b10868/llama-b10868-bin-ubuntu-x64.tar.gz
tar xzf llama.tar.gz

cd /opt/torpedo-v2-llm/models
curl -sL -o qwen2.5-0.5b-instruct-q4_k_m.gguf \
  'https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf'
```

Check `github.com/ggml-org/llama.cpp/releases` for the current numbered build
tag before reusing this — `b10868` was current as of this runbook's writing;
llama.cpp cuts new numbered builds frequently.

## How it's started / restarted after reboot or deployment

```bash
systemctl status torpedo-v2-llm.service    # is it running
systemctl restart torpedo-v2-llm.service   # restart (e.g. after a config change)
journalctl -u torpedo-v2-llm.service -n 50 --no-pager   # recent logs
```

`systemctl enable torpedo-v2-llm.service` was already run — it starts
automatically on boot, same as `torpedo-backend-v2.service`. No manual step
is needed after a VM reboot.

The unit file lives at `/etc/systemd/system/torpedo-v2-llm.service` (not
version-controlled in this repo — infrastructure config, not application
code, same as `torpedo-backend-v2.service`'s own unit file).

## How Torpedo connects to it

`backend_v2/.env` on the VM carries three new keys (values never printed —
key names only, per this project's standing discipline):

```
LOCAL_LLM_BASE_URL=http://127.0.0.1:8003/v1
LOCAL_LLM_API_KEY=<random, generated at setup — rotate via the same openssl command if ever needed>
LOCAL_LLM_MODEL_NAME=qwen2.5-0.5b-instruct
```

`app.config.Settings` reads these (`local_llm_base_url` /
`local_llm_api_key` / `local_llm_model_name`).
`app.ai.llm.get_llm_provider(db)` is the one factory every router now calls
(replacing 7 separate `GpuBrokerLLMProvider(GpuBroker(...))` construction
sites across `emailai`/`finance`/`leadgen`/`panel` routers): it returns
`LocalLlamaCppProvider` when `local_llm_base_url` is set, and falls back to
the unchanged `GpuBrokerLLMProvider`/RunPod path otherwise. Nothing about the
RunPod path was deleted — this only takes priority over it.

## Provider selection

```
Settings.local_llm_base_url set?
  ├── yes → LocalLlamaCppProvider (this runbook's model, always-on, no lease)
  └── no  → GpuBrokerLLMProvider  (RunPod, on-demand lease — unchanged, still real)
```

Both implement the same `app.ai.llm.LLMProvider` Protocol
(`chat(messages, response_format) -> LLMResponse`, raising `LLMUnavailable`
on failure) — every caller (`DecisionEngine`, the four router modules above)
is unaware of which one is actually answering.

## Health check

`GET /api/v1/ai/health` (permission-gated behind `AI_READ`, same as every
other route — deliberately *not* a public unauthenticated endpoint, since it
triggers a real inference call with a real cost; see the security-audit note
below). Performs one genuine, minimal-token chat call against whichever
provider `get_llm_provider()` currently selects and reports:

```json
{"status": "healthy", "provider": "local_llama_cpp", "model": "qwen2.5-0.5b-instruct", "latency_ms": 1234.5, "sample_response": "OK"}
```

or, when the backend can't be reached:

```json
{"status": "unavailable", "provider": "local_llama_cpp", "model": "qwen2.5-0.5b-instruct", "latency_ms": 12.3, "error": "local model call failed: ..."}
```

Always HTTP 200 — the endpoint's own job (checking) succeeded; the AI
backend's health is the `status` field, not the HTTP status code. This
distinguishes "the health-check route crashed" from "the model it's checking
is down," which are different failures needing different responses.

**Security note**: this endpoint is intentionally *not* public/unauthenticated,
unlike the bare `/health` liveness check. A real inference call costs real
CPU time on a 2-vCPU box; an unauthenticated version would be a free way for
anyone to tie up the model's one serialized inference slot.

## Known limitation — structured-output reliability at this size

Live-tested against the real model (not mocked): the model reliably produces
*syntactically* valid JSON (grammar-constrained decoding guarantees this
regardless of model size), but at 0.5B parameters it does not always fill
every field with the exact semantic type `Decision` expects — observed once
in manual testing, `follow_up_at` (expected: ISO-8601 datetime or JSON
`null`) came back as a prose sentence instead. `DecisionEngine.decide()`
already handles this correctly and safely: `Decision.model_validate()` raises
`ValidationError`, which becomes `DecisionEngineError` — a real, surfaced
failure, never silently accepted or papered over (the same I-4 discipline
this codebase applies everywhere else). This is an honest characteristic of
running a genuinely small model on a memory-constrained box, not a bug to
suppress with a fallback default.

## Local development (no VM, no model)

Every existing unit test (`GpuBrokerLLMProvider`, `LocalLlamaCppProvider`,
`DecisionEngine`, and every domain service that calls it) is tested against a
fake transport / fake provider — no network call, no model download needed to
run `pytest` locally or in CI. `local_llm_base_url` is unset by default
(`Settings`), so `get_llm_provider()` falls back to the RunPod path
automatically in any environment without these three env vars — nothing
breaks by omission.
