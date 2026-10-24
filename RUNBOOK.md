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
| `OUTREACH_SENDER_POSTAL_ADDRESS` | optional; printed in the outreach footer when set, line omitted when unset, never blocks sending. CAN-SPAM requires a physical postal address (registered office or PO box qualifies) in commercial mail to US recipients -- set a real one to satisfy that, never a placeholder |
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
company; max 2 regenerations). Sending refuses if pitch copy, sender email,
or unsubscribe URL is missing (the postal address is optional). Caps, randomized 45–180s spacing,
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

## 6. Deployment (CI/CD)

**The only deploy path is GitHub Actions** (`.github/workflows/deploy.yml`),
triggered by every push to `main`: CI gate (smoke + lead-pipeline tests +
frontend build) → SSH to the VM → snapshot VM-local edits to `/root/backups/`
→ `git reset --hard origin/main` → re-apply the snapshot (`git apply --3way`)
→ pip install → restart `torpedo-backend` + `torpedo-sales-worker` → health
poll on `:8000/docs` → `npm run build` → nginx reload.

- Secrets: `GCP_VM_IP` (=139.59.32.72 — DigitalOcean despite the name) and
  `GCP_SSH_KEY` (dedicated key, comment `github-actions-deploy@campaign_platform`,
  in the VM's `authorized_keys`). Rotate by generating a new keypair, appending
  the pubkey on the VM, and updating the secret.
- History: every run before 2026-08-04 failed at the SSH step — the old secrets
  held an unparseable key and a dead GCP IP. A `*/5min` cron calling a deleted
  `auto_pull.sh` was ALSO dead (removed; crontab backup at
  `/root/backups/crontab-20260804.bak`). Do not reintroduce a second deployer.
- **Processes, not just services.** Six systemd units run repo code
  (`torpedo-backend`, `-sales-worker`, `-linkedin-worker`, `-linkedin-beat`,
  `-panel-worker`, `-lead-gen-mcp`) plus `qre-backend` under **pm2**. All are
  restarted by the deploy. A deploy that misses one ships nothing for that
  process — celery workers once ran 8-day-old send code this way. Detect it
  with `ps -eo lstart,cmd | grep -E 'celery|uvicorn'` after a deploy.
- `qre-backend` is a survey backend: its restart drops in-flight respondents.
  During active fielding, set `SKIP_QRE_RESTART=true` and restart manually
  later. Check for live sessions first: recent `started_at`/`completed_at` in
  `qre_health_survey.respondents`.
- Not restarted, intentionally: `sfw-api` (pm2, serves `/var/www/sfw_panel`,
  a different repo). The `enrichment-runner` pm2 entry was **removed**
  2026-08-04 — stopped since ~May, 3,269 restarts; lead classification is
  driven by the leads scheduler inside `torpedo-backend` (verified: 59 leads
  classified in the preceding 24h). Recoverable from
  `/root/backups/pm2-processes-*.json`; the script remains at
  `backend/scripts/run_enrichment.py` and can still be run by hand.
- Note `backend.tasks.enrichment_tasks` appears in celery's `include` list but
  is **not** in `beat_schedule` — nothing schedules it. Being importable is not
  the same as running.
- The QRE export work is now committed (`ea4a7e6`). The snapshot/re-apply step
  remains for any future VM-local edits — but prefer committing them.
- Manual fallback (workflow down): run the same steps over SSH — snapshot
  `git diff` first, always.

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
                 backend/tests/test_batch_and_sns.py \
                 backend/tests/test_outreach_send_caps.py -q
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
- **Suppression: RESOLVED 2026-09-01.** There were three lists in three
  databases (`email_automation.suppression_list`,
  `torpedo.outreach_bounce_suppression` with 11,508 docs, and
  `campaign_platform.panel_email_suppression`) and no sender read more than
  one, so unsubscribing from one channel left you subscribed to the other two.
  `backend/messaging/suppression.py` is now the single reader/writer;
  `email_automation.suppression_list` is canonical.

  Reads are read-through (canonical, then both legacy stores) so turning this
  on could only ever suppress MORE mail, never less. Collapse them with:

  ```bash
  python -m scripts.migrate_suppressions_unified --dry-run   # always first
  python -m scripts.migrate_suppressions_unified
  ```

  The dry run prints how many addresses were suppressed in exactly one list —
  every one of those is a person who kept receiving mail from the other
  channels. Legacy collections are never deleted; drop the `_LEGACY`
  read-through in `messaging/suppression.py` only once every sender calls it.

---

## 7. Sending (the facade)

**Every outbound email goes through `backend/messaging`** (TOR-06). Thirteen
modules could previously send independently; caps lived in one of them and
counted one collection, so nothing saw total volume. That is what produced the
2026-08 over-send (past the Gmail 2,000/day cap, 45% bounce).

```python
from messaging import send

result = send(
    to_email=lead["email"],
    subject=subject,
    message=built_mime_message,      # or body_text= / body_html=
    transport=dispatch,              # your existing sender; returns a message id
    identity=SENDER_EMAIL,           # what carries the budget AND the reputation
    channel="cold_outreach",
)
if not result:
    log.info("not sent: %s (%s)", result.reason, result.category)
```

Guarantees, in order: ONE suppression check that **fails closed** → a
per-identity budget spanning every channel → the transport → ONE log
(`email_automation.email_send_log`, bodies never stored).

| Variable | Default | Purpose |
|---|---|---|
| `SENDING_ENABLED` | `true` | **Kill switch.** `false` stops all outbound mail immediately, no deploy needed. Read on every call. |
| `SEND_BUDGET_DEFAULT_DAILY` | `1500` | Per-identity daily cap (Gmail's hard limit is 2,000) |
| `SEND_BUDGET_DEFAULT_HOURLY` | `200` | Per-identity hourly cap |
| `SEND_BUDGET_TRANSACTIONAL_RESERVE` | `150` | Daily quota withheld from bulk, so a campaign cannot starve a password reset |
| `SEND_BUDGET_<IDENTITY>_DAILY` | — | Per-identity override; identity uppercased, non-alphanumerics to `_` |

Ops endpoints (on `/deliverability`, which nginx already proxies):

- `GET /deliverability/sending/status?identity=<addr>` — kill-switch state,
  budget usage, suppression counts per store, recent sends
- `GET /deliverability/sending/suppression/<email>` — is it blocked, why, and
  which list holds it
- `POST` / `DELETE` on `/deliverability/sending/suppression` — suppress or
  release an address **everywhere at once**

**Migration status.** `leads/outreach_mailer.py` is wired. The panel senders,
`campaigns/send_queue`, `outreach_engine/sending_engine`, the Gmail services and
`cold_outreach_router` still send directly — they are covered by the shared
suppression list (via the read-through) but **not yet by the shared budget**.
Route them through `messaging.send` before scaling volume.

## 8. CRM platform operations (added 2026-10-24, CRM audit Phase 3–5)

All times IST. Prod: `torpedo-prod` (139.59.32.72), code in `/var/www/campaign_platform`.

### Restart and health
```bash
systemctl restart torpedo-backend torpedo-panel-worker torpedo-sales-worker
curl -s 127.0.0.1:8000/health            # {"status":"healthy",...}
tail -f /var/log/torpedo_backend.log     # boot prints one ✅ line per router / scheduled job
```
A restart resets every interval job's timer (mail pipeline 5 min, RFQ 10 min, vendors 15 min, web 30 min).
If you deploy repeatedly, those jobs fire later than usual.

### Deploy (backend + frontend)
```bash
cd /var/www/campaign_platform && git fetch origin && git merge --ff-only origin/main
cd backend && set -a && . ./.env && set +a && ./venv/bin/python -c "import main"   # import check before restart
systemctl restart torpedo-backend torpedo-panel-worker torpedo-sales-worker
cd ../Campaign_platform && npx vite build --outDir dist_new --emptyOutDir \
  && mv dist dist_prev_$(date +%Y%m%d) && mv dist_new dist                     # rollback: swap dist_prev back
```
Pushing to GitHub does not deploy anything on its own.

### Where to look day to day
- `/admin/review-queue` is the one work list. It holds approve, correct, reject and reassign actions for every module.
- `/admin/command-centre` shows the business pulse and a ranked "needs attention" list.
- `/admin/dashboards/<module>` shows each module's KPIs. A KPI with no data source yet says so.
- `GET /api/platform/shadow-report?hours=24` shows what every module would have done (addresses masked).

### Module modes: sandbox, shadow, live
Every new module starts in **shadow**. It records decisions in its own collection and sends nothing:

| module | config section | decisions collection | job |
|---|---|---|---|
| inbound mail pipeline | `torpedo_settings.config {_id: mail_pipeline}.mode` | `mail_decisions` | every 5 min |
| RFQ extract/price | `rfq.mode` | `rfq_decisions` | every 10 min (skips until `QWEN_ENDPOINT_QWEN2_5_7B_INSTRUCT` is set) |
| Operations | `ops.mode` | `ops_decisions` | daily 18:00 |
| Vendors | `vendors.mode` | `vendor_decisions` | every 15 min |
| Re-engagement | `reengagement.mode` | `reengagement_decisions` | nightly 02:00 |
| Service Delivery | `service_delivery.mode` | `service_delivery_decisions` | daily 09:00 |
| Website follow-ups | `web.mode` | `web_decisions` | every 30 min; audiences daily 06:30 |
| Receivables / bank | `accounting.mode` | `finance_decisions`, `finance_db.bank_transactions` | 09:30 / 10:00 |

To switch a module, change its config section. This needs the `approve` capability and is audit-logged:
```bash
curl -X PUT -b <session> https://torpedo.cogentixresearch.com/api/platform/config/ops -d '{"mode":"live"}' -H 'content-type: application/json'
```
"Live" here means the module applies its record changes and puts its mails in the Review Queue as drafts. **Sending real mail** is controlled separately by `MAIL_MODE` (messaging/facade.py):
- Lead channels (`outreach`, `sales_outreach`, `campaign`, `nurture`, `reengagement`) stay in sandbox unless their own `MAIL_MODE_<CHANNEL>=live` is set. The global `MAIL_MODE` never opens them. A per-BU override is `MAIL_MODE_OUTREACH_SFW=live`.
- Outreach also needs the kill switch open: `torpedo.outreach_kill_switch {_id: global, paused: false}` plus `{_id: "bu:<business>", open: true}` for each BU.
- `SENDING_ENABLED=false` stops all outbound mail at once.

### Retry failed AI jobs
`/admin/review-queue` has a failed-jobs tab, which calls `POST /api/platform/ai/failed-jobs/{id}/retry`.
Failed and missed scheduler runs are in `torpedo_settings.job_runs`. They appear on the System Health dashboard and in "needs attention".

### Change config
`GET /api/platform/config` lists every section with its defaults merged in. `PUT /api/platform/config/{section}` changes one; unknown keys are rejected.
Owner-only values:
- `entities` (GSTIN / PAN / address / bank; invoicing is blocked while blank)
- `accounting.gst_rate`, `accounting.tds_sections`
- `ops.pm_by_bu`
- `service_delivery.rate_table`
- `web.tags` (ad IDs)
- `kpi.targets`
- `rfq.cpi_bounds_usd`

### Backups and restore
- Nightly mongodump runs at 03:00 IST (cron 21:30 UTC, `/opt/crm-ops/mongo_backup.sh`), kept 14 days, in `/var/www/campaign_platform/backups/<ts>/full.archive.gz`.
- A restore check runs weekly on Sunday at 04:00 IST (`/opt/crm-ops/mongo_restore_verify.sh`, temporary mongod on :27019).
- Restore one collection: `mongorestore --uri "$MONGO_URI" --gzip --archive=<file> --nsInclude='crm_db.accounts' --drop`.
  Note that `--drop` replaces that collection.

### Phase 4 backfill (done 2026-10-24 15:20–15:40 IST, backup 20261024T094207Z)
```bash
cd /var/www/campaign_platform/backend && set -a && . ./.env && set +a
./venv/bin/python scripts/backfill_phase4.py                    # dry run, every step
./venv/bin/python scripts/backfill_phase4.py --step rfq_bu --apply   # refuses without a dump < 3 h old
```
- Every write is stamped `backfill.<step>`, and a replaced value is kept under `legacy.<field>`. To undo a step, find the documents by `backfill.<step>` and reverse them.
- Runs are recorded in `email_automation.backfill_runs` and `crm_db.audit_log`.
- The parallel ledger is in `finance_db.journal`. Its per-entity trial balance comes from `accounting.ledger.trial_balance`.
