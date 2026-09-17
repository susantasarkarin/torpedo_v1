# Torpedo v1 — Local SLM Migration Status

Current state of every local-SLM migration attempt, in status terms only:
IMPLEMENTED / TESTED / VALIDATED / PARTIALLY VALIDATED / FAILED / BLOCKED /
DEFERRED / ROLLED BACK. Nothing here is claimed as "works" without the
evidence behind it — see `AI_VALIDATION_RESULTS.md` for the underlying data.

## Current production state (as of 2026-09-17, ~08:15 UTC)

**No workload is running on the local SLM in production.** Both scheduled
cheap-role tasks (`mail-pool-ai-sender-batch`, `lead-bucket-classification`)
are back to their pre-session state: failing against unavailable Bedrock,
producing `aborted_systemic`/`model_errors`, writing nothing. This is a
known, safe, non-corrupting failure mode — chosen deliberately over the
alternative below.

## Incident record: bucket_classifier local-SLM activation and rollback

| | |
|---|---|
| **Status** | ROLLED BACK |
| **Activated** | 2026-09-17 07:51 UTC (`BUCKET_CLASSIFIER_USE_LOCAL_SLM=true`, worker restarted) |
| **Rolled back** | 2026-09-17 08:1x UTC (~25 min later, first real production batch) |
| **Root cause** | Model mode-collapse on real messy lead data — see `AI_VALIDATION_RESULTS.md` Test 10 |
| **Data impact** | 9 leads written with incorrect `outreach_bucket=SFW`/`classification_basket=A` in `leads_raw` and mirrored `leads_enriched` |
| **Downstream impact** | None confirmed — checked `campaign_recipients` for all 9 leads, no enrollment had occurred yet |
| **Corrective action** | All 9 leads' bad fields reverted (`$unset` in both collections) within minutes of being written; flag disabled; worker restarted; confirmed reverted to Bedrock-failing (safe) state |
| **Verification of rollback** | Confirmed `BUCKET_CLASSIFIER_USE_LOCAL_SLM=false` in production `.env`, worker active, all 9 leads show `bucket=None basket=None` post-revert |

### Standing rule adopted from this incident

**No local SLM workload may be promoted to production merely because
synthetic tests pass. Production acceptance requires representative
real-data validation, and for any workload capable of changing CRM/business
state, an independent correctness/sanity check must exist outside the
model's own self-reported confidence.** This is now a permanent gate on
every future local-SLM activation, not just guidance — `bucket_classifier`
does not get re-activated on a re-read of its old synthetic-lead numbers;
it needs a fresh real-data validation pass, same as any new candidate.

### What this changes going forward

1. **A clean-synthetic-lead benchmark does not predict real-production-data
   behavior for this model.** Every future local-SLM validation must include
   real, messy production samples (garbled fields, missing data) before an
   "ACCEPTED" verdict is trusted — not just prototypical hand-written test
   cases.
2. **Confidence from this model is not a usable safety gate.** The 0.7
   threshold that was supposed to catch uncertain answers did not catch this
   failure because the model reported 0.90 confidence on every wrong answer.
   Any future re-attempt needs an independent correctness signal (e.g.
   deterministic sanity checks against the lead's own fields, or requiring
   agreement across repeated calls) rather than trusting the model's own
   self-reported confidence.
3. **The plumbing is proven correct under a real failure.** `local_slm_client.py`,
   the admission gate, and the error-handling path all behaved exactly as
   designed — timeouts were caught and routed to `REVIEW` as intended, no
   hang, no crash, no silent data corruption from the *infrastructure* side.
   The failure was entirely in model output quality, which is exactly the
   layer `local_slm_client.classify()`'s design docs already flagged as
   unproven for anything beyond the narrowest categories.
4. **No further local-SLM production activation should happen without a
   real-data validation pass first.** This applies retroactively to
   `bucket_classifier` too — its next attempt (if any) needs the same
   real-sample validation this incident just showed was missing, not a
   re-read of the old synthetic-lead numbers.

## Other candidates evaluated

| Candidate | Status | Note |
|---|---|---|
| `reply_sentiment.py` / `reply_intent.py` | FAILED (pre-production) | 25–29% accuracy in live testing; never activated in production; confirmed dead code (no live caller) independent of the accuracy finding |
| `AIClassificationService.classify_email` | FAILED (pre-production) | Timeout at 12.01s on the real production prompt; never activated |
| `bucket_classifier.py` | ROLLED BACK (production) | See incident record above |

## Structural gaps (integration work, not model-quality findings)

| Gap | Status |
|---|---|
| `email_sync/historical_classifier.py` → `claude_gateway.py` | DEFERRED — no local-model route exists; would need its own integration, not evaluated here |
| `email_crm_pipeline/email_classifier.py` → raw Anthropic Batch API | DEFERRED — no shared gateway, Batch API shape doesn't map onto a synchronous single-slot server |
| `lead_gen_mcp/qwen_client.py` → hardcoded boto3/Bedrock | DEFERRED — no `local:` mechanism, separate venv |
| Gemini paths (`gemini_enrichment.py`, `gemini_rotator.py`) | DEFERRED — separate SDK entirely |

## Bedrock-dependent workloads (blocked on account status, not implemented)

Per standing instruction, none of these are touched, tested, or repaired.
Listed for completeness only:

- `mail-pool-ai-sender-batch` (currently failing, writes nothing — safe)
- `lead-bucket-classification` (currently failing, writes nothing — safe, and now the *known-safer* of its two tested failure modes)
- Everything else classified BEDROCK in `AI_ROUTING_MATRIX.md`
