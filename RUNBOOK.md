# Lead Pipeline Runbook (AWS Bedrock, ap-south-1)

Order of operations: **enable models → set env → backfill → classify → preview → send.**

All commands run from the repo root with `PYTHONPATH=backend`:

```bash
export PYTHONPATH=backend          # PowerShell: $env:PYTHONPATH='backend'
```

---

## 0. Enable Bedrock model access (one-time)

1. AWS console → **Bedrock** → region **ap-south-1 (Mumbai)** → **Model access → Manage model access**.
2. Enable **Qwen3-32B** and **DeepSeek-V3.x**, submit, wait for "Access granted".
3. Verify the exact model ID strings and access:

```bash
python -c "import sys; sys.path.insert(0,'backend'); \
from leads.bedrock_client import validate_model_access; print(validate_model_access())"
```

This calls `list_foundation_models` and **fails fast** with the missing model
named and the IDs actually visible in the region. Every pipeline entry point
that talks to Bedrock should pass this before doing anything else. If the
default IDs (`qwen.qwen3-32b-v1:0`, `deepseek.v3-v1:0`) don't match what the
console shows, correct the env vars below — do not edit code.

## 1. Environment

| Variable | Default | Notes |
|---|---|---|
| `AWS_REGION` | `ap-south-1` | Mumbai |
| `BEDROCK_MODEL_CHEAP` | `qwen.qwen3-32b-v1:0` | queries, extraction, enrichment, first-pass classification |
| `BEDROCK_MODEL_SMART` | `deepseek.v3-v1:0` | emails, borderline-lead escalation (non-thinking mode, always) |
| `BEDROCK_MAX_RETRIES` | `3` | throttling backoff attempts |
| `MONGO_URI` | `mongodb://localhost:27017/` | |
| `GOOGLE_API_KEY`, `GOOGLE_CSE_ID` | — | Google CSE; 100 free queries/day |

Batch mode only:

| Variable | Notes |
|---|---|
| `BEDROCK_BATCH_S3_BUCKET` | bucket for job input/output JSONL |
| `BEDROCK_BATCH_ROLE_ARN` | IAM role Bedrock assumes (S3 read/write on that bucket) |

Sending only:

| Variable | Notes |
|---|---|
| `OUTREACH_SENDER_EMAIL` / `OUTREACH_SENDER_NAME` | verified SES identity |
| `OUTREACH_SENDER_POSTAL_ADDRESS` | **legally required** (CAN-SPAM); send refuses without it |
| `OUTREACH_UNSUBSCRIBE_URL` | must resolve to the unsubscribe route below |
| `OUTREACH_TRANSPORT` | `ses` (default) or `smtp` (+ `SMTP_HOST/PORT/USER/PASSWORD`) |

Tunables: `BUCKET_CONFIDENCE_THRESHOLD` (0.7), `BUCKET_CLASSIFY_DAILY_CAP` (500),
`OUTREACH_MIN_ICP_SCORE` (4), `OUTREACH_SEND_DAILY_CAP` (200), `OUTREACH_SEND_HOURLY_CAP` (25).

Credentials come from the standard AWS chain (env / profile / instance role) —
never from code or config files.

**Blocking prerequisite:** write the service pitch copy in
`backend/leads/outreach_config.py` → `BUCKETS[*]["pitch"]`. All three are
placeholders; Stage 4 refuses to send until they are real. Also sanity-check
each bucket's `description`/`ideal_buyer` — they were derived from the ICP
configs, not authored.

---

## 2. Backfill and enrich

```bash
python -m leads.backfill_enrich --dry-run --limit 100   # always first
python -m leads.backfill_enrich --no-enrich             # free: name-split + re-score only
python -m leads.backfill_enrich                         # on-demand (default)
python -m leads.backfill_enrich --batch                 # Bedrock batch inference, 50% cheaper
```

- Resumable via `backend/leads/.backfill_checkpoint.json`; `--reset` starts over.
- `--dry-run --batch` writes the JSONL to `.backfill_batch_preview.jsonl` and
  submits nothing — **inspect this and run a tiny live job (`--batch --limit 2`)
  before a big one**: the native batch request body for Qwen is unverified
  against the live service.
- Google CSE budget: 100 free queries/day ≈ 68 days for ~6,800 leads. Batch
  mode halves the *Bedrock* cost, not the CSE cost — the search is the
  bottleneck either way. A 429 pauses CSE for 24h automatically.

## 3. Classify into buckets

```bash
python -m leads.bucket_classifier --dry-run --limit 50
python -m leads.bucket_classifier
```

Flow per lead: keyword exclusion (free) → Qwen first pass → if confidence < 0.7,
one DeepSeek escalation → still < 0.7 goes to REVIEW, not a bucket. Confident
REJECTs never pay for DeepSeek. Capped at `BUCKET_CLASSIFY_DAILY_CAP`/run.

```javascript
// what needs human eyes
db.leads_raw.find({outreach_bucket: "REVIEW"},
                  {title: 1, outreach_bucket_reason: 1}).limit(20)
```

## 4. Preview, then send

```bash
python -m leads.outreach_mailer                      # DEFAULT = dry run
python -m leads.outreach_mailer --bucket BIM --limit 10
# read outreach/preview/<BUCKET>/*.txt, then:
python -m leads.outreach_mailer --send
```

Emails are written by DeepSeek (`role="smart"`) and validated (length, CTA,
correct name, no placeholders, no invented claims about the recipient's
company; max 2 regenerations). Sending refuses if pitch copy, postal address,
sender email, or unsubscribe URL is missing. Caps, randomized 45–180s spacing,
plain-text part, `List-Unsubscribe` headers, full send log in
`outreach_send_logs` (bodies never logged).

### Bounce / unsubscribe automation (SES)

1. SES → configuration set on the sending identity → event destination → SNS
   topic (Bounce + Complaint events).
2. Subscribe the topic (HTTPS) to `POST /outreach/ses-notifications` — mount
   the router:

```python
from leads.ses_notifications import build_router
app.include_router(build_router())
```

   The route auto-confirms the SNS subscription handshake.
3. Point `OUTREACH_UNSUBSCRIBE_URL` at `GET /outreach/unsubscribe`.

Permanent bounces and complaints are suppressed automatically; transient
bounces (mailbox full) are deliberately **not** — those leads stay live.

---

## 5. Mail Pool AI (Bedrock mail-desk)

The Gmail mail pool (`torpedo_gmail.email_metadata`) is processed by a
two-stage pipeline. **Stage 1** is the free rule classifier
(`agents/mail_segregation_agent.py`); **Stage 2** is the Bedrock mail-desk
(`sales/mail_pool_ai.py`) — but only for mail worth paying for.

**Roles:** per-email/sender analysis runs on `role="cheap"` (Qwen); follow-up
reply drafts and RFQ line-item parsing run on `role="smart"` (DeepSeek).

### Env

| Variable | Default | Purpose |
|---|---|---|
| `MAIL_AI_PREFILTER_ENABLED` | `true` | Stage-1 rule prefilter on/off |
| `MAIL_AI_PREFILTER_MIN_CONFIDENCE` | `0.5` | min rule confidence to skip noise |
| `MAIL_AI_MAX_PER_RUN` | `200` | per-beat cap on emails processed |
| `MAIL_AI_PREFILTER_AUDIT_SAMPLE` | `20` | nightly re-check sample size |
| `MAIL_AI_ANALYSIS_ROLE` | `cheap` | role for analysis calls |
| `MAIL_AI_WRITER_ROLE` | `smart` | role for drafts + RFQ items |

Uses the same `BEDROCK_*` / `AWS_REGION` model access as §0–1. No extra AWS
setup beyond enabling the two models in ap-south-1.

### Cost control (the prefilter)

Rules run first. Only segments `Internal / Client / Vendor / GST-IT-Govt /
Others` reach Bedrock. `Bank / Promotion / Transactional` at confidence ≥ 0.5
are marked `ai_analysis = {skipped: true, reason: "rule_prefilter"}` and never
cost a model call. The nightly `audit_prefiltered_mail` task re-checks 20
random skipped emails with the cheap model and records any disagreements to
`email_automation.mail_ai_prefilter_audit` — watch this for the rule filter
silently eating real client mail.

### Segment source of truth + backfill

After Stage 2 the AI `category` maps onto the `segment` field the MailPool UI
reads (`rfq/client_inquiry/reply → Client`, `vendor → Vendor`, etc.);
`Internal/Bank/Govt` stay rule-decided. Both opinions are kept
(`rule_classification`, `segment`, `segment_source`). To re-derive segments for
already-processed mail **without new model calls**:

```bash
python -m sales.backfill_mail_segments --dry-run     # inspect, no writes
python -m sales.backfill_mail_segments               # live; idempotent
```

Then let the beats take over: `process_mail_pool_sender_batch` (every 10 min),
`process_mail_pool_batch` (per-email, manual/`POST /api/mail/ai-process`), and
`audit_prefiltered_mail` (nightly 02:00 UTC). Restart the worker + beat after
deploy.

### Ops

- `GET /api/mail/ai-stats` — processed / prefiltered / pending counts, rule↔AI
  disagreement rate (7d), and Bedrock token usage by model (7d).
- On Bedrock throttling/outage the run stops and leaves emails **unmarked**
  (no partial `ai_analysis`, no burned attempt); the next beat retries.
- Mail-sourced leads run through `bucket_classifier` + outreach qualification.
  **Inbound senders are never cold-outreach targets** — anyone who has emailed
  us is `cold_outreach_blocked` and routed to
  `email_automation.warm_outreach_queue` for human follow-up.

## Tests

```bash
python -m pytest backend/tests/test_bedrock_client.py \
                 backend/tests/test_icp_query_generation.py \
                 backend/tests/test_icp_query_ai.py \
                 backend/tests/test_backfill_enrich.py \
                 backend/tests/test_bucket_classifier.py \
                 backend/tests/test_outreach_qualification.py \
                 backend/tests/test_outreach_mailer.py \
                 backend/tests/test_mail_pool_ai.py \
                 backend/tests/test_batch_and_sns.py -q
```

(Name the files explicitly — three legacy test files in the same directory hang
on collection; pre-existing issue.)

## Troubleshooting

- **`ModelAccessError` at startup** — model not enabled in ap-south-1, or the
  ID string differs from the default. The error lists what IS visible; fix the
  env var.
- **"qualified leads: 0"** — expected until enrichment populates emails; run
  `funnel_report()` (see `leads/outreach_qualification.py`) to see which gate
  everything dies at. As of the last audit all 6,886 leads fail at `no_email`.
- **Everything in REVIEW** — both model passes failing; check credentials and
  the `bedrock call` INFO lines (model, latency, token counts are logged on
  every call).
- **Batch job `Failed`** — almost certainly the native request schema; check
  the job's failure message in the Bedrock console, and inspect
  `.backfill_batch_preview.jsonl` from a dry run.
- **CSE silent** — 24h cooldown: `db.scheduler_state.findOne({_id: "google_cse_state"})`.
- **Suppression split-brain (known, unresolved)** — canonical list is
  `email_automation.suppression_list` (`campaigns/suppression.py`), but
  `outreach_engine/sending_engine.py` and `canonical_ingestion.py` reference a
  different collection (`outreach_bounce_suppression`) in *different
  databases*. Consolidate before scaling sends.
