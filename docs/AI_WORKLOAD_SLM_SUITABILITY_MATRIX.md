# Complete AI workload inventory & Qwen2.5-0.5B suitability matrix

**Scope: read-only audit + isolated benchmark calls only. No Bedrock, smart
role, credentials, or persisted production configuration changed as part of
this document. `cheap` role remains on Bedrock/DO in production
(`BEDROCK_MODEL_CHEAP`/`BEDROCK_FALLBACKS_CHEAP` unset).**

## The scoping finding that changes the whole question

Before any benchmark: **most AI operations in this codebase cannot be routed
to the local model today, regardless of any env var**, because they never
call `bedrock_client.py` at all. Two structurally separate systems exist:

- **`bedrock_client.py` path** (has `local:` support, the gate, everything
  built this session): `ai_gateway.py`'s task methods, `bucket_classifier`,
  `mail_pool_ai`, `icp_query_ai`, `ingestion`/`ingestion_vm`,
  `backfill_enrich`, `ai_email_agents`, parts of `ai_classifier.py`,
  `leads/email_classifier.py`, `routers/crm.py`'s draft endpoint,
  `outreach_pipeline.py`, `sales/tasks.py`. Roughly a dozen distinct call
  sites.
- **`claude_gateway.py` path** (a separate, independently-implemented
  client — no `local:` concept exists in it at all): `openai_wrapper.py`
  (shim), `query_generator.py`, `web_search_enrichment.py`,
  `email_sync/openai_email_classifier.py`,
  `email_sync/historical_classifier.py`, `crm_promote.py`,
  `segment_to_finance.py`, `gemini_enrichment.py`, `agents/base_agent.py`,
  `tasks/cint_survey_scoring.py`, both `outreach_tasks.py` files and all of
  `app/services/outreach/*`, `routers/prompt_management.py`'s test
  endpoint, the 4 original Anthropic-direct holdouts, and
  `ai_classifier.py`'s web-search-grounded method.

**"Make Qwen the default internal AI engine across Torpedo" is not
achievable by configuration today.** The `claude_gateway.py` half of the
codebase — which is the *larger* half by file count — has no path to the
local model at all without its own separate integration work (adding a
`local:`-equivalent to `claude_gateway.py`, or migrating those callers onto
`ai_gateway`/`bedrock_client`). That's real, scoped, additional work, not a
configuration decision, and it's not evaluated here.

The rest of this document covers only the `bedrock_client`-reachable half —
the actual candidates for today's gate/timeout architecture.

## Benchmark methodology note (a real mid-audit lesson)

Rapid back-to-back test calls with long timeouts against a `--parallel 1`
server left prior abandoned requests still computing server-side (client
timeout ≠ server cancellation — confirmed directly in `llama-server`'s own
log: a "cancel task" event is the *client* giving up, not the model
stopping). This measurably degraded even the previously-fast
`bucket_classifier` baseline (1.2s → 9-12s) partway through this session's
testing. The server was restarted before each clean measurement below, but
**this is itself a finding, not just a testing artifact**: real production
traffic legitimately mixes different prompt shapes back-to-back on this
same single-slot server, so the same degradation is a live risk, not
something that only happens under artificial rapid-fire testing.

## Suitability matrix

**GREEN** = tested, reliable. **YELLOW** = untested this session, prompt
shape suggests plausible but unverified. **RED** = tested and failed, or
prompt shape closely matches a tested failure.

| Operation | File | Category | Real prompt shape | Tested? | Result | Verdict |
|---|---|---|---|---|---|---|
| Lead bucket classification | `bucket_classifier.py` | 1 | Fixed short lead profile, 4-way output | Yes | 1.18-1.41s clean (isolated); degraded to 9-12s after mixed-load testing | **GREEN, with a caveat** — safe in isolation, degrades under realistic mixed traffic |
| Inbound email analysis | `mail_pool_ai.py` | 2 | Full email body + 15-field nested JSON | Yes | Failed at 12s (production, 100% of real calls); 21.5s one isolated run, >40s another | **RED** |
| ICP search query generation | `icp_query_ai.py` | 1 (creative generation) | Moderate prompt, asks for 15 diverse novel strings | Yes | Failed to complete in 45s | **RED** |
| Lead extraction from search results | `ingestion.py`/`ingestion_vm.py` | 1 | Batched search snippets (even a 3-item batch tested), 8-field-per-lead array output, `max_tokens=2048` | Yes | Failed to complete in 45s even with only 3 results | **RED** — has an existing regex fallback, so failure degrades gracefully today |
| Batch lead classification (Bedrock Batch API) | `backfill_enrich.py` | 1 | N/A — never reaches the gate | Code-read only | `model_for_role()` result passed directly to AWS as `modelId`; no `local:` handling | **RED** — would hard-fail against AWS, not a graceful local failure |
| Sender classification (batch up to 50) | `ai_gateway.classify_senders` (called from `sales/tasks.py`) | 1 (batch) | Up to 50 sender summaries in one call | No | — | **YELLOW→RED risk** — batch-shaped like the failed extraction case |
| BU routing | `ai_gateway.route_to_business_unit` (called from `outreach_pipeline.py`) | 2 | **Unbounded** — whole business-unit `.txt` files concatenated, no cap | No | — | **RED risk** — unbounded prompt length is worse than anything tested |
| Reply sentiment analysis | `ai_gateway.analyze_reply_sentiment` (called from `outreach_pipeline.py`) | 2 | Full reply body up to 3000 chars | No | — | **RED risk** — closely matches `mail_pool_ai`'s failed profile |
| Lead enrichment scoring | `ai_gateway.enrich_lead_data` (called from `sales/tasks.py`) | 1 | Scraped company text, 1-1.5KB capped, 8-field output | No | — | **YELLOW** — closer to the safe shape than the risky one |
| Email classify/summarize/extract | `ai_gateway.classify_email`/`summarize_email`/`extract_leads_from_email` | 1 | Body capped 2000-3000 chars, compact JSON out | No | — | **YELLOW** |
| Thread + contact extraction (Agent 1) | `ai_email_agents.py` | 2 | Full email thread, multiple messages, up to 500-word summary out | No | — | **RED risk** — long input + long output, same shape class as failures |
| Bulk lead categorization (Agent 2) | `ai_email_agents.py` | 2 | Up to 100 leads/call, dynamic category schema, `max_tokens=2000` | No | — | **RED risk** — same batch-size risk as extraction failure |
| Full lead classification (~20 fields) | `ai_classifier.py` `classify_lead` | 1/2 | Short input, but **~20-field flat output** | No | — | **YELLOW/RED** — output size alone may be the bottleneck, worth testing before trusting |
| Signature contact extraction | `ai_classifier.py` `extract_contact_from_signature` | 1 | Last 500 chars only, ~8-field output | No | — | **YELLOW, leaning GREEN** — smallest untested shape, closest to the one proven-safe case |
| Draft email for a CRM contact | `routers/crm.py` `draft_email_for_contact` | 3→5 (human-gated) | Short context, drafts subject+body | N/A | Already `role="smart"`, not cheap | **Confirmed NOT on local** |

## Forbidden-role re-confirmation

Every drafting/generation/customer-facing operation identified across both
research passes explicitly uses `role="smart"` where it's on the
`bedrock_client` path (`ai_gateway.generate_email_draft`,
`draft_outreach_email`, `outreach_pipeline.draft_outreach_email`,
`cold_outreach_router._generate_personalised_email`), or is entirely on the
separate `claude_gateway`/direct-client path where the concept of
`BEDROCK_MODEL_SMART`/`local:` doesn't even apply
(`gemini_enrichment.py`, `base_agent.py`, both `outreach_tasks.py` files and
`app/services/outreach/*`, `cint_survey_scoring.py`). **None of these can be
reached by a cheap-role local-model change, by construction.**

## A significant out-of-scope finding, flagged not investigated further

`backend/tasks/outreach_tasks.py`, `backend/app/tasks/outreach_tasks.py`,
and `app/services/outreach/*` implement a **second, entirely separate
outreach pipeline** from `cold_outreach_router.py` — hardcoding
`claude-opus-4-8` directly via `AsyncClaudeChatClient`, generating and in
several paths **sending customer-facing email with no kill-switch check, no
identity-swap validator, and (for `generate_initial_email`/
`generate_followup`) no human-review gate at all**, unlike the
`cold_outreach_router.py` path hardened earlier this session. This is
structurally irrelevant to local-SLM safety (it can never reach the local
model), but it's a real, separate finding worth your attention independent
of everything else in this document.

## Revised final verdict

**KEEP DISABLED for anything beyond the single proven-safe operation.**

The evidence does not support "Qwen as Torpedo's default internal AI
engine," even scoped to non-generative structured work. Of every real
workload actually load-tested this session with its real production prompt
shape, only the narrowest one (`bucket_classifier`'s 4-way fixed-vocabulary
classification) completed reliably — and even that degraded to 9-12s under
realistic mixed-traffic conditions, a genuine, unresolved risk for
production. Every other tested operation — including ones that looked
"structured" by the same reasoning that made `bucket_classifier` seem safe
— failed to complete within generous 40-45 second budgets. This confirms
the pattern you named directly: **generation complexity (batch size, list
diversity, output field count) predicts failure better than "is this
technically structured JSON."**

This is a hardware/model-capability ceiling, not a configuration problem.
Two honest paths forward, not mutually exclusive:

1. **Scope Qwen down to exactly what's proven** — `bucket_classifier` only,
   accept it as a narrow, real, but small win, and separately resolve the
   mixed-traffic degradation (likely needs its own investigation: does
   restarting `llama-server` between dissimilar prompt shapes help, or is a
   larger `--ctx-size`/different KV-cache eviction policy needed?) before
   even that narrow scope is trusted for sustained production use.
2. **This VM/model combination cannot support the broader vision.**
   Realizing "SLM as internal AI worker for all structured work" would need
   either a larger model, dedicated (non-shared, non-2-vCPU) hardware, or
   both — not tuning of what's already deployed here.

Recommend against further benchmarking passes on this hardware for this
model before deciding which of those two paths to take — the data already
collected is consistent and sufficient to make that call.
