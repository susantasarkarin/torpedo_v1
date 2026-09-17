# Torpedo v1 — AI Routing Matrix

Master workload inventory and routing decisions. Every row is grounded in
either a direct code read (file:function cited) or a live test (see
`AI_VALIDATION_RESULTS.md`). Routing categories: **DETERMINISTIC** / **LOCAL
SLM** / **BEDROCK** (currently unavailable — payment issue; entries here are
the technically-correct long-term route, not something implemented now) /
**HYBRID** / **UNREACHABLE-BY-DESIGN** (needs its own integration work before
a routing choice is even possible).

**Standing constraint, in force for every row below**: no Bedrock code,
credentials, config, or role chain is modified, tested, or depended upon.
Rows marked BEDROCK document the correct destination for when it's restored;
none are implemented.

## Transport inventory (how AI actually reaches Torpedo v1 today)

| # | Transport | Local-SLM-reachable? | Callers |
|---|---|---|---|
| 1 | `leads/bedrock_client.py` (boto3 Converse) | **Yes** — has the `local:` prefix seam | `bucket_classifier`, `mail_pool_ai`, `icp_query_ai`, `ingestion(_vm)`, `backfill_enrich`, `ai_gateway.py` (→ `AIClassificationService`) |
| 2 | `ai_governance/claude_gateway.py` | No | `openai_wrapper`, `query_generator`, `web_search_enrichment`, `openai_email_classifier`, `historical_classifier`, `crm_promote`, `segment_to_finance`, `gemini_enrichment`(partial), `base_agent`, `cint_survey_scoring`, both `outreach_tasks.py`, `app/services/outreach/*`, `prompt_management` test endpoint |
| 3 | `ai_governance/openai_gateway.py` (actually Claude-backed) | No — depends on Claude's built-in web-search tool | `web_search`, `discover_leads_external`, `enrich_company_web` |
| 4 | Raw `import anthropic` (no shared gateway) | No | `email_crm_pipeline/email_classifier.py` (Batch API, `claude-opus-4-7`), `email_classification/reply_sentiment.py`, `email_classification/reply_intent.py` (both `claude-haiku-4-5`, both bypass all AI-governance daily-limit checks — separate finding, not actioned here) |
| 5 | `google.generativeai` SDK directly | No | `leads/gemini_rotator.py`, `gemini_enrichment.py` |
| — | Hardcoded boto3 Bedrock, duplicated transport | No — deliberately bypasses #1 | `lead_gen_mcp/qwen_client.py` |
| **new** | **`leads/local_slm_client.py`** (this migration's own gateway) | **Native — local-only, no role chain** | none yet (Phase 1 built, nothing wired in) |

## Workload routing table

| Workload | File | Current transport | Local SLM verdict | Route |
|---|---|---|---|---|
| Lead bucket classification | `bucket_classifier.py` | #1 | **ACCEPTED** (1.2–1.4s clean; 9–12s under mixed load — caveat, not a rejection) | LOCAL SLM (already in place) |
| Inbound email → CRM routing | `mail_pool_ai.py` | #1 | REJECTED — 100% timeout at 12s | BEDROCK (currently: unavailable; stays on whatever's configured, no change made) |
| Mail Stage-1 prefilter | `mail_segregation_agent.py` | none (zero-AI by design) | N/A — deterministic by design, correctly so | DETERMINISTIC (no change — this is the right answer, not a gap) |
| Gmail-app email classify/extract | `app/services/ai_classification_service.py` → `ai_gateway.py` | #1 | REJECTED — timeout at 12.01s (real prod prompt) | BEDROCK (blocked on account status) |
| ICP search query generation | `icp_query_ai.py` | #1 | REJECTED — failed in 45s | BEDROCK (blocked) |
| Lead extraction from search results | `ingestion(_vm).py` | #1 | REJECTED — failed in 45s, batch of 3 | BEDROCK (blocked); has a working regex fallback already — degrades gracefully today |
| Batch lead classification | `backfill_enrich.py` | #1 (Bedrock Batch API) | Not tested — no `local:` handling in code at all | BEDROCK (blocked); needs its own `local:` support before SLM is even an option |
| Reply sentiment + intent | `email_classification/reply_sentiment.py`, `reply_intent.py` | #4 | **REJECTED** — 25–29% accuracy, near/at random-chance baseline, mode-collapse onto one default answer, confidence uninformative (flat 0.9 regardless of correctness) | Remain on current direct-Anthropic transport (governance-bypass gap flagged separately, not fixed here) |
| Historical bulk email classification (90K+ backlog) | `email_sync/historical_classifier.py` | #2 | Not testable — no local route exists | UNREACHABLE-BY-DESIGN; would need a `local:`-equivalent built into `claude_gateway.py`, or migration onto transport #1 |
| Batch email → CRM extraction | `email_crm_pipeline/email_classifier.py` | #4 (Anthropic Batch API) | Not testable | UNREACHABLE-BY-DESIGN; Batch API shape doesn't map onto a single-slot synchronous local server at all |
| Web-search lead discovery / company enrichment | `openai_gateway.py`, `web_search_enrichment.py` | #3 | Not applicable | UNREACHABLE-BY-DESIGN; needs live web search, which the local model cannot do regardless of prompt design |
| Gemini-based enrichment | `gemini_enrichment.py`, `gemini_rotator.py` | #5 | Not tested | UNREACHABLE-BY-DESIGN; separate SDK, separate quota system |
| Lead-gen MCP classification/scoring | `lead_gen_mcp/qwen_client.py` | hardcoded Bedrock | Not tested | UNREACHABLE-BY-DESIGN; hardcoded transport, no `local:` branch, separate venv |
| Sender classification (batch ≤50) | `ai_gateway.classify_senders` (via `sales/tasks.py`) | #1 | Untested; batch shape matches failed `ingestion.py` profile | Presumed BEDROCK-class until proven otherwise (see "what this rules out," `AI_VALIDATION_RESULTS.md`) |
| BU routing | `ai_gateway.route_to_business_unit` (via `outreach_pipeline.py`) | #1 | Untested; unbounded prompt length | BEDROCK-class — worse than anything tested, not a candidate |
| Cold email drafting (all paths) | `outreach_mailer.py`, `cold_outreach_router.py`, `outreach_pipeline.py`, second outreach pipeline | #1 / #2 | Out of scope | Explicitly excluded — `role="smart"`/drafting, per standing instruction regardless of local-model question |

## Business-decision surfaces with NO current AI involvement (deterministic today)

Per master-prompt section 4/34, these are real decision points, currently
rule-based/manual, not yet audited for an SLM opportunity. Listed for the
next loop iteration, not yet classified — classifying without reading the
actual implementation would be exactly the "assume a function exists"
mistake the master prompt warns against:

- Lead-to-account / lead-to-contact matching (dedup)
- Opportunity stage progression, deal-risk flags
- Vendor/RFQ matching, supplier performance scoring
- Panel/panelist matching and allocation
- Cint allocation and conversion analysis
- Finance reconciliation (payment↔invoice candidate matching)
- Meeting intelligence (no evidence a transcript/notes pipeline exists in v1 at all — needs verification before assuming there's anything to route)

None of these have been read in the actual repository yet this loop
iteration — they are not claimed to exist in any particular form, per
section 4's explicit warning against inventing implementation paths.

## Phase 1 status

`leads/local_slm_client.py` — built, unit-tested (16/16), live-smoke-tested,
committed (`7fd65b8`), deployed to `torpedo-prod`. Zero callers wired in yet;
two candidates evaluated and **rejected** (see above). Structurally, this
proves the gateway itself works — the bottleneck found so far is the model's
semantic discrimination ability on nuanced categories, not the plumbing.
