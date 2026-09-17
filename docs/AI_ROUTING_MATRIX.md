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
| Lead bucket classification | `bucket_classifier.py` | #1 | **REJECTED as of 2026-09-17** — activated in production, mode-collapsed on real messy lead data (9/9 identical `SFW, confidence=0.90` regardless of actual content), confidence gate provided no protection. See `AI_VALIDATION_RESULTS.md` Test 10. Earlier "ACCEPTED" verdict was measured on clean synthetic leads only and did not generalize. | Reverted to Bedrock (currently failing there too — `model_errors`, but crucially writes nothing, which is the safer of the two known failure modes) |
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

## CRM/Sales agent framework — a major finding (cycle 2)

`app/services/ai_engine.py` is **not an LLM client** — it's a governance/
autonomy layer (observe/recommend/approve/autopilot modes, an approval-gated
action queue, audit logging) that 8 registered agents in `agents/*.py` route
their decisions through. This is real, already-built infrastructure much
closer to master-prompt section 35's "closed-loop intelligence system" than
anything needing to be built from scratch. All 8 were read this cycle:

| Agent | What it actually does | AI/LLM involved? | Verdict |
|---|---|---|---|
| `follow_up_agent.py` | Pure date-math: flags opportunities with no activity past a threshold | None — exact date calculation | **Correctly deterministic already** — matches section 13's own guidance verbatim |
| `opportunity_scoring_agent.py` | Pure point-based scoring (amount/stage/recency/linkage → 0–100 + next-best-action) | None | **Correctly deterministic already** |
| `panel_intelligence_agent.py` | Pure numeric fraud heuristic (reward/completion ratio thresholds) | None | **Correctly deterministic already** |
| `lead_research_agent.py` | Calls the Apollo REST API for factual enrichment (title/phone/company/LinkedIn) | None — factual lookup, not inference | Not an AI task; nothing to migrate |
| `old_mail_classifier.py` | Bridges *already-classified* output (from `email_crm_pipeline/email_classifier.py`, transport #4) into CRM records | Consumes upstream AI, does none itself | Nothing to migrate — the AI already happened elsewhere |
| `reply_monitor.py` | Drafts a suggested reply to inbound outreach replies — **explicitly templated with a documented "pluggable LLM hook... swap in an LLM draft later" comment in the code** | None yet — genuine, pre-built extension point | **Generation task, not classification** — same risk profile as cold-outreach drafting (identity/fact fabrication risk), explicitly out of local-SLM scope per this session's evidence and standing instruction. Human always reviews before send (approval-gated), so this is the *safest* place to eventually try a stronger model — but not the 0.5B local model. |
| `survey_revenue_agent.py` | Numeric revenue-per-entrant ranking | None (deterministic, same shape as opportunity scoring) | **Correctly deterministic already** |
| `seo_agent.py` | Stub — needs GA/Search Console API keys not yet configured | None | Not yet implemented, unrelated to AI routing |

**Conclusion**: this framework was already built following the master
prompt's own section 28 principle (deterministic where deterministic is
correct) before this loop ever started. There is essentially **no
unexploited local-SLM opportunity inside the CRM/sales agent layer** — the
one real gap (`reply_monitor`'s draft quality) is a generation task requiring
a stronger model, not a classification task suited to a 0.5B model.

## Cint / Panel / Vendor / Finance — confirmed zero AI involvement today

Checked directly (`app/services/cint_service.py`,
`cint_allocation_extension.py`, `survey_allocation_service.py`,
`traffic_service.py`, `activation_service.py`, `services/vendor_service.py`):
**none import or call any AI transport.** This is pure deterministic
API-integration and CRUD code today. Master-prompt sections 16/17/19's
"opportunities" here (vendor/RFQ matching, panelist ranking, Cint allocation
optimization) are **real gaps, but they are net-new feature work, not AI
migrations** — there is no existing call to route anywhere, no prompt to
test, no accuracy baseline to compare against.

This matters for scope discipline: building revenue-affecting Cint
allocation logic or panelist-ranking logic from scratch is a product-scoping
decision (data pipeline design, what "improvement" is measured against,
who approves a live allocation change) — not an "ordinary technical
alternative" a routing audit should decide unilaterally per section 33's own
risk/reversibility criteria. Recommending against speculatively building
these without dedicated scoping is the conservative, correct engineering
call here, not scope avoidance.

No dedicated finance-reconciliation module (payment↔invoice candidate
matching) exists in this repo at all — only a one-time migration
(`migrations/004_link_finance_invoices.py`) and an unrelated CRM-identity
`scripts/reconcile_account_links.py`. **No meeting-intelligence pipeline
exists anywhere in v1** (no transcript/notes ingestion of any kind) —
confirmed absent, not merely unaudited.

## Real-data audit, cycle 5 (2026-09-17) — Panel is the richest real dataset

Per the "start from what data actually exists to query" rule, checked real
collection sizes rather than just code references:

| Collection | DB | Real document count |
|---|---|---|
| `panelists` | `campaign_platform` | 224,004 |
| `panel_invitation_log` | `campaign_platform` | 3,469,649 |
| `panel_email_suppression` | `campaign_platform` | 29,416 |
| `vendor_leads` | `email_automation` | 1,272 |
| `vendors` | `email_automation` | 3 |
| `panel_vendors` | `email_automation` | 0 |

**Panel has by far the most real, usable history** among the collections
checked in that first pass — but a second pass found a database not
checked before (`cint_research`, missed because it doesn't contain the
literal word "panel"/"vendor"/etc.) with **equally rich, live-updating real
Cint data**:

| Collection | DB | Real document count |
|---|---|---|
| `cint_surveys` | `cint_research` | 157,023 |
| `cint_metrics` | `cint_research` | 7,625 |
| `cint_entry_links` | `cint_research` | 50 |

`cint_surveys` carries genuinely rich, directly-relevant real fields already:
`conversion`, `overall_completes`, `bid_incidence`, `mobile_conversion`,
`revenue_per_interview` (a real CPI-equivalent, with currency), `epc`
(revenue per click), `quota_remaining`/`total_remaining`,
`deactivation_reason`, `account_name` (the buyer/client), `source_api`
(traffic source, e.g. `fulcrum_offerwall`), `is_active`/`is_live`. Data is
live and current (`updated_at` timestamps within the hour at query time) —
this is an actively-integrated, actively-updated system, not a stale or
abandoned one. This maps closely onto the master prompt's own Cint section
(conversion rate, CPI, source performance, deactivation/anomaly analysis)
with real fields already in place for nearly all of it.

Vendors, by contrast, has almost no real data yet (3 records) — not enough
to build any meaningful matching/scoring on today; that capability would
need real vendor data collected first, which is itself the actual blocker,
not a missing AI feature.

**Next evidence-backed candidate for cycle 6**: a read-only, deterministic
aggregation over `cint_surveys` — e.g., conversion/deactivation-reason
breakdown by `account_name` or `source_api`, surfacing which
buyers/traffic-sources are underperforming or getting deactivated most
often. Pure aggregation, no AI/model needed for a first version, following
the same "deterministic first, safest possible starting point" pattern
already used for panel.

**A real, concrete bug found and fixed as a result**:
`agents/panel_intelligence_agent.py` (one of the 8 registered CRM agents,
audited in cycle 2 as "correctly deterministic") defaulted to
`source_db="panel"`, which is **empty** — confirmed via direct query. Run
exactly as its own module docstring's usage example shows
(`python -m backend.agents.panel_intelligence_agent --dry-run`), it would
scan zero panelists. Separately, its fraud heuristic checked for
`surveys_completed`-style fields that **do not exist anywhere in the real
`campaign_platform.panelists` schema** (confirmed via a 200-document field-
union query) — meaning even pointed at the right collection, it would have
flagged every panelist with any reward balance as suspicious, a false
positive on missing data rather than a real signal.

**Fixed**: default `source_db` corrected to `campaign_platform`; the
rewards-vs-completions check now only fires when completion data is actually
present in the document; the real field name (`rewards_balance`) is
recognized; a new, evidence-backed signal was added (reward balance sitting
on a `bounced`/`dnd` account — a real anomaly given what data actually
exists, not an invented policy). 12 new unit tests, all passing. This stays
in `recommend` autonomy mode (unchanged) — it creates a human-review task,
it does not autonomously act on any panelist record.

## Phase 1 status

`leads/local_slm_client.py` — built, unit-tested, live-smoke-tested,
committed (`7fd65b8`), deployed to `torpedo-prod`. The gateway/transport
layer itself works correctly (admission gate, JSON parsing, error handling
all behaved exactly as designed even during the incident below). Three
candidates evaluated: `reply_sentiment`/`reply_intent` rejected pre-
production (live validation only); `bucket_classifier` was activated in
production on 2026-09-17, found to mode-collapse on real data within
~30 minutes, and rolled back — see `AI_MIGRATION_STATUS.md` for the full
incident record. **As of this writing, no workload is running on
`local_slm_client` in production.** The bottleneck across every candidate
tested is the model's semantic discrimination ability, not the plumbing —
the plumbing has now been proven correct under a real failure, including
correctly catching and reporting the timeout cases inline rather than
hanging or corrupting data.
