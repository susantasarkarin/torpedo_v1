# Local SLM (Qwen2.5-0.5B) validation results — running record

**All numbers below are from real calls against the live `llama-server`
(127.0.0.1:8003, `--parallel 1`), never simulated.** This file is the
evidentiary backbone for `AI_ROUTING_MATRIX.md`'s routing decisions — every
"local SLM: REJECTED" or "local SLM: ACCEPTED" entry there points back to a
row here. Updated as each new workload is tested; entries are never removed,
only appended, so the pattern across tests stays visible.

## Summary of the pattern so far

| # | Workload | Shape | Result | Verdict |
|---|---|---|---|---|
| 1 | `bucket_classifier.py` (lead bucket) | short prompt, 4-way fixed vocab | 1.2–1.4s clean, degrades to 9–12s under mixed load | **ACCEPTED, with a load caveat** |
| 2 | `mail_pool_ai.py` (inbound email routing) | full body + 15-field nested JSON | 100% failure at 12s in production | **REJECTED** |
| 3 | `AIClassificationService.classify_email` | body≤2000 chars, 6-flat-field JSON | timeout at 12.01s | **REJECTED** |
| 4 | `icp_query_ai.py` (search query generation) | moderate prompt, 15 diverse strings out | failed to complete in 45s | **REJECTED** |
| 5 | `ingestion.py`/`ingestion_vm.py` (lead extraction) | batched snippets, 8-field array out | failed in 45s on a 3-item batch | **REJECTED** |
| 6 | Ad-hoc sales-lead binary classifier | minimal 2-field schema, keyword-free ambiguous email | schema-valid, WRONG answer (confidence 0.0, should have been high) | **REJECTED** |
| 7 | Bank-notification binary classifier (smoke test) | minimal 2-field schema, unambiguous email | correct, 10.27s | **ACCEPTED** (trivial/unambiguous case) |
| 8 | `reply_sentiment.py` replacement (sentiment+intent) | minimal schema (1 category + 1 extra field) | **2/8 sentiment (25%), 2/8 intent (25%)** — random-chance baseline | **REJECTED** |
| 9 | `reply_intent.py` replacement (intent only) | minimal schema (1 category, 0 extra fields) | **2/7 (29%)**, mode-collapsed onto "objection" | **REJECTED** |

**The pattern across all 9 tests: prompt/output size does not predict the
outcome. Category *distinctiveness* does.** #1 and #7 succeeded because their
categories are coarse and near-impossible to confuse (lead bucket A vs B vs
C vs D; obviously-a-bank-notice vs obviously-a-lead). Every failure — #2
through #6, #8, #9 — involves categories that require real semantic
judgment, even when the schema was minimal (#6, #8, #9 all used ≤2 output
fields and still failed). Decomposing a prompt into a smaller schema fixes
*format compliance*, which was rarely the actual failure mode anyway
(#6/#8/#9 all returned syntactically valid, schema-compliant JSON) — it does
not fix the model's ability to *tell similar things apart*.

## Test 8 — `reply_sentiment.py` replacement, full detail

**Design change applied before testing** (not a post-hoc fix): dropped the
free-text `explanation` field, since no caller (`update_lead_sentiment`,
`update_campaign_recipient_sentiment`) branches on its content — it's a log
string. Schema tested: `category` (sentiment, 4-way) + `extra_fields.intent`
(7-way) — already within `local_slm_client.classify()`'s proven-safe shape
cap.

| Reply (truncated) | Expected sentiment | Got | Expected intent | Got | Confidence |
|---|---|---|---|---|---|
| "Thanks for reaching out! I'd love to schedule a call..." | positive | negative | meeting_request | wrong_person | 0.9 |
| "Can you send me more information about your pricing..." | neutral | negative | more_info | wrong_person | 0.9 |
| "Not interested, please remove me from your list." | negative | negative ✓ | opt_out | wrong_person | 0.9 |
| "I think you have the wrong person. Contact John..." | neutral | negative | wrong_person | wrong_person ✓ | 0.9 |
| "This looks interesting. Tell me more about how it works." | positive | neutral | more_info | more_info ✓ | 0.8 |
| "Already have a similar solution in place..." | negative | negative ✓ | not_interested | wrong_person | 0.9 |
| "Unsubscribe" | unsubscribe | negative | opt_out | wrong_person | 0.9 |
| "Our budget is frozen until Q3..." | neutral | negative | more_info | wrong_person | 0.9 |

**Sentiment: 2/8 (25%). Intent: 2/8 (25%).** Note the model answered
`sentiment=negative` on 7 of 8 cases and `intent=wrong_person` on 6 of 8 —
this isn't random noise, it's collapse onto a default answer regardless of
input content. Confidence was 0.8–0.9 on every single case, correct or not —
**confidence carries no information here** and must never be used as an
accept/reject signal for this task.

## Test 9 — `reply_intent.py` replacement, full detail

**Design change applied before testing**: dropped `suggested_action`
entirely — it's a deterministic 1:1 lookup from `intent` in every one of the
file's own 7 few-shot examples (`meeting_request→schedule_call`,
`objection→address_objection`, etc.). Asking a probabilistic model to
reproduce an exact lookup table is pure waste and risk; the migration
proposal replaces it with a plain Python dict. Also dropped
`secondary_intent` and `key_phrases` — never read by any function in the
file.

| Reply (truncated) | Expected | Got | Confidence |
|---|---|---|---|
| "Thanks for reaching out! I'd love to schedule a call..." | meeting_request | meeting_request ✓ | 0.9 |
| "This looks interesting but the pricing seems high..." | objection | objection ✓ | 0.9 |
| "I'm not the right person for this. You should reach out to our CTO..." | referral | objection | 0.9 |
| "How does your solution integrate with our existing CRM..." | question | objection | 0.9 |
| "This could be useful but we're in the middle of Q4 closing..." | not_now | objection | 0.9 |
| "We're currently using HubSpot and it's working well..." | competitor_mention | not_now | 0.9 |
| "I'm no longer with the company. Please remove me..." | wrong_person | objection | 0.9 |

**2/7 (29%)**, with 4 of 7 answers landing on `objection` regardless of
content. Same mode-collapse pattern as Test 8, same flat 0.9 confidence
throughout.

## What this rules out for future testing

Given 6 of 9 tests failed, and every failure involves distinguishing between
semantically related categories (client vs vendor-shaped intent; positive vs
neutral sentiment; objection vs not_now vs competitor_mention), **any future
SLM candidate whose categories require similar fine-grained judgment should
be treated as presumptively RED without a fresh test proving otherwise** —
not because testing is banned, but because 6 independent negative results on
this exact failure shape is strong enough evidence that the burden is now on
a candidate to show its categories are meaningfully *coarser* than these,
the way `bucket_classifier`'s and the bank-notification test's were.

## Routing decision recorded

- `reply_sentiment.py`, `reply_intent.py`: **remain on their current direct-
  Anthropic (`claude-haiku-4-5`) transport.** Not migrated to local SLM.
  Per standing instruction, no Bedrock work is being done either — this is
  "leave as-is," not "move to Bedrock." If/when Bedrock access is restored,
  routing these through `claude_gateway.py`-equivalent governance (they
  currently bypass all AI daily-limit/governance checks entirely, a separate
  finding worth its own ticket) is the correct next step, not local SLM.
