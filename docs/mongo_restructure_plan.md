# MongoDB Restructure Plan

> **Corrections from the production inventory of 2026-11-16 (read before acting on any phase).**
> This plan was written from static code analysis. Real production numbers are in `docs/mongo_prod_inventory_2026-11-16.md` and contradict it in these places:
>
> - Marketing collections are NOT in `crm_db` on prod. They live in `email_automation` (`review_queue_items` 1,331 docs and written daily, `web_events`, `web_audiences`, `seo_issues`, `seo_audits`). Marketing steps must be rewritten with `email_automation` as the source.
> - `torpedo_gmail.mail_pool` does not exist. The mail store is `torpedo_gmail.email_metadata` only: 392,803 docs, 3.2 GB, written continuously (the plan assumed about 142k).
> - `survey_allocation` is NOT retirable as planned: `surveys` 2.75M docs and `survey_metrics` 2.79M docs are written daily. A cross-database move is a full copy, not a rename.
> - These databases do not exist on prod, so only code references need removing: `internal_db`, `gmail_archive`, `prompt_management`, `cpx_db`, `cint_db`, `leads`, `ai_enrichment`. `linkedin_db` exists but is empty.
> - Outreach v1 is already empty on prod (`campaigns`, `campaign_sends`, `campaign_recipients`, `sends` all 0 docs), so retiring it is a code-only change.
> - `email_automation`: 77 of 185 collections are empty, 29 stale, 61 live.
> - `operations_db` (36 docs) and `marketing_db` (3 docs) are tiny but live.
> - Still open, owner decision: live sales paths (`sales/outreach_pipeline.py`, `sales/validation.py`, `sales/tasks.py`, `routers/sales_outreach.py`, `app/services/crm_service.py`) use `campaign_platform.leads` (193 orphan docs, last write 2026-04-13) through `db_pools`. Pick `crm_db.leads` (13,238) or `email_automation.leads` (339) before re-pointing them.
>
> No data has been moved. Done on 2026-11-16: 32 missing indexes built on prod (list in `/root/backups/index_built_20261116.json` on the VM); finance, traffic and sales-dashboard tasks re-pointed in code to the databases their collections live in.


Date: 2026-11-15. Scope: single self-hosted Mongo (no replica set, no multi-document transactions), 8GB VM shared with the v2 repo. Source of truth for counts: static inventory (counts +/-10%, existence of db.collection pairs reliable).

Phase 0 (code only: single factory `db.py`, typo dbs `cpx_db`/`cint_db` fixed, per-call clients removed, one registry `indexes.py` covering crm_db and torpedo) is DONE and is the precondition for everything below. This plan starts at Phase 1.

Note on the working tree: the branch `chore/structure-cleanup-2026-11-15` already deletes `outreach/`, `email_crm_pipeline/`, `analytics/`, `intelligence/`, `ml/`, `email_classification/` and the legacy routers. Writer lists below are from the inventory; any writer already deleted on that branch drops out of the effort counts. Re-grep each collection before its cutover (Phase 3 gate).

## Standing rules (apply to every phase)

| Rule | Detail |
|---|---|
| Move, do not rename | A collection keeps its name when it changes db. Renames multiply code churn. Exceptions are name collisions at the destination (listed explicitly). |
| Route table | `db.py` gets one dict `ROUTES = {"leads_enriched": ("torpedo","leads_enriched"), ...}` and one accessor `coll(name)`. Mode per group from env `DB_ROUTE_<GROUP>` = `old` (default), `dual`, `new`. Call-site changes are mechanical: `client["email_automation"]["x"]` becomes `coll("x")`. |
| Provenance (technical) | Every copied doc gets `_mig: {src: "email_automation.sales_accounts", batch: "20261201a", at: <utc>}`. Removed by one `$unset` after Phase 4 plus 30 days. |
| Provenance (business) | Where several stores merge into one collection, a permanent `source` field is set (examples in section 2). |
| _id policy | Pure moves preserve `_id` exactly (type included). Merges into an existing collection get a fresh ObjectId plus `legacy_id` (string) and `legacy_coll`. Never coerce string `_id` to ObjectId during a copy; report them (risk R1). |
| Copy mechanics | Python script, `bulk_write` of `ReplaceOne(upsert=True)` keyed by `_id`, batches of 500, `sleep(0.2)` between batches, one collection at a time, sorted by `_id`, resumable from last `_id`. Idempotent: re-runnable at any time. |
| Archive instead of drop | The source collection is `renameCollection`d inside its own db to `_archived_<name>_<YYYYMMDD>` (metadata-only, instant, no extra RAM or disk). A mongodump of it is taken first, which satisfies the "archive before drop" convention. Rollback is rename back. |
| Deploy | Backend and Celery workers restarted together with the same env (workers read the route table at import). Deploy is by hand (auto-deploy is not reliable): pull, check venv imports, restart backend + sales worker + linkedin-beat. |
| Prod safety | Migration scripts require `--apply` and print every resolved `(db, coll)` first. Never run tests/smoke on the VM. |

# 1. Target topology

## 1.1 Surviving databases

| Db | Role | Contents after restructure |
|---|---|---|
| crm_db | System of record | accounts, contacts, opportunities (RFQs), leads (qualified CRM leads), activities, projects, service_projects, audit_log, vendor_leads, party_relationships, users, marketing/site/SEO/ads collections (one copy), review_queue_items, pm_projects/pm_tasks/pm_time_entries, support ticket set |
| finance_db | Money | unchanged: customers, invoices, vendors, estimates, bills, payments_*, expenses, zoho_*, bank_*, journal (billing_vendors dropped) |
| torpedo_gmail | Mail store | email_metadata (mail pool), one mailbox registry, sync state, derived mail collections (classified_gmail, classified_emails, mail_summaries, mail_pool, mail_pool_stats_cache) |
| torpedo | Outreach + lead-gen | outreach_*_v2 set, bounce suppression, kill switch, quota, leads_raw, leads_enriched, lead-gen caches/logs/ICP configs, Clay set, LinkedIn set, web_search_jobs, templates |
| campaign_platform | Survey panel only | panelists, panel_invitation_log, panel_email_suppression, panel_rewards, panel_sessions, panel_vendors |
| cint_research, cpx_research, traffic_flow_db | Survey routing | unchanged, plus survey_allocation collections folded into traffic_flow_db |
| torpedo_settings | Config | app_settings, config, scheduler_config, ai_prompts, ai_governance_log, email_signatures, survey_filters, openai_usage_logs, cint_metrics, ladder_* |
| ai_governance | AI guard | unchanged (email_classification_guard, labelled_examples, qwen_jobs); added to indexes.py |
| qre_health_survey | External survey app | untouched (separate product on the VM) |

Ten live dbs after cleanup (down from about 20). Rationale: a db boundary equals lifecycle and blast radius (CRM truth, money, mail volume, outreach send state, panel, config). A naming convenience stays a collection prefix, not a db.

## 1.2 Retired databases

| Db | Decision | Reason |
|---|---|---|
| email_automation | Retire in stages (map in 1.3) | about 180 collections, catch-all |
| gmail_archive | Retire. `emails` diffed against torpedo_gmail.email_metadata by message id; unmatched rows copied in with `source: "gmail_archive"`; then archive | one legacy reader (routers/gmail.py:1755) |
| operations_db | Retire. All collections to `crm_db.mystery_<name>` (prefix avoids collisions) | one writer (routers/mystery_shopping, the only module-level Motor client); the Phase 2 pre-flight lists the real names with `list_collection_names()` |
| marketing_db | Retire. websites, navigation, pages, blog_posts to `crm_db.site_websites`, `site_navigation`, `site_pages`, `site_blog_posts` | marketing stack already lives in crm_db; routers/marketing_site is the only user |
| prompt_management | Retire. Merge into `torpedo_settings.ai_prompts` with `source: "prompt_management"` | one user; prompts are config |
| survey_allocation | Retire. respondents, surveys, survey_metrics, allocation_log to `traffic_flow_db.alloc_respondents`, `alloc_surveys`, `alloc_metrics`, `alloc_log` | allocation is routing; prefix avoids clash with cint/cpx surveys; writer is app/services/survey_allocation_service |
| internal_db | DROP (archive first) | leads/clay_models only, likely dead; confirm no reads in logs before archive |
| linkedin_db | Retire. automation_jobs to `torpedo.linkedin_automation_jobs` | joins the LinkedIn set moving from email_automation to torpedo |
| cpx_db, cint_db, leads, ai_enrichment | Phantom dbs from typos | Phase 0 fixed the code; Phase 4 checks `listDatabases` and drops any that exist and are empty; if non-empty, mongodump and review by hand |

## 1.3 email_automation collection map

"Archive" means Phase 4 rename to `_archived_<name>_<YYYYMMDD>`. Archives are dumped off-VM and dropped after 30 days.

| Group | Source collections | Destination | Reason |
|---|---|---|---|
| Lead pool | leads_raw, leads_enriched | torpedo.leads_raw, torpedo.leads_enriched (moved, same names) | enrichment pool sits beside the outreach that consumes it; link field to outreach_leads_v2 (2.1) |
| Leads legacy | leads | Archive | crm_db.leads already holds migrated rows (migrations/002); verify `legacy_id` coverage first |
| Leads mail-derived | email_leads | torpedo.leads_raw with `source: "email_leads"` | same shape class, produced by ai_classifier |
| Vendor leads | vendor_leads | crm_db.vendor_leads | 944 already flagged and copied 2026-10-24; this finishes it |
| Companies | sales_accounts | crm_db.accounts (merge, 2.2) | duplicate CRM |
| Companies | clients, vendors | crm_db.accounts (migrated by migrations/003); read-only mirror then Archive | routers still read them |
| Company caches | company_cache, ai_discovered_companies, company_domains, company_enrichment_cache, company_type_usage | torpedo (same names) | lead-gen caches, not CRM entities |
| Contacts | contacts, contact_history, email_extractions | crm_db.contacts (merge by email+account), crm_db.activities (`source: "contact_history"`), crm_db.email_extractions | second CRM written by the deleted crm_populator; readers remain |
| RFQ | rfqs, rfq_candidates, rfq_decisions, rfq_review_queue, rfq | crm_db.opportunities (`source: "rfqs"`), crm_db.rfq_candidates, crm_db.rfq_decisions, crm_db.rfq_review_queue | RFQ is an opportunity (spine intent) |
| Projects | projects, projects_qualification_backup_auto | crm_db.projects (2.5); backup collection Archive | |
| Campaigns v1 | campaigns, campaign_sends, campaign_recipients, email_campaigns, email_variants, campaign_decisions, reply_decisions, campaign_stats, campaign_optimizations, campaign_reports, ab_tests, outreach_* (v1 DI set), automation_rules, reengagement_pool, lead_outreach_drafts, outreach_send_logs | Archive | v1 retired, v2 canonical; export campaigns + sends to CSV first |
| Templates | templates, email_templates, outreach_templates | torpedo.templates (merge, `source` per origin) | |
| Templates | whatsapp_templates | crm_db.whatsapp_templates (one copy) | |
| Suppression | suppression_list | torpedo.outreach_bounce_suppression (`source: "suppression_list"`) | 2.6 |
| Mail-derived | classified_gmail, classified_emails, mail_summaries, mail_pool, mail_sender_analysis, sender_metadata | torpedo_gmail (same names) | |
| Mail stray | emails, email_conversations | merge into torpedo_gmail.email_metadata by message id where unmatched, else Archive | 2.4 |
| Mailboxes | mailboxes, gmail_accounts, imap_accounts, gmail_account_usage | torpedo_gmail.workspace_mailboxes (merge, `kind`) | 2.8 |
| Deliverability | domain_health, reputation_metrics, deliverability_alerts, email_events | torpedo (same names) | belongs to outreach sending |
| Lead-gen ops | email_patterns, email_address_structures, email_domain_structures, web_search_jobs (+_archive), search_cache (+_metrics), search_plans_cache, search_query_leads, cse_query_ledger, google_cse_*, skrapp_usage, icp_configs, icp_segments, icp_search_hints, url_validation_*, batch_enrichment_*, extraction_backlog, ingestion_log, csv_column_mappings, lead_ai_classification_logs, lead_extraction_logs, enrichment_logs, company_enrichment_logs, enrichment_runs, dedup_index, dedup_logs, ai_classified_leads, ai_review_queue, potential_client_leads, error_tracking, scheduler_logs, agent_jobs, agent_configurations | torpedo (same names) | lead-gen runtime state |
| LinkedIn | linkedin_connections, linkedin_sessions, linkedin_messages, linkedin_activities, linkedin_templates | torpedo (same names) | |
| Marketing | content_items, gsc_*, inbox_items, review_queue_items, web_events, web_sessions, web_visitors, web_audiences, web_decisions, seo_issues, ad_accounts, ads, decisions, consents | crm_db (same names; crm_db copy wins on conflict, EA copy Archive after diff) | 2.7 |
| Settings | app_settings, scheduler_settings, scheduler_state | torpedo_settings (2.9) | |
| Usage | openai_usage_logs, ai_usage_logs | torpedo_settings.openai_usage_logs (merge, `source`) | |
| Relationships | party_relationships | crm_db.party_relationships | override list is CRM truth (Hansa client, Cint vendor) |
| Auth | users | crm_db.users | auth must not live in a catch-all; routers, app/security, rbac re-pointed together |
| Panel | panel_vendors | campaign_platform.panel_vendors | |
| Audit/activity | activities, audit_log, email_audit_log | crm_db.activities, crm_db.audit_log (merge with `source`) | spine already owns both |
| Ops state | migrations_log, backfill_runs, reports, inbox_items, lists, review_queue_items | crm_db (same names; review queues merge with `queue` field) | |
| Mail pipeline | threads, mail_followups, mail_events, vendor_bids | crm_db (same names) | outputs of mail_pipeline/runner |
| Platform | ladder_jobs, ladder_spend, user_profiles | torpedo_settings | |
| Analytics | cohorts, funnels, email_tracking, scheduled_reports | Archive | writers deleted on the cleanup branch |
| Cleanup logs | six `*_cleanup_log`, email_recovery_log | DROP (Archive then 30 days) | one-off script residue |

# 2. Entity consolidation (10 overlap groups)

## 2.1 Leads (7 stores, about 25 writers)

| Item | Decision |
|---|---|
| Canonical, cold prospects | `torpedo.outreach_leads_v2` (send state, gates, suppression, enrollment). |
| Canonical, qualified leads | `crm_db.leads` (post-reply, inbound, marketing form). Written only through crm_service. |
| Enrichment pool | `torpedo.leads_raw` (staging) and `torpedo.leads_enriched` (verdicts: classification_basket, outreach_bucket). Moved, not merged. |
| Link fields | `outreach_leads_v2.enriched_id` -> leads_enriched `_id`; `crm_db.leads.outreach_lead_id` -> v2 `_id`. |
| Semantics warning | Merging leads_enriched into v2 would blur "this company was classified" with "this address may be mailed". The 2026-09-26 incident (enrollment read the wrong classifier, 8,759 REJECT/REVIEW leads mailed) came from that blur. Keep two collections plus a link; the send gate reads the verdict through the link. |
| Provenance | email_leads rows into leads_raw: `source: "email_leads"`. email_automation.leads rows not already in crm_db.leads: `source: "legacy_leads"`, `legacy_id`. |
| Mirrors | email_automation.leads_raw/leads_enriched are read-only mirrors in Phase 3, archived in Phase 4. campaign_platform.email_leads is dropped. |
| Writers to re-point | leads_enriched (9): bounce_recovery, skrapp_jobs, company_fit, automation/reply_engine, outreach_engine/sending_engine, routers/sales_accounts, background_job_scheduler, bucket_classifier, leads/scheduler. leads_raw (3): email_processor, leads/router, email_pattern_system. email_leads: ai_classifier. vendor_leads: email_processor, scripts/classify_ai_database. |

## 2.2 Accounts, customers, companies

| Item | Decision |
|---|---|
| Canonical | `crm_db.accounts`, single dedupe path `crm_service.get_or_create_account`. |
| Finance | `finance_db.customers` stays a separate entity by design; link is `customers.account_id` (backfill/finance_customers.py), `merged_into` marks losers. No change. |
| sales_accounts | Merge into accounts. Match by normalized domain, then name. Matched rows add only missing fields (never overwrite) and append `sources: ["sales_accounts"]`. Unmatched rows become accounts with `lifecycle: "prospect"`, `source: "sales_accounts"`, `legacy_id`. |
| Semantics warning | sales_accounts holds prospects scraped from mail, not companies we transact with. Do not set client or vendor on import. Relationship type is not derivable from the word RFQ; it comes only from party_relationships or an operator. If unmatched rows exceed 1,000, report to the owner before inserting. |
| clients, vendors (EA) | Already in accounts via migrations/003. Read-only mirror, then Archive. |
| company_cache, ai_discovered_companies | Not accounts. Move to torpedo; set `account_id` when a domain matches. |
| Writers to re-point | routers/sales_accounts (the six cleanup scripts are one-off and left alone or deleted). |

## 2.3 Outreach v1 vs v2

| Item | Decision |
|---|---|
| Canonical | v2 in `torpedo` (live, sends real mail). |
| v1 | email_automation campaigns, campaign_sends, campaign_recipients, email_campaigns and the v1 outreach_* set: no data moved into v2 (outreach_engine/migration.py already did it). Export campaigns + sends to CSV in `docs/archive/`, then Archive in Phase 4. |
| Writers | routers/campaigns, routers/campaign_automation, automation/*, agents/campaign_autopilot, campaigns/*, leads/campaign_integration. Decision: delete or return 410 at Phase 3 instead of re-pointing. Check no UI page still calls `/campaigns`. |
| Latent bug | outreach/router.py `Depends(get_database)` lives in a file the cleanup branch deletes; confirm it is gone. |

## 2.4 Email metadata and mail pool

| Item | Decision |
|---|---|
| Canonical | `torpedo_gmail.email_metadata` (about 142k mails, reanalysis_v2 fields). It does not move; only stray copies move into it. |
| Duplicates | campaign_platform.email_metadata, email_automation.emails, email_conversations, gmail_archive.emails. Diff by message id; absent rows are copied with `source: "<db>.<coll>"`; present rows are not touched; then Archive. |
| email_sync | Its default `MONGO_DB_NAME` is campaign_platform while services write torpedo_gmail. Fixed in Phase 1 by `coll("email_metadata")` only (R2). |
| mail_pool | `torpedo_gmail.mail_pool` canonical; email_automation.mail_pool merged by message id with `source`. Review queues: email_automation.review_queue_items and ai_review_queue merge into `crm_db.review_queue_items` with `queue: "mail"|"ai"`. |
| Writers (6) | gmail_service, gmail_workspace_service, rfq_thread_text, qualification_autofill, shadow_replay, rfq_reset_rebuild. Do not run stray-copy merges while a mail reanalysis run is active (check `backfill_runs`). |

## 2.5 Projects and RFQs

| Item | Decision |
|---|---|
| RFQ canonical | `crm_db.opportunities` (bridges spine_rfq.py and backfill_spine_rfqs.py exist). email_automation.rfqs merged with `source: "rfqs"`, `legacy_id`, matched on thread/message id first so rows already bridged are not duplicated. |
| crm_db.rfqs | Phantom (only marketing reads it). Count, Archive, re-point the marketing reader to opportunities. |
| Project canonical | `crm_db.projects` (won_handoff, rfq_from_mail). email_automation.projects merged with `source: "ops_projects"`, `legacy_id`. |
| Semantics warning | An opportunity is not a project. Do not merge them; link `projects.opportunity_id` and `service_projects.project_id`. Ops projects with no matching won opportunity import with `opportunity_id: null` and go on an owner review list. |
| torpedo_settings projects/tasks/time_entries | Internal PM, a different meaning from client projects. Move to `crm_db.pm_projects`, `pm_tasks`, `pm_time_entries` (rename required to avoid colliding with crm_db.projects). Writer: projects/service.py only. |
| campaign_platform.projects | Archive. |
| String-_id phantoms | The merge skips and reports any source row with a string `_id` whose 24-hex form exists as an ObjectId in the target (R1). The "try as string _id" fallbacks (routers/cpx_api.py:330, routers/traffic.py:5410) are removed only after the Phase 2 histogram shows zero string ids in the affected collections. |
| Writers (about 12 files) | projects (5 writers incl. qualification_autofill, backfill, routers, services); rfqs: department_router, sales/schemas. Re-point via `coll()`. |

## 2.6 Suppression

| Item | Decision |
|---|---|
| Canonical, cold mail | `torpedo.outreach_bounce_suppression` (8 files, name kept). email_automation.suppression_list merged in with `source: "suppression_list"`, lowercase email as the unique key. |
| Panel | `campaign_platform.panel_email_suppression` stays. Semantics differ (panelist consent and bounce vs cold prospect). Not merged. |
| Link | One helper `messaging/suppression.is_suppressed(email, scope)` with scope outreach, panel, all. The unsubscribe handler writes both stores with `source`. |
| Gate | The unique index on normalized email is created only after the duplicate report is empty (R6). |
| Writers | sales/outreach_pipeline, cold_outreach_router, messaging/suppression, panel_bounce_handler, scripts/migrate_suppressions. |

## 2.7 Marketing (3 homes)

| Item | Decision |
|---|---|
| Canonical | `crm_db` (marketing/schema.py already targets it). |
| Moves | torpedo.seo_audits, seo_issues, cwv_results to crm_db (cwv_results exists there: merge with `source: "torpedo"`). email_automation duplicates of content_items, gsc_pages_daily, inbox_items, review_queue_items, web_events, web_sessions, web_visitors, whatsapp_templates, seo_issues: diff by `_id` and natural key, copy only missing rows, then Archive. |
| Writers (about 12) | marketing/*, web_tracking/*. Mostly flip to `coll()`. |
| Index | marketing/schema.py creates 1 index for 15+ collections; add them to indexes.py in Phase 1 (non-unique). |

## 2.8 Mailbox registries (8 collections)

| Item | Decision |
|---|---|
| Canonical (sync accounts) | `torpedo_gmail.workspace_mailboxes` (12 writers). mailboxes, accounts, gmail_accounts, imap_accounts (both dbs) merged with `kind: "gmail"|"workspace"|"imap"`, `source`, unique key `email`. |
| Outreach senders | `torpedo.outreach_mailboxes` stays (quota, warmup, kill switch). A mailbox can sync mail without being allowed to send, so no merge; link `mailbox_id` -> workspace_mailboxes `_id`. |
| Secrets | Credential and token fields are copied opaque; the copy script never prints or logs them. |
| Writers | gmail_service, gmail_workspace_service, email_sync, scripts. |

## 2.9 Settings

| Item | Decision |
|---|---|
| Canonical | `torpedo_settings.app_settings` (about 30 files) and `config` (config_store). |
| Merge | email_automation.app_settings (routers/operations.py:1444) merged key by key. On conflict torpedo_settings wins and the loser goes to `app_settings_conflicts` for owner review. |
| Scheduler | `scheduler_config` canonical; scheduler_settings and scheduler_state merged with `kind: "settings"|"state"`. scheduler_state is hot runtime data: merge last, inside the dual-write window. |
| Not merged | `ai_governance` stays its own db (AI guard blast radius). |

## 2.10 Vendors

| Item | Decision |
|---|---|
| Canonical | `crm_db.accounts` with `account_type: "vendor"` (relationship per party_relationships). |
| Finance | `finance_db.vendors` stays (bills, payments); add `account_id` link (same pattern as customers). billing_vendors (index only) is dropped. |
| Leads and panel | vendor_leads to crm_db.vendor_leads; panel_vendors to campaign_platform. |
| Reader | routers/unified_vendors keeps merge-on-read but sources become accounts + the finance link. repositories/vendor_repo re-pointed via `coll()`. |
| Semantics | Cint = vendor, Hansa = client (override list). A merge must never infer vendor or client from RFQ mail. |

## 2.11 Second CRM (inventory group J)

email_crm_pipeline (DB_CRM defaulting to email_automation) is deleted on the cleanup branch. Its output collections (contacts, sales_accounts, rfqs, contact_history, email_extractions) are handled in 1.3 and 2.2/2.5. After Phase 3 the env vars `CRM_TARGET_DB`, `EMAIL_SOURCE_DB` are removed.

# 3. Migration sequence

All phases run per collection group, not big-bang. Group order, lowest risk first:

| Order | Group | Why here |
|---|---|---|
| 1 | internal_db, cleanup logs, gmail_archive, prompt_management, marketing_db, operations_db, linkedin_db | few readers, no live writes |
| 2 | settings, templates, relationships, users | small, read-heavy |
| 3 | marketing duplicates, review queues | no sends depend on them |
| 4 | lead-gen ops and caches, leads_raw/leads_enriched | many files, mechanical |
| 5 | mailbox registry, mail stray copies | touches sync; mail reanalysis idle |
| 6 | suppression | send path; outside send windows |
| 7 | sales_accounts, contacts, rfqs, projects merges | semantic merges, owner review in the loop |
| 8 | campaigns v1 retirement | last; route deletion |

## Phase 1: Dual-write / shadow (code deploy, no data moved)

| Step | Action |
|---|---|
| 1 | Add `ROUTES`, `coll()` and `DB_ROUTE_*` modes to `db.py`. Default `old`: behavior identical to today. |
| 2 | In `dual` mode, writes go to old first, then to new via `update_one(..., upsert=True)` keyed by `_id`. A failure on the new side is logged and counted (`dualwrite_fail` in torpedo_settings.config), never raised. Reads stay on old. |
| 3 | Add missing collections to `indexes.py` (non-unique only): marketing set in crm_db, torpedo extras, ai_governance, cint_research. |
| 4 | Flip `DB_ROUTE_<GROUP>=dual` one group at a time, restart backend + workers. |
| 5 | Fix env drift: remove per-package `MONGO_DB_NAME` defaults; email_sync and leads read the route table only. |

Backup before the first flip:
```
nice -n 19 ionice -c3 mongodump --uri="$MONGO_URI" --db=torpedo --gzip --archive=/var/backups/mongo/torpedo_20261201_p1.gz
nice -n 19 ionice -c3 mongodump --uri="$MONGO_URI" --db=email_automation --gzip --archive=/var/backups/mongo/ea_20261201_p1.gz
```
Run one at a time; check `df -h /var/backups` and `free -m` first; use `--excludeCollection` for large low-value logs (web_events, search_cache).

Rollback: set `DB_ROUTE_<GROUP>=old`, restart. New-side writes are inert (nothing reads them) and are removed by `deleteMany({"_mig.batch": ...})` or by dropping the new collection.

Exit criteria: 48 hours of dual-write with `dualwrite_fail` = 0 per group.

## Phase 2: Copy with provenance and verification

Per group, off-peak (India night), one collection at a time, abort if swap above 60% or load above 3. llama servers untouched.

| Step | Action |
|---|---|
| 1 | Pre-flight (read-only): per source collection count, `_id` type histogram, duplicate report for the planned unique key. |
| 2 | Run the copy script (Standing rules); `_mig.batch` set to the run id. |
| 3 | Run the verification below. All must pass. |
| 4 | Create unique indexes on the new collection only after the duplicate report is empty (R6). |

Backup (only for destinations that already exist and receive merges; fresh destinations roll back by drop):
```
nice -n 19 ionice -c3 mongodump --uri="$MONGO_URI" --db=<dest_db> --collection=<coll> --gzip --archive=/var/backups/mongo/<dest_db>_<coll>_pre_p2.gz
```

Verification (mongosh, on the VM; output saved to `docs/archive/verify_<batch>.txt`):
```
// 1. counts: provenance-tagged dst rows must equal src count
db.getSiblingDB("email_automation").leads_enriched.countDocuments({})
db.getSiblingDB("torpedo").leads_enriched.countDocuments({"_mig.src":"email_automation.leads_enriched"})

// 2. _id type histogram, must match src vs dst; string ids are reported
db.leads_enriched.aggregate([{$group:{_id:{$type:"$_id"},n:{$sum:1}}}])

// 3. missing ids: page src ids 50k at a time, $in against dst, expect 0 missing

// 4. freshness after dual-write: max(updated_at) dst >= src
db.leads_enriched.aggregate([{$group:{_id:null,m:{$max:"$updated_at"}}}])

// 5. sample equality: 200 docs via $sample on src, fetch by _id on dst,
//    compare after removing _mig; mismatches must be 0

// 6. natural-key duplicates on merge destinations
db.accounts.aggregate([{$group:{_id:"$domain_normalized",n:{$sum:1}}},{$match:{n:{$gt:1}}},{$count:"dups"}])
db.outreach_bounce_suppression.aggregate([{$group:{_id:{$toLower:"$email"},n:{$sum:1}}},{$match:{n:{$gt:1}}},{$count:"dups"}])

// 7. provenance coverage on merges
db.accounts.aggregate([{$group:{_id:"$source",n:{$sum:1}}}])
```

Group checks: suppression: every email in `suppression_list` exists in `outreach_bounce_suppression` (not-found count 0). Accounts: unmatched sales_accounts count reported before insert. Mail: email_metadata count grows only by the diff report. Mailboxes: each `email` present once.

Rollback: `db.<coll>.deleteMany({"_mig.batch":"<batch>"})` for merges into existing collections; `drop()` for fresh destinations. Sources untouched and dual-write still on, so no data is lost.

## Phase 3: Cut reads over

| Step | Action |
|---|---|
| 1 | Re-grep the old `db.collection` pair across the repo and Celery task modules; every hit goes through `coll()`. Add one test per group asserting the route resolves to the expected `(db, coll)` and the code under test calls it (R5). |
| 2 | Flip `DB_ROUTE_<GROUP>=new`: writes go to new first and are mirrored back to old, so old stays warm for rollback. |
| 3 | Deploy, restart backend + sales worker + linkedin-beat. Smoke with read-only endpoints only. |
| 4 | Watch 7 days: error rate, `dualwrite_fail`, mail reanalysis jobs, outreach send counters, panel completion rate. |

Backup immediately before each flip:
```
nice -n 19 ionice -c3 mongodump --uri="$MONGO_URI" --db=<dest_db> --gzip --archive=/var/backups/mongo/<dest_db>_pre_cut_20261208.gz
```

Rollback: `DB_ROUTE_<GROUP>=old`, restart. Reads return to old, which has been mirrored; no data operation needed. If mirror failures are non-zero, the group stays in `dual`.

Special gates: suppression flips only between send windows with `outreach_kill_switch` on for the flip (off again after a read-only check). Mailboxes flip only while no mail sync is running.

## Phase 4: Drop with dated archive

| Step | Action |
|---|---|
| 1 | Stop the reverse mirror (route stays `new`), confirm 7 quiet days. |
| 2 | Final dump: `mongodump --uri="$MONGO_URI" --db=<old_db> --collection=<coll> --gzip --archive=/var/backups/mongo/<old_db>_<coll>_final_20261215.gz` |
| 3 | `db.<coll>.renameCollection("_archived_<coll>_20261215")` in the old db (metadata-only). |
| 4 | After 30 more days: copy the dumps off-VM, then `drop()` the `_archived_*` set. When a db has no live collections, drop the db. |
| 5 | Remove the old side of `ROUTES`, the `DB_ROUTE_*` flags and retired env vars (`MONGODB_DB`, `MONGODB_DATABASE`, `CRM_TARGET_DB`, `EMAIL_SOURCE_DB`, `LEAD_AGENTS_DB`). `updateMany({}, {$unset:{_mig:""}})` in batches. |

Rollback: `renameCollection` back to the original name (instant), or `mongorestore --nsFrom/--nsTo` from the final dump; then set the route flag to `old`.

# 4. Risk register

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | String vs ObjectId `_id` phantoms (4 project copies re-IDed 2026-10-03; main.py:4575; fallbacks in cpx_api and traffic) | Medium / high: duplicates or lost joins after a merge | `_id` histogram in Phase 2 pre-flight; moves preserve type; merges add `legacy_id`; skip-and-report on 24-hex collision; fallbacks removed only after zero string ids |
| R2 | email_sync defaults to campaign_platform while services write torpedo_gmail | High / medium: sync writes to the wrong db, mail pool goes stale | Phase 1 step 5; `coll("email_metadata")` only; startup log prints resolved `(db, coll)` per route; freshness check (verification 4) |
| R3 | `MONGO_DB_NAME` means different dbs per package (torpedo vs campaign_platform); MONGODB_DB, MONGODB_DATABASE | High / high | Env vars removed from db selection; the route table is the only selector; deploy checks env files for stale values (an empty MONGO_URI env file once crash-looped linkedin celery) |
| R4 | Shared 8GB VM memory during copies (swap-saturated v1+v2; the llama cache-ram collapse) | Medium / high: VM collapse, Mongo OOM | one collection at a time, batches of 500, sleeps, nice/ionice, off-peak, abort at swap > 60% or load > 3; no parallel mongodump |
| R5 | Tests never exercise db selection (fakes monkeypatch per-module helpers; `_fakemongo` does not pin a db name) | High / medium: silent mis-routing ships | `tests/test_routes.py` asserts the route table; `_fakemongo` records `(db, coll)` accessed, asserted in one test per migrated group; CI grep fails on `client["<retired_db>"]` and retired db literals |
| R6 | Unique-index creation on dirty data (suppression emails, account domains, mailbox emails) | High / medium: build fails or blocks writes | duplicate report first; dedupe with provenance; `partialFilterExpression` to skip nulls; create on the new collection only, never on a live source |
| R7 | No transactions: a crash mid-copy or mid-merge leaves partial state | Medium / medium | idempotent upsert copy by `_id`; `_mig.batch` makes every run undoable; merges are fill-only |
| R8 | Semantic over-merge (prospect treated as client, REJECT lead mailed, panel opt-out lost) | Medium / high | links not merges for leads, opportunities vs projects, panel suppression; no client/vendor inferred on import; owner review lists for unmatched sales_accounts and ops projects |
| R9 | Concurrent sessions editing the same tree and VM | High / medium | one group per deploy; explicit-path staging; verify the deployed commit on the VM; scripts require `--apply` |
| R10 | Live sends depend on moved collections (suppression, kill switch, v2 leads) | Low / very high: mail to suppressed or rejected leads | v2 leads/sends/campaigns never change db; only the suppression merge touches the send path, gated by kill switch and send windows |
| R11 | Import-time and class-held clients cache an old route after a flip | Medium / medium | workers restart with the backend; mode logged at import; a heartbeat in torpedo_settings.config compares route modes across processes and alerts on a mismatch |
| R12 | Disk space for dumps and archives on the VM | Low / medium | `df -h` check per phase; dumps copied off-VM before Phase 4 step 4; documented `--excludeCollection` for low-value logs |

# 5. Effort (file touches, derived from the inventory writer lists)

Counts are modules to edit, not call sites. The 85 one-off scripts are excluded except those run by cron or Celery.

| Phase | Work | Files |
|---|---|---|
| 1 | `db.py` route table + dual-write helper; `indexes.py` additions; env drift fixes (email_sync/router, leads/*, cold_outreach_router, outreach_unsubscribe) | about 20 |
| 1 | Route-table tests, `_fakemongo` db recording | about 4 |
| 2 | Migration runner + one config per group, verification script, pre-flight report | about 4 new files, no existing code touched |
| 3 | Leads and lead-gen (leads_enriched 40 users, leads_raw 35, overlapping) | about 50 |
| 3 | Accounts, contacts, RFQ, projects, clients/vendors mirrors | about 35 |
| 3 | Mail and mailboxes, review queues | about 20 |
| 3 | Marketing and web_tracking | about 16 |
| 3 | Settings, templates, users (routers, security, rbac), party_relationships | about 25 |
| 3 | Suppression | about 7 |
| 3 | Campaigns v1 retirement (delete or 410) | about 15 |
| 3 | Small dbs (gmail_archive 1, operations_db 1, marketing_db 1, prompt_management 1, survey_allocation 4, linkedin_db 3) | about 11 |
| 4 | Remove old route side, env vars, `_mig` unset script | about 10 |

Total about 190 file-touches, roughly 180 of them mechanical `coll()` swaps in Phase 3. Files that touch several groups count once per group, so unique files are closer to 140. Writers already deleted on the cleanup branch (about 30 files) come off the totals. Phase 3 groups 3, 4, 5, 7 each exceed 10 files, so the owner's go-ahead is needed before each starts.

## Defaults applied unless the owner objects

| Question | Default |
|---|---|
| Is any UI still calling v1 `/campaigns` routes? | Assume no: return 410 at Phase 3 |
| Downtime window? | None assumed; suppression flip uses the kill switch |
| Keep `_archived_*` for 30 days before drop? | Yes |
