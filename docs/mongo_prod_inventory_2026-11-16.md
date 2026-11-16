# Prod Mongo inventory (139.59.32.72), read-only, taken 2026-11-16 IST

Method: one mongosh script (estimatedDocumentCount, collStats storageSize, nindexes, newest `_id` ObjectId timestamp shown in IST, `_id` type histogram over a `$sample` of 200). "n/a" newest = `_id` is not an ObjectId (no timestamp). STALE = newest ObjectId older than 2026-09-17 (60 days). Storage is data only (excludes indexes). No writes performed.

Totals: data storage ~5,029 MB across 17 dbs (torpedo_gmail 3,186 MB; campaign_platform 447 MB; cint_research 412 MB; traffic_flow_db 375 MB; survey_allocation 339 MB; email_automation 211 MB). Mongo sizeOnDisk sum ~6.8 GiB. Disk `/`: 155G size, 36G used, 120G free.
Backup: /var/www/campaign_platform/backups/20261115T213001Z (latest symlink), full.archive.gz 1,385,875,451 bytes (~1.29 GiB), OK marker present, dump.log present. Taken 2026-11-16 03:00 IST.

Databases absent on prod (not in listDatabases): internal_db, gmail_archive, prompt_management, cpx_db, cint_db, leads, ai_enrichment.

## Retired-db verdicts

| Db | Exists | Collections / docs | Last write | Verdict |
|---|---|---|---|---|
| internal_db | no | 0 | n/a | EMPTY (absent) |
| gmail_archive | no | 0 | n/a | EMPTY (absent) |
| prompt_management | no | 0 | n/a | EMPTY (absent) |
| cpx_db, cint_db, leads, ai_enrichment | no | 0 | n/a | EMPTY (absent) |
| operations_db | yes | mystery_shopping_audits: 36 docs, 0.1 MB | 2026-11-10 23:43 | LIVE (tiny) |
| marketing_db | yes | websites: 3 docs | 2026-10-26 13:46 (21 d) | LIVE (tiny) |
| linkedin_db | yes | accounts 0, automation_jobs 0, opportunities 0 | n/a | EMPTY (droppable now) |
| survey_allocation | yes | allocation_log 0 (EMPTY); respondents 346 (0.2 MB) last 2026-02-03 = STALE; surveys 2,745,990 (247 MB) and survey_metrics 2,791,708 (92 MB) both written 2026-11-16 08:28 | LIVE, large | mixed: 1 empty, 1 stale, 2 large live |
| email_automation | yes | 185 collections, 1,073,816 docs, 211 MB | - | 77 EMPTY, 29 STALE, 61 LIVE, 18 unknown (string `_id`, no timestamp) |

Note: the plan's "~70 single-file collections" is roughly the 77 EMPTY ones in email_automation, but many of the 61 LIVE ones are named in the plan's merge groups.

## Overlap groups (docs, newest write IST)

Leads:
- email_automation.leads 339 (2026-11-12 14:15)
- email_automation.leads_raw 28,656 (2026-10-26 16:44)
- email_automation.leads_enriched 30,526 (2026-11-09 12:20)
- email_automation.email_leads 0 (EMPTY)
- email_automation.vendor_leads 2,848 (2026-11-15 16:04)
- crm_db.leads 13,238 (2026-10-26 16:44)
- torpedo.outreach_leads_v2 44,938 (2026-11-02 02:46)
- campaign_platform.email_leads: absent; campaign_platform.leads 193 (2026-04-13, STALE)

Accounts:
- crm_db.accounts 10,390 (2026-11-04 01:30)
- email_automation.sales_accounts 5,983 (2026-11-04 08:00)
- email_automation.clients 0 (EMPTY)
- email_automation.vendors 6 (2026-10-31 13:56)
- finance_db.customers 2,464 (2026-10-27 16:26)
- finance_db.vendors 36 (2026-08-01, STALE)
- not in plan: email_automation.accounts 85 (2026-10-19)

Projects / RFQs:
- email_automation.projects 503 (2026-11-06 17:12)
- email_automation.rfqs 0 (EMPTY, 0.5 MB storage)
- email_automation.rfq_candidates: absent
- email_automation.rfq_decisions 43 (2026-11-05 17:29)
- email_automation.rfq_review_queue 2 (2026-09-20, STALE)
- crm_db.projects 1,963 (2026-11-05 17:20)
- crm_db.service_projects 0 (EMPTY)
- crm_db.opportunities 1,960 (2026-11-05 17:20)
- crm_db.rfqs: absent
- torpedo_settings.projects: absent

Outreach v1 vs v2:
- email_automation campaigns, campaign_sends, campaign_recipients, campaign_send_queue, sends: all 0 (EMPTY). email_campaigns: absent. v1 outreach_* set: absent.
- email_automation.email_send_log 2,104 (2026-10-23 09:42) (not in plan)
- torpedo.outreach_campaigns_v2 5 (2026-04-09, STALE); outreach_campaigns_v2_backup_20261015 5 (same)
- torpedo.outreach_sends_v2 62,050 (2026-10-23 09:42, sends idle 24 d)

Mail:
- torpedo_gmail.email_metadata 392,803 (2026-11-16 08:22, 3,186 MB), plan assumed about 142k
- torpedo_gmail.mail_pool: absent (plan says canonical); mail_pool_stats_cache 1 doc; mail_pool_ai_state 1 doc in EA
- email_automation.emails 0, email_automation.email_metadata 0 (EMPTY)
- campaign_platform.email_metadata 0, campaign_platform.emails 0 (EMPTY)
- gmail_archive.emails: db absent
- email_automation.classified_emails 560,741 (2026-11-16 04:47, 37.5 MB); classified_gmail 6,939 (2026-11-16 04:37); mail_summaries 193,897 (2026-11-16 07:47)

Suppression:
- email_automation.suppression_list 40,797 (2026-10-25 16:24)
- torpedo.outreach_bounce_suppression 40,942 (2026-11-15 13:03)
- campaign_platform.panel_email_suppression 29,427 (2026-10-27 13:39)

Settings:
- torpedo_settings.app_settings 5 (string `_id`, no timestamp); torpedo_settings.config 2 (string)
- email_automation.app_settings 1 (string); scheduler_settings 1 (string); scheduler_state 2 (string) (all no timestamp)
- scheduler_config: absent from torpedo_settings and email_automation

Mailbox registries:
- torpedo_gmail.workspace_mailboxes 5 (2026-04-15 12:20, STALE)
- torpedo_gmail.mailboxes 0, torpedo_gmail.imap_accounts 0
- email_automation.mailboxes 0, imap_accounts 0, gmail_account_usage 0; gmail_accounts: absent
- campaign_platform.mailboxes 0 (EMPTY)
- torpedo.outreach_mailboxes 1 (2026-04-15 17:39, STALE)

Marketing (plan says crm_db is the canonical home, but no marketing collections exist in crm_db on prod):
- crm_db: content_items, gsc_*, inbox_items, review_queue_items, web_*, seo_*, cwv_results, whatsapp_templates: all absent
- email_automation.review_queue_items 1,331 (2026-11-16 08:17); web_events 79 (2026-10-25); web_visitors 11 (2026-10-25); web_audiences 22 (2026-11-16 06:30); seo_issues 166 (2026-10-25); seo_audits 15 (2026-11-15 22:00); web_sites 0; web_sessions 0; content_items 0; gsc_* 0; inbox_items 0; ads/ad_accounts 0; consents 0; cwv_results 0; whatsapp_templates 15 (2026-10-26)
- torpedo.seo_issues, seo_audits, cwv_results: absent

Review queues:
- email_automation.review_queue_items 1,331 (2026-11-16 08:17, LIVE)
- email_automation.ai_review_queue 15 (2026-08-02, STALE)
- torpedo_gmail.ai_review_queue 6 (2026-11-16 08:22, LIVE)
- campaign_platform.ai_review_queue 0 (EMPTY)
- email_automation.rfq_review_queue 2 (2026-09-20, STALE)
- crm_db.review_queue_items: absent

## Full table (all collections on prod)

Columns: db | collection | est_docs | storage_MB | indexes | newest_IST | _id types in 200-sample. "empty" = est_docs 0 (no sample taken).

| db | collection | est_docs | storage_MB | indexes | newest_IST | id_types |
|---|---|---:|---:|---:|---|---|
| ai_governance | ladder_jobs | 29583 | 1.7 | 1 | 2026-11-16 08:07 IST | ObjectId=200 |
| ai_governance | ladder_spend | 1 | 0.0 | 1 | n/a | string=1 |
| ai_governance | qwen_jobs | 1360 | 1.0 | 1 | 2026-10-26 22:31 IST | ObjectId=200 |
| campaign_platform | ai_review_queue | 0 | 0.0 | 3 | n/a | empty |
| campaign_platform | aliases | 0 | 0.0 | 4 | n/a | empty |
| campaign_platform | campaign_clay_configs | 0 | 0.0 | 3 | n/a | empty |
| campaign_platform | categorization_queue | 0 | 0.0 | 4 | n/a | empty |
| campaign_platform | cost_ledgers | 0 | 0.0 | 5 | n/a | empty |
| campaign_platform | cpx_callback_logs | 0 | 0.0 | 2 | n/a | empty |
| campaign_platform | email_metadata | 0 | 0.0 | 4 | n/a | empty |
| campaign_platform | emails | 0 | 0.0 | 14 | n/a | empty |
| campaign_platform | execution_logs | 0 | 0.0 | 5 | n/a | empty |
| campaign_platform | global_rate_limits | 1 | 0.0 | 1 | n/a | string=1 |
| campaign_platform | import_sessions | 0 | 0.0 | 4 | n/a | empty |
| campaign_platform | leads | 193 | 0.1 | 1 | 2026-04-13 14:30 IST | ObjectId=193 |
| campaign_platform | mailboxes | 0 | 0.0 | 3 | n/a | empty |
| campaign_platform | openai_quota | 186 | 0.4 | 3 | 2026-11-15 14:13 IST | ObjectId=186 |
| campaign_platform | openai_requests | 20218 | 1.0 | 3 | 2026-11-16 00:13 IST | ObjectId=200 |
| campaign_platform | panel_email_suppression | 29427 | 1.4 | 4 | 2026-10-27 13:39 IST | ObjectId=200 |
| campaign_platform | panel_invitation_log | 3480809 | 429.5 | 12 | 2026-11-15 11:36 IST | ObjectId=200 |
| campaign_platform | panel_job_state | 7 | 0.0 | 1 | n/a | string=7 |
| campaign_platform | panel_rewards | 0 | 0.0 | 3 | n/a | empty |
| campaign_platform | panel_sessions | 173 | 0.1 | 1 | 2026-11-09 16:57 IST | ObjectId=173 |
| campaign_platform | panelists | 224010 | 14.0 | 17 | 2026-10-31 08:20 IST | ObjectId=200 |
| campaign_platform | panelists_dedupe_backup | 2974 | 0.3 | 1 | 2026-05-31 16:07 IST | ObjectId=200 |
| campaign_platform | rate_limits | 0 | 0.0 | 2 | n/a | empty |
| campaign_platform | sales_dashboards | 5 | 0.0 | 1 | 2026-11-10 23:43 IST | ObjectId=5 |
| campaign_platform | sales_reports | 4 | 0.0 | 1 | 2026-10-22 02:48 IST | ObjectId=4 |
| campaign_platform | sources | 0 | 0.0 | 5 | n/a | empty |
| campaign_platform | sync_state | 0 | 0.0 | 2 | n/a | empty |
| campaign_platform | sync_states | 0 | 0.0 | 2 | n/a | empty |
| campaign_platform | url_parameters | 0 | 0.0 | 3 | n/a | empty |
| campaign_platform | workbook_cells | 0 | 0.0 | 5 | n/a | empty |
| campaign_platform | workbook_columns | 0 | 0.0 | 4 | n/a | empty |
| campaign_platform | workbook_rows | 0 | 0.0 | 4 | n/a | empty |
| campaign_platform | workbooks | 0 | 0.0 | 5 | n/a | empty |
| campaign_platform | workflow_tasks | 0 | 0.0 | 4 | n/a | empty |
| campaign_platform | workflows | 0 | 0.0 | 4 | n/a | empty |
| cint_research | cint_buyer_stats | 26 | 0.0 | 4 | 2026-11-16 05:25 IST | ObjectId=26 |
| cint_research | cint_entry_links | 50 | 0.0 | 4 | 2026-02-17 12:06 IST | ObjectId=50 |
| cint_research | cint_filters | 0 | 0.0 | 3 | n/a | empty |
| cint_research | cint_metrics | 8099 | 0.3 | 4 | 2026-11-16 05:25 IST | ObjectId=200 |
| cint_research | cint_respondent_outcomes | 0 | 0.0 | 8 | n/a | empty |
| cint_research | cint_settings | 0 | 0.0 | 4 | n/a | empty |
| cint_research | cint_subscriptions | 0 | 0.0 | 4 | n/a | empty |
| cint_research | cint_surveys | 94793 | 411.6 | 11 | 2026-11-16 08:30 IST | ObjectId=200 |
| cpx_research | cpx_filters | 0 | 0.0 | 2 | n/a | empty |
| cpx_research | cpx_surveys | 0 | 0.0 | 11 | n/a | empty |
| crm_db | _archived_records_20261003 | 1565 | 0.3 | 1 | 2026-10-03 11:28 IST | ObjectId=200 |
| crm_db | _archived_test_leads_20261026 | 24 | 0.0 | 1 | 2026-10-26 13:45 IST | ObjectId=24 |
| crm_db | accounts | 10390 | 2.0 | 4 | 2026-11-04 01:30 IST | ObjectId=200 |
| crm_db | activities | 28717 | 4.6 | 2 | 2026-11-16 08:00 IST | ObjectId=200 |
| crm_db | ai_decisions | 3012 | 0.5 | 1 | 2026-11-15 12:45 IST | ObjectId=200 |
| crm_db | audit_log | 1391 | 0.1 | 1 | 2026-11-16 08:17 IST | ObjectId=200 |
| crm_db | cint_buyer_mirror | 856 | 0.2 | 1 | 2026-11-14 12:45 IST | ObjectId=200 |
| crm_db | contacts | 4388 | 0.7 | 2 | 2026-11-04 22:10 IST | ObjectId=200 |
| crm_db | invoices | 297 | 0.1 | 1 | 2026-10-24 23:40 IST | ObjectId=200 |
| crm_db | leads | 13238 | 1.5 | 1 | 2026-10-26 16:44 IST | ObjectId=200 |
| crm_db | notifications | 6634 | 0.8 | 1 | 2026-11-15 23:43 IST | ObjectId=200 |
| crm_db | opportunities | 1960 | 1.8 | 3 | 2026-11-05 17:20 IST | ObjectId=200 |
| crm_db | panel_mirror | 45708 | 2.8 | 1 | 2026-06-08 02:20 IST | ObjectId=200 |
| crm_db | projects | 1963 | 1.0 | 1 | 2026-11-05 17:20 IST | ObjectId=200 |
| crm_db | service_projects | 0 | 0.0 | 3 | n/a | empty |
| crm_db | tasks | 3244 | 0.3 | 1 | 2026-11-15 23:43 IST | ObjectId=200 |
| crm_db | vendor_bids | 0 | 0.0 | 2 | n/a | empty |
| email_automation | _archived_purged_leads | 224 | 0.1 | 1 | 2026-10-24 18:26 IST | ObjectId=200 |
| email_automation | accounts | 85 | 0.0 | 1 | 2026-10-19 05:23 IST | ObjectId=85 |
| email_automation | ad_accounts | 0 | 0.0 | 3 | n/a | empty |
| email_automation | ad_campaigns | 0 | 0.0 | 3 | n/a | empty |
| email_automation | ad_groups | 0 | 0.0 | 3 | n/a | empty |
| email_automation | ad_metrics_daily | 0 | 0.0 | 4 | n/a | empty |
| email_automation | ads | 0 | 0.0 | 3 | n/a | empty |
| email_automation | agent_configurations | 3 | 0.0 | 3 | 2026-01-20 18:04 IST | ObjectId=3 |
| email_automation | agent_execution_logs | 20 | 0.0 | 1 | 2026-01-26 21:13 IST | ObjectId=20 |
| email_automation | agent_jobs | 0 | 0.0 | 4 | n/a | empty |
| email_automation | ai_discovered_companies | 0 | 0.0 | 6 | n/a | empty |
| email_automation | ai_review_queue | 15 | 0.0 | 6 | 2026-08-02 11:57 IST | ObjectId=15 |
| email_automation | ai_usage_logs | 0 | 0.0 | 6 | n/a | empty |
| email_automation | aliases | 0 | 0.0 | 4 | n/a | empty |
| email_automation | app_settings | 1 | 0.0 | 1 | n/a | string=1 |
| email_automation | attribution_results | 104 | 0.1 | 3 | 2026-10-25 11:04 IST | ObjectId=104 |
| email_automation | audiences | 12 | 0.0 | 2 | 2026-10-26 13:29 IST | ObjectId=12 |
| email_automation | audit_log | 0 | 0.0 | 5 | n/a | empty |
| email_automation | auto_classifier_stats | 1 | 0.0 | 1 | 2026-01-19 18:48 IST | ObjectId=1 |
| email_automation | auto_classify_agent_state | 1 | 0.0 | 1 | n/a | string=1 |
| email_automation | backfill_runs | 42 | 0.0 | 1 | 2026-11-16 03:45 IST | ObjectId=42 |
| email_automation | batch_enrichment_jobs | 0 | 0.0 | 5 | n/a | empty |
| email_automation | batch_enrichment_results | 0 | 0.0 | 4 | n/a | empty |
| email_automation | brand_voice | 3 | 0.0 | 2 | 2026-10-26 12:03 IST | ObjectId=3 |
| email_automation | campaign_decisions | 0 | 0.0 | 7 | n/a | empty |
| email_automation | campaign_recipients | 0 | 0.0 | 11 | n/a | empty |
| email_automation | campaign_send_queue | 0 | 0.0 | 3 | n/a | empty |
| email_automation | campaign_sends | 0 | 0.0 | 10 | n/a | empty |
| email_automation | campaigns | 0 | 0.0 | 3 | n/a | empty |
| email_automation | categorization_queue | 0 | 0.0 | 4 | n/a | empty |
| email_automation | classified_emails | 560741 | 37.5 | 1 | 2026-11-16 04:47 IST | ObjectId=200 |
| email_automation | classified_gmail | 6939 | 4.2 | 8 | 2026-11-16 04:37 IST | ObjectId=200 |
| email_automation | clients | 0 | 0.0 | 7 | n/a | empty |
| email_automation | company_cache | 0 | 0.0 | 7 | n/a | empty |
| email_automation | company_domains | 1355 | 0.1 | 1 | n/a | string=200 |
| email_automation | company_enrichment_cache | 0 | 0.0 | 2 | n/a | empty |
| email_automation | company_enrichment_logs | 1 | 0.0 | 1 | 2026-01-26 23:22 IST | ObjectId=1 |
| email_automation | company_type_usage | 10 | 0.0 | 1 | n/a | string=10 |
| email_automation | company_types | 13307 | 7.9 | 2 | n/a | string=200 |
| email_automation | consents | 0 | 0.0 | 3 | n/a | empty |
| email_automation | contact_identity_cleanup_log | 736 | 0.1 | 1 | 2026-08-29 22:16 IST | ObjectId=200 |
| email_automation | contacts | 5706 | 0.7 | 7 | 2026-11-05 08:00 IST | ObjectId=200 |
| email_automation | content_gaps | 17 | 0.0 | 2 | 2026-10-26 13:20 IST | ObjectId=17 |
| email_automation | content_items | 0 | 0.0 | 3 | n/a | empty |
| email_automation | crm_sync_logs | 200 | 0.0 | 1 | 2026-01-26 14:24 IST | ObjectId=200 |
| email_automation | cse_query_ledger | 458 | 0.1 | 2 | n/a | string=200 |
| email_automation | csv_column_mappings | 47 | 0.0 | 2 | 2026-06-15 23:57 IST | ObjectId=47 |
| email_automation | cwv_results | 0 | 0.0 | 3 | n/a | empty |
| email_automation | decision_candidates | 74 | 0.0 | 3 | 2026-11-10 22:30 IST | ObjectId=74 |
| email_automation | decision_outcomes | 0 | 0.0 | 3 | n/a | empty |
| email_automation | decisions | 62 | 0.1 | 4 | 2026-11-10 22:30 IST | ObjectId=62 |
| email_automation | dedup_index | 8626 | 2.2 | 6 | 2026-01-20 21:22 IST | ObjectId=200 |
| email_automation | dedup_logs | 0 | 0.0 | 4 | n/a | empty |
| email_automation | deliverability_checks | 21 | 0.0 | 1 | 2026-11-14 08:45 IST | ObjectId=21 |
| email_automation | discovery_cache | 0 | 0.0 | 4 | n/a | empty |
| email_automation | domain_health | 0 | 0.0 | 3 | n/a | empty |
| email_automation | email_address_structures | 51550 | 10.6 | 1 | n/a | string=200 |
| email_automation | email_audit_log | 0 | 0.0 | 4 | n/a | empty |
| email_automation | email_domain_structures | 7780 | 0.8 | 1 | n/a | string=200 |
| email_automation | email_extracted_leads | 0 | 0.0 | 5 | n/a | empty |
| email_automation | email_leads | 0 | 0.0 | 6 | n/a | empty |
| email_automation | email_metadata | 0 | 0.0 | 4 | n/a | empty |
| email_automation | email_patterns | 12243 | 2.1 | 8 | 2026-11-15 19:34 IST | ObjectId=200 |
| email_automation | email_send_log | 2104 | 0.3 | 4 | 2026-10-23 09:42 IST | ObjectId=200 |
| email_automation | email_templates | 0 | 0.0 | 3 | n/a | empty |
| email_automation | emails | 0 | 0.0 | 14 | n/a | empty |
| email_automation | enrichment_logs | 1000 | 0.0 | 1 | 2026-01-26 14:24 IST | ObjectId=200 |
| email_automation | experiments | 0 | 0.0 | 2 | n/a | empty |
| email_automation | extraction_backlog | 2634 | 29.4 | 1 | n/a | string=200 |
| email_automation | fabricated_domain_cleanup_log | 7 | 0.0 | 1 | 2026-08-29 22:17 IST | ObjectId=7 |
| email_automation | finance_decisions | 69 | 0.0 | 1 | 2026-11-14 09:30 IST | ObjectId=69 |
| email_automation | ga4_daily | 0 | 0.0 | 3 | n/a | empty |
| email_automation | gemini_quota | 358 | 0.0 | 3 | 2026-04-28 17:00 IST | ObjectId=200 |
| email_automation | gemini_requests | 0 | 0.0 | 3 | n/a | empty |
| email_automation | global_rate_limits | 1 | 0.0 | 1 | n/a | string=1 |
| email_automation | gmail_account_usage | 0 | 0.0 | 4 | n/a | empty |
| email_automation | google_cse_monthly_usage | 1 | 0.0 | 2 | 2026-09-28 15:04 IST | ObjectId=1 |
| email_automation | google_cse_usage | 51 | 0.0 | 3 | 2026-11-15 13:30 IST | ObjectId=51 |
| email_automation | gsc_pages_daily | 0 | 0.0 | 3 | n/a | empty |
| email_automation | gsc_queries_daily | 0 | 0.0 | 3 | n/a | empty |
| email_automation | gsc_sitemaps | 0 | 0.0 | 2 | n/a | empty |
| email_automation | gsc_url_index | 0 | 0.0 | 3 | n/a | empty |
| email_automation | hunter_lookups | 32 | 0.0 | 1 | n/a | string=32 |
| email_automation | hunter_usage | 3 | 0.0 | 1 | n/a | string=3 |
| email_automation | icp_configs | 3 | 0.0 | 3 | 2026-03-27 00:22 IST | ObjectId=3 |
| email_automation | icp_segments | 5 | 0.0 | 2 | 2026-03-31 14:50 IST | ObjectId=5 |
| email_automation | imap_accounts | 0 | 0.0 | 3 | n/a | empty |
| email_automation | inbox_items | 0 | 0.0 | 6 | n/a | empty |
| email_automation | ingestion_log | 29530 | 7.1 | 2 | 2026-11-16 02:15 IST | ObjectId=200 |
| email_automation | keyword_positions | 756 | 0.1 | 3 | 2026-11-16 07:00 IST | ObjectId=200 |
| email_automation | keywords | 36 | 0.0 | 2 | 2026-10-26 13:20 IST | ObjectId=36 |
| email_automation | kpi_definitions | 56 | 0.0 | 1 | 2026-10-27 00:30 IST | ObjectId=56 |
| email_automation | kpi_snapshots | 88 | 0.1 | 2 | 2026-11-16 00:30 IST | ObjectId=88 |
| email_automation | lead_ai_classification_logs | 0 | 0.0 | 4 | n/a | empty |
| email_automation | lead_enrichment_logs | 3350 | 0.4 | 1 | 2026-10-31 10:24 IST | ObjectId=200 |
| email_automation | lead_form_pending | 0 | 0.0 | 3 | n/a | empty |
| email_automation | lead_interests | 0 | 0.0 | 2 | n/a | empty |
| email_automation | leads | 339 | 0.2 | 18 | 2026-11-12 14:15 IST | ObjectId=200 |
| email_automation | leads_enriched | 30526 | 27.7 | 13 | 2026-11-09 12:20 IST | ObjectId=200 |
| email_automation | leads_raw | 28656 | 14.8 | 10 | 2026-10-26 16:44 IST | ObjectId=200 |
| email_automation | linkedin_activities | 0 | 0.0 | 5 | n/a | empty |
| email_automation | linkedin_connections | 0 | 0.0 | 8 | n/a | empty |
| email_automation | linkedin_messages | 0 | 0.0 | 7 | n/a | empty |
| email_automation | linkedin_sessions | 0 | 0.0 | 6 | n/a | empty |
| email_automation | linkedin_templates | 0 | 0.0 | 3 | n/a | empty |
| email_automation | lists | 0 | 0.0 | 3 | n/a | empty |
| email_automation | mail_ai_prefilter_audit | 48 | 0.0 | 1 | 2026-09-20 07:30 IST | ObjectId=48 |
| email_automation | mail_decisions | 5926 | 0.6 | 2 | 2026-11-16 08:17 IST | ObjectId=200 |
| email_automation | mail_followup_drafts | 6296 | 2.3 | 1 | 2026-09-02 01:51 IST | ObjectId=200 |
| email_automation | mail_pool_ai_state | 1 | 0.0 | 1 | n/a | string=1 |
| email_automation | mail_sender_analysis | 7023 | 8.9 | 1 | n/a | string=200 |
| email_automation | mail_summaries | 193897 | 37.1 | 1 | 2026-11-16 07:47 IST | ObjectId=200 |
| email_automation | mailboxes | 0 | 0.0 | 3 | n/a | empty |
| email_automation | marketing_eval_cases | 42 | 0.0 | 3 | 2026-10-25 18:33 IST | ObjectId=42 |
| email_automation | marketing_eval_runs | 3 | 0.0 | 1 | 2026-11-10 23:00 IST | ObjectId=3 |
| email_automation | marketing_kpi_snapshots | 0 | 0.0 | 3 | n/a | empty |
| email_automation | marketing_reports | 3 | 0.0 | 1 | 2026-11-09 09:00 IST | ObjectId=3 |
| email_automation | marketing_touches | 0 | 0.0 | 4 | n/a | empty |
| email_automation | migrations_log | 4 | 0.0 | 1 | 2026-10-03 16:58 IST | ObjectId=4 |
| email_automation | offline_conversion_uploads | 0 | 0.0 | 3 | n/a | empty |
| email_automation | openai_quota | 16 | 0.0 | 3 | 2026-04-30 08:16 IST | ObjectId=16 |
| email_automation | openai_requests | 189 | 0.1 | 3 | 2026-04-30 20:16 IST | ObjectId=189 |
| email_automation | openai_usage_logs | 0 | 0.0 | 4 | n/a | empty |
| email_automation | ops_decisions | 22 | 0.0 | 2 | 2026-11-15 18:00 IST | ObjectId=22 |
| email_automation | panel_vendors | 0 | 0.0 | 7 | n/a | empty |
| email_automation | party_relationships | 19 | 0.0 | 2 | 2026-10-26 23:40 IST | ObjectId=19 |
| email_automation | perplexity_usage_logs | 0 | 0.0 | 3 | n/a | empty |
| email_automation | person_fallback_cleanup_log | 3159 | 0.3 | 1 | 2026-08-29 22:09 IST | ObjectId=200 |
| email_automation | persons | 0 | 0.0 | 4 | n/a | empty |
| email_automation | placeholder_accounts_cleanup_log | 4 | 0.0 | 1 | 2026-08-29 22:09 IST | ObjectId=4 |
| email_automation | potential_client_leads | 53 | 0.0 | 1 | 2026-02-20 19:30 IST | ObjectId=53 |
| email_automation | projects | 503 | 0.3 | 7 | 2026-11-06 17:12 IST | ObjectId=200 |
| email_automation | projects_qualification_backup_20261017 | 2 | 0.0 | 1 | 2026-10-15 17:33 IST | ObjectId=2 |
| email_automation | projects_qualification_backup_20261021 | 2 | 0.0 | 1 | 2026-10-21 11:13 IST | ObjectId=2 |
| email_automation | projects_qualification_backup_20261022 | 16 | 0.0 | 1 | 2026-10-22 11:58 IST | ObjectId=16 |
| email_automation | projects_qualification_backup_auto | 3 | 0.0 | 1 | 2026-11-06 17:12 IST | ObjectId=3 |
| email_automation | projects_routing_backup_20261019 | 4 | 0.0 | 1 | 2026-10-17 10:17 IST | ObjectId=4 |
| email_automation | rate_limits | 0 | 0.0 | 2 | n/a | empty |
| email_automation | reengagement | 151 | 0.1 | 1 | n/a | string=151 |
| email_automation | reengagement_decisions | 483 | 0.1 | 1 | 2026-11-16 02:00 IST | ObjectId=200 |
| email_automation | reports | 2 | 0.0 | 1 | 2026-08-01 20:35 IST | ObjectId=2 |
| email_automation | review_queue_items | 1331 | 0.9 | 2 | 2026-11-16 08:17 IST | ObjectId=200 |
| email_automation | rfq_backfill_cleanup_log | 668 | 0.1 | 1 | 2026-08-29 21:54 IST | ObjectId=200 |
| email_automation | rfq_decisions | 43 | 0.1 | 2 | 2026-11-05 17:29 IST | ObjectId=43 |
| email_automation | rfq_review_queue | 2 | 0.0 | 3 | 2026-09-20 11:44 IST | ObjectId=2 |
| email_automation | rfqs | 0 | 0.5 | 4 | n/a | empty |
| email_automation | sales_accounts | 5983 | 0.5 | 6 | 2026-11-04 08:00 IST | ObjectId=200 |
| email_automation | scheduler_logs | 2033 | 0.1 | 1 | 2026-05-02 09:48 IST | ObjectId=200 |
| email_automation | scheduler_settings | 1 | 0.0 | 1 | n/a | string=1 |
| email_automation | scheduler_state | 2 | 0.0 | 1 | n/a | string=2 |
| email_automation | search_cache | 0 | 0.0 | 6 | n/a | empty |
| email_automation | search_cache_metrics | 1357 | 0.1 | 4 | 2026-05-02 09:30 IST | ObjectId=200 |
| email_automation | search_plans_cache | 0 | 0.0 | 3 | n/a | empty |
| email_automation | search_terms | 0 | 0.0 | 3 | n/a | empty |
| email_automation | sends | 0 | 0.0 | 2 | n/a | empty |
| email_automation | seo_audits | 15 | 0.1 | 2 | 2026-11-15 22:00 IST | ObjectId=15 |
| email_automation | seo_fix_plans | 3 | 0.0 | 2 | 2026-10-26 13:20 IST | ObjectId=3 |
| email_automation | seo_issues | 166 | 0.1 | 4 | 2026-10-25 12:23 IST | ObjectId=166 |
| email_automation | service_delivery_decisions | 21 | 0.0 | 1 | 2026-11-14 09:00 IST | ObjectId=21 |
| email_automation | skrapp_companies | 13230 | 2.4 | 1 | n/a | string=200 |
| email_automation | social_accounts | 0 | 0.0 | 3 | n/a | empty |
| email_automation | social_metrics_daily | 0 | 0.0 | 3 | n/a | empty |
| email_automation | social_posts | 0 | 0.0 | 3 | n/a | empty |
| email_automation | suppression_list | 40797 | 2.3 | 4 | 2026-10-25 16:24 IST | ObjectId=200 |
| email_automation | sync_state | 0 | 0.0 | 2 | n/a | empty |
| email_automation | sync_states | 0 | 0.0 | 2 | n/a | empty |
| email_automation | templates | 10 | 0.0 | 3 | 2026-02-13 18:45 IST | ObjectId=10 |
| email_automation | touchpoints | 14673 | 3.0 | 9 | 2026-10-25 11:04 IST | ObjectId=200 |
| email_automation | url_validation_cache | 0 | 0.0 | 4 | n/a | empty |
| email_automation | url_validation_logs | 0 | 0.0 | 3 | n/a | empty |
| email_automation | users | 1 | 0.0 | 4 | 2026-01-16 11:27 IST | ObjectId=1 |
| email_automation | vendor_leads | 2848 | 1.1 | 5 | 2026-11-15 16:04 IST | ObjectId=200 |
| email_automation | vendors | 6 | 0.0 | 3 | 2026-10-31 13:56 IST | ObjectId=6 |
| email_automation | warm_outreach_queue | 1210 | 0.2 | 1 | 2026-09-01 04:11 IST | ObjectId=200 |
| email_automation | web_audiences | 22 | 0.0 | 1 | 2026-11-16 06:30 IST | ObjectId=22 |
| email_automation | web_events | 79 | 0.0 | 6 | 2026-10-25 09:51 IST | ObjectId=79 |
| email_automation | web_search_jobs | 25 | 1.3 | 5 | 2026-09-29 13:12 IST | ObjectId=24 string=1 |
| email_automation | web_search_jobs_archive | 14 | 0.0 | 1 | 2026-06-16 00:01 IST | ObjectId=14 |
| email_automation | web_sessions | 0 | 0.0 | 4 | n/a | empty |
| email_automation | web_site_checks | 22 | 0.0 | 1 | 2026-11-16 08:00 IST | ObjectId=22 |
| email_automation | web_sites | 0 | 0.0 | 3 | n/a | empty |
| email_automation | web_visitors | 11 | 0.0 | 6 | 2026-10-25 09:51 IST | ObjectId=11 |
| email_automation | websearch_accounts_cleanup_log | 1368 | 0.1 | 1 | 2026-08-29 22:00 IST | ObjectId=200 |
| email_automation | whatsapp_optins | 0 | 0.0 | 3 | n/a | empty |
| email_automation | whatsapp_templates | 15 | 0.0 | 2 | 2026-10-26 13:16 IST | ObjectId=15 |
| finance_db | _removed_test_residue_20261002 | 1 | 0.0 | 1 | 2026-10-02 16:26 IST | ObjectId=1 |
| finance_db | bank_transactions | 0 | 0.0 | 3 | n/a | empty |
| finance_db | billing_vendors | 0 | 0.0 | 5 | n/a | empty |
| finance_db | bills | 0 | 0.0 | 3 | n/a | empty |
| finance_db | ca_packs | 3 | 0.0 | 1 | 2026-11-05 09:00 IST | ObjectId=3 |
| finance_db | contracts | 408 | 0.1 | 1 | 2026-10-24 22:28 IST | ObjectId=200 |
| finance_db | customers | 2464 | 0.8 | 5 | 2026-10-27 16:26 IST | ObjectId=200 |
| finance_db | estimates | 14643 | 5.9 | 2 | 2026-11-05 17:29 IST | ObjectId=200 |
| finance_db | expenses | 0 | 0.0 | 2 | n/a | empty |
| finance_db | invoice_fx | 137 | 0.0 | 1 | n/a | string=137 |
| finance_db | invoices | 290 | 0.1 | 11 | 2026-10-26 12:53 IST | ObjectId=200 |
| finance_db | journal | 554 | 0.1 | 2 | 2026-10-26 12:58 IST | ObjectId=200 |
| finance_db | payments_made | 0 | 0.0 | 2 | n/a | empty |
| finance_db | payments_received | 0 | 0.0 | 2 | n/a | empty |
| finance_db | purchase_orders | 0 | 0.0 | 2 | n/a | empty |
| finance_db | statements | 16 | 0.0 | 1 | 2026-11-01 09:00 IST | ObjectId=16 |
| finance_db | vendors | 36 | 0.0 | 1 | 2026-08-01 16:50 IST | ObjectId=36 |
| finance_db | work_orders | 408 | 0.2 | 1 | 2026-10-24 22:28 IST | ObjectId=200 |
| linkedin_db | accounts | 0 | 0.0 | 6 | n/a | empty |
| linkedin_db | automation_jobs | 0 | 0.0 | 6 | n/a | empty |
| linkedin_db | opportunities | 0 | 0.0 | 6 | n/a | empty |
| marketing_db | websites | 3 | 0.0 | 1 | 2026-10-26 13:46 IST | ObjectId=3 |
| operations_db | mystery_shopping_audits | 36 | 0.1 | 1 | 2026-11-10 23:43 IST | ObjectId=36 |
| qre_health_survey | module_counters | 1 | 0.0 | 1 | n/a | string=1 |
| qre_health_survey | quotas | 4 | 0.0 | 1 | n/a | string=4 |
| qre_health_survey | respondents | 21497 | 5.3 | 5 | n/a | string=200 |
| qre_health_survey | studies | 3 | 0.0 | 1 | n/a | string=3 |
| survey_allocation | allocation_log | 0 | 0.0 | 7 | n/a | empty |
| survey_allocation | respondents | 346 | 0.2 | 7 | 2026-02-03 17:01 IST | ObjectId=200 |
| survey_allocation | survey_metrics | 2791708 | 91.5 | 2 | 2026-11-16 08:28 IST | ObjectId=200 |
| survey_allocation | surveys | 2745990 | 246.9 | 8 | 2026-11-16 08:28 IST | ObjectId=200 |
| surveyfieldwork | badges | 0 | 0.0 | 2 | n/a | empty |
| surveyfieldwork | contactmessages | 0 | 0.0 | 7 | n/a | empty |
| surveyfieldwork | dnd | 0 | 0.0 | 7 | n/a | empty |
| surveyfieldwork | fraudflags | 0 | 0.0 | 3 | n/a | empty |
| surveyfieldwork | leaderboardsnapshots | 0 | 0.0 | 3 | n/a | empty |
| surveyfieldwork | referrals | 0 | 0.0 | 5 | n/a | empty |
| surveyfieldwork | rewards | 0 | 0.0 | 5 | n/a | empty |
| surveyfieldwork | suppliers | 0 | 0.0 | 4 | n/a | empty |
| surveyfieldwork | surveycompletions | 0 | 0.0 | 5 | n/a | empty |
| surveyfieldwork | transactions | 0 | 0.0 | 2 | n/a | empty |
| surveyfieldwork | userbadges | 0 | 0.0 | 2 | n/a | empty |
| surveyfieldwork | users | 0 | 0.0 | 14 | n/a | empty |
| surveyfieldwork | webhookevents | 0 | 0.0 | 3 | n/a | empty |
| torpedo | _archived_purged_leads | 132 | 0.0 | 1 | 2026-10-24 18:26 IST | ObjectId=132 |
| torpedo | app_settings | 0 | 0.0 | 1 | n/a | empty |
| torpedo | contact_icp_checks | 3265 | 0.3 | 1 | n/a | string=200 |
| torpedo | email_mx_cache | 0 | 0.0 | 3 | n/a | empty |
| torpedo | filter_settings | 0 | 0.0 | 1 | n/a | empty |
| torpedo | outreach_bounce_suppression | 40942 | 1.8 | 1 | 2026-11-15 13:03 IST | ObjectId=200 |
| torpedo | outreach_campaigns_v2 | 5 | 0.0 | 1 | 2026-04-09 17:11 IST | ObjectId=5 |
| torpedo | outreach_campaigns_v2_backup_20261015 | 5 | 0.0 | 1 | 2026-04-09 17:11 IST | ObjectId=5 |
| torpedo | outreach_daily_quota | 122 | 0.0 | 1 | n/a | string=122 |
| torpedo | outreach_health | 0 | 0.0 | 1 | n/a | empty |
| torpedo | outreach_kill_switch | 1 | 0.0 | 1 | n/a | string=1 |
| torpedo | outreach_leads_v2 | 44938 | 12.3 | 1 | 2026-11-02 02:46 IST | ObjectId=200 |
| torpedo | outreach_leads_v2_unauth_enroll_backup_20261019 | 817 | 0.1 | 1 | 2026-10-19 05:27 IST | ObjectId=200 |
| torpedo | outreach_mailboxes | 1 | 0.0 | 1 | 2026-04-15 17:39 IST | ObjectId=1 |
| torpedo | outreach_scan_state | 1 | 0.0 | 1 | n/a | string=1 |
| torpedo | outreach_sends_v2 | 62050 | 12.1 | 2 | 2026-10-23 09:42 IST | ObjectId=200 |
| torpedo | traffic | 494 | 0.2 | 8 | 2026-02-05 01:31 IST | ObjectId=200 |
| torpedo | vendors | 1 | 0.0 | 3 | 2026-02-04 19:03 IST | ObjectId=1 |
| torpedo_gmail | ai_review_queue | 6 | 0.0 | 3 | 2026-11-16 08:22 IST | ObjectId=6 |
| torpedo_gmail | aliases | 0 | 0.0 | 4 | n/a | empty |
| torpedo_gmail | categorization_queue | 0 | 0.0 | 4 | n/a | empty |
| torpedo_gmail | email_metadata | 392803 | 3185.7 | 32 | 2026-11-16 08:22 IST | ObjectId=200 |
| torpedo_gmail | email_sync_log | 0 | 0.0 | 5 | n/a | empty |
| torpedo_gmail | emails | 0 | 0.0 | 14 | n/a | empty |
| torpedo_gmail | gemini_classification_logs | 0 | 0.0 | 3 | n/a | empty |
| torpedo_gmail | global_rate_limits | 1 | 0.0 | 1 | n/a | string=1 |
| torpedo_gmail | gmail_config | 1 | 0.0 | 1 | n/a | string=1 |
| torpedo_gmail | imap_accounts | 0 | 0.0 | 3 | n/a | empty |
| torpedo_gmail | mail_pool_stats_cache | 1 | 0.0 | 1 | n/a | string=1 |
| torpedo_gmail | mailboxes | 0 | 0.0 | 3 | n/a | empty |
| torpedo_gmail | parallel_sync_progress | 0 | 0.0 | 4 | n/a | empty |
| torpedo_gmail | rate_limits | 0 | 0.0 | 2 | n/a | empty |
| torpedo_gmail | sync_state | 0 | 0.0 | 2 | n/a | empty |
| torpedo_gmail | sync_states | 0 | 0.0 | 2 | n/a | empty |
| torpedo_gmail | workspace_mailboxes | 5 | 0.0 | 3 | 2026-04-15 12:20 IST | ObjectId=5 |
| torpedo_settings | ai_governance_log | 0 | 0.0 | 2 | n/a | empty |
| torpedo_settings | ai_prompts | 0 | 0.0 | 3 | n/a | empty |
| torpedo_settings | app_settings | 5 | 0.0 | 1 | n/a | string=5 |
| torpedo_settings | approval_authorities | 0 | 0.0 | 2 | n/a | empty |
| torpedo_settings | approval_requests | 0 | 0.0 | 8 | n/a | empty |
| torpedo_settings | approval_rules | 0 | 0.0 | 5 | n/a | empty |
| torpedo_settings | config | 2 | 0.0 | 1 | n/a | string=2 |
| torpedo_settings | job_runs | 57 | 0.0 | 1 | n/a | string=57 |
| torpedo_settings | permissions | 0 | 0.0 | 2 | n/a | empty |
| torpedo_settings | roles | 9 | 0.0 | 2 | 2026-06-20 23:23 IST | ObjectId=9 |
| torpedo_settings | user_roles | 0 | 0.0 | 2 | n/a | empty |
| torpedo_settings | users | 0 | 0.0 | 2 | n/a | empty |
| traffic_flow_db | ad_pixel_fires | 1 | 0.0 | 3 | 2026-10-03 13:12 IST | ObjectId=1 |
| traffic_flow_db | client_reject_batches | 0 | 0.0 | 2 | n/a | empty |
| traffic_flow_db | client_rejects | 0 | 0.0 | 4 | n/a | empty |
| traffic_flow_db | cpx_callback_logs | 2168 | 0.4 | 5 | 2026-11-16 07:12 IST | ObjectId=200 |
| traffic_flow_db | cpx_entry_guards | 1270 | 0.4 | 4 | 2026-02-21 20:48 IST | ObjectId=200 |
| traffic_flow_db | cpx_postback_logs | 0 | 0.0 | 1 | n/a | empty |
| traffic_flow_db | inapp_events | 350 | 0.1 | 1 | 2026-10-18 23:46 IST | ObjectId=200 |
| traffic_flow_db | ip_intel | 0 | 0.0 | 2 | n/a | empty |
| traffic_flow_db | quality_validation | 21 | 0.0 | 1 | 2026-11-14 10:00 IST | ObjectId=21 |
| traffic_flow_db | routing_sessions | 71170 | 7.3 | 2 | 2026-11-13 16:03 IST | ObjectId=200 |
| traffic_flow_db | survey_callback_errors | 2123 | 0.3 | 2 | 2026-11-10 23:34 IST | ObjectId=200 |
| traffic_flow_db | survey_transactions | 2 | 0.0 | 5 | 2026-01-29 23:02 IST | ObjectId=2 |
| traffic_flow_db | url_parameters | 793175 | 366.1 | 25 | 2026-11-16 05:24 IST | ObjectId=200 |

## Per-db totals (#TOTAL rows)
| db | collections | est_docs | storage_MB |
|---|---:|---:|---:|
| ai_governance | 4 colls | 31132 | 2.9 |
| campaign_platform | 35 colls | 3758007 | 446.9 |
| cint_research | 8 colls | 102968 | 412.0 |
| cpx_research | 2 colls | 0 | 0.0 |
| crm_db | 17 colls | 123387 | 16.7 |
| email_automation | 185 colls | 1073816 | 211.4 |
| finance_db | 18 colls | 18960 | 7.3 |
| linkedin_db | 3 colls | 0 | 0.0 |
| marketing_db | 1 colls | 3 | 0.0 |
| operations_db | 1 colls | 36 | 0.1 |
| qre_health_survey | 4 colls | 21505 | 5.4 |
| survey_allocation | 4 colls | 5538044 | 338.7 |
| surveyfieldwork | 13 colls | 0 | 0.1 |
| torpedo | 18 colls | 152774 | 27.1 |
| torpedo_gmail | 17 colls | 392817 | 3185.9 |
| torpedo_settings | 12 colls | 73 | 0.2 |
| traffic_flow_db | 13 colls | 870280 | 374.7 |
