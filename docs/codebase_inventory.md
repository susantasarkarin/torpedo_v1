# Torpedo Codebase Inventory
> Generated: 2026-05 | Recovery Phase 0 | Updated: 2026-06-11 (cleanup sweep — see Addendum at bottom)

This document is the authoritative snapshot of the backend's structural state: routers, Celery task modules, APScheduler jobs, startup hooks, and environment variables.
Update this file whenever routers are added, removed, or moved.

---

## 1. Router Inventory

### 1.1 Mounted Routers (`backend/main.py` `include_router`)

| Router File | Prefix | Notes |
|---|---|---|
| `backend/routers/approvals.py` | (none) | |
| `backend/routers/audit.py` | `/api/audit` | conflict RESOLVED — `audit_router.py` unmounted, moved to `deprecated/` 2026-06-11 |
| `backend/routers/automation.py` | `/automation` | |
| `backend/routers/campaigns.py` | `/campaigns` | |
| `backend/routers/campaign_automation.py` | `/campaigns/automation` | double-mount FIXED 2026-06-11 — mounted once |
| `backend/routers/classification.py` | `/classification` | |
| `backend/routers/classified_gmail.py` | (none) | |
| `backend/routers/cold_outreach_router.py` | `/api/cold-outreach` | |
| `backend/routers/company_cache.py` | (none) | |
| `backend/routers/cpx_api.py` | (none) | |
| `backend/routers/deliverability.py` | `/deliverability` | |
| `backend/routers/email_campaigns.py` | `/email-campaigns` | |
| `backend/routers/email_patterns.py` | (none) | |
| `backend/routers/finance.py` | `/finance` | |
| `backend/routers/gmail.py` | (none) | |
| `backend/routers/gmail_workspace.py` | (none) | |
| `backend/routers/health.py` | (none) | |
| `backend/routers/health_router_v2.py` | `/api/health` | |
| `backend/routers/linkedin.py` | (none) | |
| `backend/routers/mail_operations.py` | (none) | |
| `backend/routers/mcp.py` | (none) | |
| `backend/routers/operations.py` | `/api/operations` | |
| `backend/routers/panel.py` | `/panel` | |
| `backend/routers/panel_admin.py` | `/api/panel-admin` | dual mount FIXED 2026-06-11 — `/api` form only (nginx only proxies `/api`) |
| `backend/routers/panel_invitations.py` | `/api/panel-admin/invitations` | |
| `backend/routers/panel_ses_webhook.py` | `/webhooks` | single mount (no `/api`) |
| `backend/routers/performance.py` | `/performance` | |
| `backend/routers/projects.py` | `/api/projects` | |
| `backend/routers/prompt_management.py` | (none) | |
| `backend/routers/review_queue.py` | (none) | |
| `backend/routers/rfq.py` | (none) | |
| `backend/routers/roles.py` | `/roles` | |
| `backend/routers/sales_accounts.py` | `/sales` | |
| `backend/routers/sales_dashboard.py` | (none) | |
| `backend/routers/sales_outreach.py` | `/api/sales-outreach` | |
| `backend/routers/settings.py` | (none) | |
| `backend/routers/support.py` | `/api/support` | |
| `backend/routers/traffic.py` | (none) | |
| `backend/routers/unified_inbox.py` | `/inbox` | |
| `backend/routers/unified_vendors.py` | `/api/vendors` | |
| `backend/routers/users.py` | `/users` | |
| `backend/routers/vendor_leads.py` | `/vendor-leads` | |
| `backend/app/routers/cint.py` | (none) | |
| `backend/app/routers/cpx.py` | `/cpx` | |
| `backend/app/routers/gmail_router.py` | `/gmail` | |
| `backend/app/routers/survey_allocation.py` | (none) | |
| `backend/app/routers/survey_pool.py` | (none) | |

### 1.2 Unmounted Routers (defined but NOT in `main.py`)

| Router File | Prefix | Status |
|---|---|---|
| `backend/routers/agents.py` | `/agents` | Dead / incomplete |
| `backend/routers/autopilot.py` | `/api/autopilot` | Dead / incomplete |
| `backend/routers/intelligence.py` | `/api/intelligence` | Dead / incomplete |
| `backend/routers/marketing.py` | `/marketing` | Dead / incomplete |
| `backend/routers/team.py` | `/team` | Dead / incomplete |
| `backend/app/routers/outreach_api.py` | `/api/outreach` | Dead / incomplete |

(`ai_governance_router.py`, `predictions.py`, `public_website.py`, `seo_monitoring.py`, `audit_router.py` were fully orphaned — moved to `backend/deprecated/routers/` 2026-06-11.)

### 1.3 Duplicate Router Files (functional overlap, same domain)

| Canonical | Duplicate | Action |
|---|---|---|
| `backend/routers/gmail.py` | `backend/app/routers/gmail_router.py` | Consolidate → Phase 6 |
| `backend/routers/cpx_api.py` | `backend/app/routers/cpx.py` | Consolidate → Phase 6 |
| `backend/routes/analytics_routes.py` | (many analytics routers) | Consolidate → Phase 6 |

---

## 2. Celery Task Inventory

### 2.1 Registered Task Modules (`backend/celery_app.py` `include` list)

| Module | Tasks | Queue |
|---|---|---|
| `backend.tasks.email_tasks` | Email processing tasks | `email_sync` |
| `backend.tasks.ai_tasks` | AI processing tasks | `ai_processing` |
| `backend.tasks.api_tasks` | API tasks | `api_tasks` |
| `backend.tasks.finance_tasks` | Finance tasks | `finance` |
| `backend.tasks.sales_tasks` | Sales tasks | `sales` |
| `backend.tasks.traffic_tasks` | Traffic tasks | `traffic` |
| `backend.tasks.outreach_tasks` | Cold outreach (AsyncOpenAI) | default |
| `backend.tasks.linkedin_tasks` | LinkedIn automation | `linkedin_automation` |
| `backend.tasks.cint_survey_scoring` | Cint survey tasks | `surveys` |
| `backend.sales.tasks` | Sales tasks | `sales` |
| `backend.sales.outreach_pipeline` | Sales outreach pipeline | `sales` |
| `backend.sales.mail_pool_extractor` | Mail pool extraction | `sales` |

### 2.2 Unregistered Task Modules — ALL RESOLVED

All four previously-unregistered modules (`lead_agent_tasks`, `enrichment_tasks`, `app.tasks.outreach_tasks`, `campaigns.send_queue`) are now in the `celery_app.py` `include` list (verified 2026-06-11).

### 2.3 Celery Queue Definitions

Defined in `backend/celery_app.py`:
`default`, `email_sync`, `ai_processing`, `api_tasks`, `finance`, `sales`, `traffic`, `surveys`, `linkedin_automation`

---

## 3. APScheduler Jobs

### 3.1 Jobs in `backend/background_job_scheduler.py`

| Job ID | Function | Schedule |
|---|---|---|
| `check_resume_jobs` | `check_and_resume_paused_jobs` | every 5 min |
| `monitor_jobs` | `monitor_active_jobs` | every 10 min |
| `cleanup_jobs` | `cleanup_stale_jobs` | every 30 min |
| `reset_errors` | `reset_error_tracking` | daily 01:00 UTC |
| `cint_survey_cleanup` | `async_cint_survey_cleanup` | every 5 min |
| `background_enrichment` | `background_enrich_leads` | every 30 min |
| `proactive_pattern_discovery` | `proactive_pattern_discovery` | daily 02:30 UTC |
| `email_metadata_classification` | `_run_email_metadata_classification` | every 2 hours |
| `mailpool_backfill` | `_run_mailpool_backfill` | every 15 min |
| `rule_based_lead_classification` | `_run_lead_classification` | every 5 min |
| `mail_pool_stats_cache` | `_run_mail_pool_stats` | every 15 min |

### 3.2 Jobs in `backend/main.py` startup event

| Job ID | Function | Schedule |
|---|---|---|
| `cpx_refresh` | `refresh_cpx_inventory` | configurable interval |
| `gmail_sync` | `background_gmail_sync` | every 300s |
| `cint_health_check` | `cint_health_check` | every 1800s |
| `cint_inventory_refresh` | `refresh_cint_inventory` | every 300s |
| `outreach_send_processor` | `_outreach_send_job` | every 60s |

---

## 4. Startup Hooks

| Location | Type | Notes |
|---|---|---|
| `backend/main.py:1677` | `@app.on_event("startup")` | Main startup event — registers APScheduler jobs |
| `backend/main.py:1419` | `asyncio.create_task(_check_and_resubscribe())` | Called inside startup event |
| `backend/main.py:1464` | `asyncio.create_task(_fetch_and_sync())` | Called inside startup event |
| `backend/main.py:1802` | `asyncio.create_task(run_web_search_job(job_id))` | Called inside startup event |
| `backend/main.py:1829` | `asyncio.create_task(asyncio.to_thread(refresh_cpx_inventory))` | Called inside startup event |
| `backend/main.py:1897` | `asyncio.create_task(asyncio.to_thread(refresh_cint_inventory))` | Called inside startup event |
| `backend/analytics/report_builder.py` | Lazy global via `get_report_builder()` | FIXED — no longer fires on import |
| `backend/app/integrations/cint_integration.py:319` | `@app.on_event("startup")` | ⚠️ Second startup hook — ordering is unpredictable |

---

## 5. AI Governance Bypass Audit

Files that instantiate OpenAI/Gemini clients directly instead of using `ai_governance/`:

| File | Issue |
|---|---|
| `backend/campaigns/auto_response_drafting.py:103` | `openai.OpenAI()` direct |
| `backend/email_classification/reply_sentiment.py:170` | `openai.OpenAI()` direct |
| `backend/email_classification/reply_intent.py:154` | `openai.OpenAI()` direct |
| `backend/leads/gemini_enrichment.py` | 6 separate direct Gemini instantiations |
| `backend/routers/prompt_management.py:505` | `openai.OpenAI()` direct |
| `backend/routers/cold_outreach_router.py:510` | `openai.OpenAI()` direct |
| `backend/app/tasks/outreach_tasks.py` | 5 direct instantiations (Gemini) |
| `backend/app/routers/outreach_api.py:103` | `openai.OpenAI()` direct |

---

## 6. Dependency Versions (as of Phase 0 snapshot)

| Package | Version |
|---|---|
| fastapi | 0.136.0 |
| uvicorn | 0.46.0 |
| pydantic | 2.13.3 |
| motor | 3.7.1 |
| celery | 5.6.3 |
| redis | 7.4.0 |
| APScheduler | 3.11.2 |
| openai | 2.32.0 |
| httpx | 0.28.1 |
| requests | 2.32.5 |
| aiohttp | 3.13.5 |

Total locked packages: 136
Requirements file: `backend/requirements-outreach.txt` (only one — no `requirements.txt` at root)

---

## 7. Environment Variables

### Database
`MONGO_URI`, `MONGO_DB_NAME`, `REDIS_URL`, `REDIS_PASSWORD`

### AI Providers
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `PERPLEXITY_API_KEY`, `GOOGLE_API_KEY`

### Auth
`JWT_SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`

### Email / SMTP
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `GMAIL_APPLICATION_PASSWORD`

### Webhooks
`CINT_WEBHOOK_URL`, `CINT_WEBHOOK_SECRET`, `STRIPE_WEBHOOK_SECRET`

### AWS (found in .env)
`AWS_ACCESS_KEY_ID` (+ related keys — see .env for full list)

### Feature Flags / Misc
`ENVIRONMENT`, `DEBUG`, `ENABLE_CINT_INTEGRATION`, `ENABLE_CPX_INTEGRATION`, `MAX_EMAIL_SYNC_STREAMS`

Total .env keys: 32

---

## 8. Dead Code Candidates (Phase 1)

| File | Reason |
|---|---|
| `backend/leads/openai_wrapper.py` | Raises `RuntimeError("openai_wrapper is retired...")` on import |
| `backend/agents/mail_segregation_agent.py.bak` | `.bak` file, not importable |
| `backend/agents/mail_segregation_agent_v2.py` | No imports anywhere in codebase |
| `backend/leads/web_search_enrichment.py` | Disabled (broken by openai_wrapper chain) |
| Root `check_*.js`, `fix_panel_*.py`, `patch_traffic.py` | Debug/investigation scripts not part of the application |

---

## Phase 0.5 — Config Audit Findings

| Category | Finding | Severity |
|---|---|---|
| Celery Routing | `lead_agent_tasks` module not in `include` list | CRITICAL |
| Celery Routing | `enrichment_tasks` module not in `include` list | HIGH |
| Celery Routing | `backend.app.tasks.outreach_tasks` not in `include` list | HIGH |
| Celery Routing | `campaigns.send_queue` not in `include` list | MEDIUM |
| Router Conflicts | `/api/audit` prefix used by both `audit.py` and `audit_router.py` | HIGH |
| Dual Mount | `campaign_automation_router` mounted twice in main.py | MEDIUM |
| Dual Mount | `panel_admin`, `panel_invitations`, `panel_ses_webhook` mounted with and without `/api` prefix | MEDIUM |
| Startup Hooks | Two separate `@app.on_event("startup")` hooks (main.py + cint_integration.py) | MEDIUM |
| Startup Hooks | `BackgroundScheduler()` in `report_builder.py` fires on import | MEDIUM |

## Phase 0.6 — Dependency Audit Findings

| Finding | Detail |
|---|---|
| No root requirements.txt | Only `backend/requirements-outreach.txt` exists |
| 136 total locked packages | No pip freeze committed to repo |
| pipdeptree not pre-installed | Installed ad-hoc for this audit |
| APScheduler 3.x | Using 3.x not 4.x (3.x is compatible with current usage pattern) |
| openai 2.x | New major version — verify no breaking changes vs prior usage |

---

## Addendum — 2026-06-11 Cleanup Sweep (branch `fix/cleanup-sweep`)

- Removed `celery-beat>=2.5.0` from requirements-outreach.txt (not a PyPI package; broke `pip install` on every deploy — beat is built into celery).
- deploy.yml: added `set -e` + a polling health gate on :8000 (up to 300s) so a dead backend fails the deploy.
- main.py: `campaign_automation` mounted once; bare (non-`/api`) mounts of `panel_admin` and `panel_join` removed — nginx only proxies the `/api` form and invite links are always generated with `/api`.
- Quarantined 35 fully-orphaned backend modules into `backend/deprecated/` (dead routers, the Agent-5 campaign engine, dead sales/leads routers, `leads/routers/` sub-package, `router_registry.py`, finished one-shot migrations). `indexes.py` / `create_templates.py` intentionally left (manual ops scripts).
- Archived 27 orphaned frontend files into `Campaign_platform/src/_archived/`; deleted 0-byte `SendEmailModal.jsx`.
- Untracked PII mailpool CSVs (gitignored, kept on disk — note they remain in git history); removed `.tmp_login_probe.py`, `build-output.txt`.
- Multiple `@app.on_event("startup")` hooks (main.py + `setup_cint_with_fastapp`) confirmed NOT a bug — FastAPI runs them in deterministic registration order.
- Still open: AI-governance bypasses (§5), monolith files (traffic/leads/gmail/finance routers + main.py all 3,500-4,300 lines), gmail/cpx/cint duplicate-router consolidation, `legacy_*` routers, `ingestion.py` vs `ingestion_vm.py` fork, RBAC default-off, prod admin password rotation.
