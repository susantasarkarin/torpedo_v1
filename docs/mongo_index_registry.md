# MongoDB index registry

Source of truth: `backend/indexes.py` (`INDEXES`). Runtime: `ensure_indexes()` is called once at startup from `startup_checks.audit_indexes_async()` (main.py). Default is read-only (`build=False`, logs missing/conflicting indexes). Creation: `AUTO_CREATE_INDEXES=true`, or `python indexes.py` in a maintenance window.

`ensure_indexes(db_names=None, client=None, build=True)` returns `{db: {created, existing, conflicts, failed, missing}}`. Conflicts are `OperationFailure` codes 85/86, or a name/key-pattern already present with other options. Text indexes are matched by name only (MongoDB reports `_fts`/`_ftsx` keys for them).

Unique rule: a field is `unique` in the registry only if its writers really enforce it. See the dedupe-key section.

## Per database

### `crm_db` (22 indexes in 7 collections)

| collection | index keys | options |
|---|---|---|
| `accounts` | `name` | - |
| `accounts` | `account_type` | - |
| `accounts` | `status` | - |
| `accounts` | `domain` | - |
| `accounts` | `root_domain` | - |
| `accounts` | `name_normalized` | - |
| `contacts` | `email` | - |
| `contacts` | `account_id` | - |
| `leads` | `email` | - |
| `leads` | `status` | - |
| `opportunities` | `account_id` | - |
| `opportunities` | `status` | - |
| `opportunities` | `stage` | - |
| `activities` | `contact_id` | - |
| `activities` | `account_id` | - |
| `activities` | `created_at` | - |
| `tasks` | `owner_id` | - |
| `tasks` | `status` | - |
| `tasks` | `due_date` | - |
| `ai_decisions` | `agent_name` | - |
| `ai_decisions` | `status` | - |
| `ai_decisions` | `linked_object_type 1, linked_object_id 1` | - |

### `torpedo` (27 indexes in 9 collections)

| collection | index keys | options |
|---|---|---|
| `outreach_leads_v2` | `email` | - |
| `outreach_leads_v2` | `email 1, campaign_id 1` | - |
| `outreach_leads_v2` | `lead_id` | - |
| `outreach_leads_v2` | `workflow_id 1, workflow_status 1, next_send_at 1` | - |
| `outreach_leads_v2` | `assigned_mailbox_id` | - |
| `outreach_leads_v2` | `next_send_at` | - |
| `outreach_campaigns_v2` | `campaign_id` | - |
| `outreach_campaigns_v2` | `status` | - |
| `outreach_templates_v2` | `template_id` | - |
| `outreach_templates_v2` | `company_brand 1, step_type 1` | - |
| `outreach_sends_v2` | `message_id` | unique=True |
| `outreach_sends_v2` | `campaign_id 1, lead_id 1` | - |
| `outreach_sends_v2` | `status 1, scheduled_at 1` | - |
| `outreach_send_logs` | `logged_at desc` | - |
| `outreach_send_logs` | `campaign_id 1, logged_at desc` | - |
| `outreach_send_logs` | `mailbox_used 1, logged_at desc` | - |
| `outreach_send_logs` | `status` | - |
| `outreach_error_logs` | `logged_at desc` | - |
| `outreach_error_logs` | `error_type` | - |
| `outreach_send_queue` | `campaign_id 1, lead_id 1, step_number 1` | unique=True, name=idempotency_unique_idx |
| `outreach_send_queue` | `scheduled_at 1, status 1` | - |
| `outreach_send_queue` | `campaign_id` | - |
| `outreach_send_queue` | `lead_id` | - |
| `outreach_mailboxes` | `mailbox_id` | unique=True |
| `outreach_mailboxes` | `email_address` | unique=True |
| `outreach_mailboxes` | `health_status 1, is_active 1` | - |
| `outreach_bounce_suppression` | `email` | unique=True |

### `finance_db` (24 indexes in 8 collections)

| collection | index keys | options |
|---|---|---|
| `invoices` | `invoice_number` | unique=True, sparse=True |
| `invoices` | `idempotency_key` | unique=True, sparse=True |
| `invoices` | `customer_id` | sparse=True |
| `invoices` | `customer_name` | - |
| `invoices` | `status` | - |
| `invoices` | `due_date` | - |
| `invoices` | `created_at` | - |
| `invoices` | `status 1, due_date 1` | - |
| `invoices` | `status 1, created_at desc` | name=invoices_status_date |
| `invoices` | `customer_id 1, status 1` | name=invoices_customer_status |
| `customers` | `name` | - |
| `customers` | `email` | sparse=True |
| `customers` | `operations_client_id` | sparse=True |
| `customers` | `createdAt` | - |
| `billing_vendors` | `name` | - |
| `billing_vendors` | `email` | sparse=True |
| `billing_vendors` | `status` | - |
| `billing_vendors` | `createdAt` | - |
| `bills` | `status 1, due_date 1` | name=bills_status_due |
| `bills` | `vendor_id 1, status 1` | name=bills_vendor_status |
| `expenses` | `approval_status 1, created_at desc` | name=expenses_approval_date |
| `payments_received` | `invoice_id 1, created_at desc` | name=payments_received_invoice_date |
| `payments_made` | `bill_id 1, created_at desc` | name=payments_made_bill_date |
| `purchase_orders` | `status 1, created_at desc` | name=po_status_date |

### `torpedo_gmail` (18 indexes in 4 collections)

| collection | index keys | options |
|---|---|---|
| `email_metadata` | `gmail_message_id` | unique=True |
| `email_metadata` | `mailbox_id` | - |
| `email_metadata` | `from_email` | - |
| `email_metadata` | `ai_category` | sparse=True |
| `email_metadata` | `ai_analysis` | - |
| `email_metadata` | `mailbox_id 1, timestamp desc` | - |
| `email_metadata` | `ai_category 1, ai_confidence desc` | - |
| `email_metadata` | `ai_category 1, mailbox_id 1` | - |
| `email_metadata` | `mailbox_id 1, ai_category 1, timestamp desc` | name=email_metadata_mailbox_category_time |
| `email_metadata` | `mailbox_id 1, gmail_message_id 1` | unique=True |
| `parallel_sync_progress` | `email` | unique=True |
| `parallel_sync_progress` | `status` | - |
| `parallel_sync_progress` | `status 1, updated_at desc` | - |
| `imap_accounts` | `email` | unique=True |
| `imap_accounts` | `is_active` | - |
| `email_sync_log` | `account_email` | - |
| `email_sync_log` | `started_at` | - |
| `email_sync_log` | `account_email 1, started_at desc` | - |

### `campaign_platform` (23 indexes in 4 collections)

| collection | index keys | options |
|---|---|---|
| `panelists` | `email` | unique=True |
| `panelists` | `country` | - |
| `panelists` | `status` | - |
| `panelists` | `double_opt_in_completed` | - |
| `panelists` | `status 1, created_at desc` | name=panelists_status_date |
| `panelists` | `status 1, last_invited_at 1` | name=panelists_status_last_invited |
| `panelists` | `double_opt_in_completed 1, last_login_invite_sent_at 1` | name=panelists_optin_last_login_invite |
| `panelists` | `sfw_profile_complete` | sparse=True |
| `panelists` | `sfw_last_login` | sparse=True |
| `panelists` | `sfw_country` | sparse=True |
| `panelists` | `invite_clicked_at` | sparse=True |
| `panelists` | `last_invited_at` | sparse=True |
| `panel_invitation_log` | `email` | - |
| `panel_invitation_log` | `email 1, sent_at desc` | name=invitation_log_email_sent |
| `panel_invitation_log` | `batch_id` | - |
| `panel_invitation_log` | `status` | - |
| `panel_invitation_log` | `type` | - |
| `panel_invitation_log` | `ses_message_id` | sparse=True |
| `panel_invitation_log` | `invite_token` | unique=True, sparse=True |
| `panel_email_suppression` | `email` | unique=True |
| `panel_email_suppression` | `reason` | - |
| `panel_rewards` | `panelist_id` | - |
| `panel_rewards` | `type 1, status 1` | name=rewards_type_status |

### `torpedo_settings` (0 indexes in 0 collections)

_No index definitions. See the backlog section for files that create indexes for this database._

### `email_automation` (235 indexes in 79 collections)

| collection | index keys | options |
|---|---|---|
| `users` | `username` | unique=True |
| `users` | `email` | sparse=True |
| `users` | `createdAt` | - |
| `contacts` | `email` | unique=True |
| `contacts` | `listId` | - |
| `contacts` | `firstName 1, lastName 1` | - |
| `contacts` | `tags` | - |
| `contacts` | `createdAt` | - |
| `contacts` | `email text, firstName text, lastName text, company text` | name=contacts_text_search |
| `rfq_review_queue` | `source_email_id` | unique=True |
| `rfq_review_queue` | `status` | - |
| `lists` | `name` | - |
| `lists` | `createdAt` | - |
| `templates` | `name` | - |
| `templates` | `createdAt` | - |
| `projects` | `name` | - |
| `projects` | `status` | - |
| `projects` | `createdAt` | - |
| `projects` | `projectStatus 1, createdAt desc` | name=projects_status_date |
| `projects` | `user_id 1, createdAt desc` | name=projects_user_date |
| `leads` | `email` | sparse=True |
| `leads` | `linkedin_url` | sparse=True |
| `leads` | `source` | - |
| `leads` | `classification_status` | - |
| `leads` | `seniority` | - |
| `leads` | `country` | - |
| `leads` | `createdAt` | - |
| `leads` | `email text, name text, company text, title text` | name=leads_text_search |
| `leads` | `engagement_score` | sparse=True |
| `leads` | `reengagement_eligible` | sparse=True |
| `leads` | `last_outreach_date` | sparse=True |
| `leads` | `linkedin_connection_status` | sparse=True |
| `leads` | `engagement_score desc, reengagement_eligible 1, last_outreach_date desc` | name=leads_reengagement_query |
| `leads` | `source 1, createdAt desc` | name=leads_source_date |
| `leads` | `classification_status 1, createdAt desc` | name=leads_classification_date |
| `leads` | `country 1, seniority 1, createdAt desc` | name=leads_country_seniority_date |
| `web_search_jobs` | `job_id` | unique=True |
| `web_search_jobs` | `status` | - |
| `web_search_jobs` | `created_at` | - |
| `web_search_jobs` | `status 1, created_at desc` | - |
| `panel_vendors` | `name` | - |
| `panel_vendors` | `email` | sparse=True |
| `panel_vendors` | `status` | - |
| `panel_vendors` | `createdAt` | - |
| `panel_vendors` | `vid` | unique=True, sparse=True |
| `panel_vendors` | `status 1, createdAt desc` | name=panel_vendors_status_date |
| `clients` | `name` | - |
| `clients` | `email` | sparse=True |
| `clients` | `status` | - |
| `clients` | `sales_account_id` | sparse=True |
| `clients` | `createdAt` | - |
| `clients` | `status 1, createdAt desc` | name=clients_status_date |
| `vendors` | `name` | - |
| `vendors` | `status` | - |
| `openai_usage_logs` | `timestamp` | - |
| `openai_usage_logs` | `source 1, timestamp desc` | - |
| `openai_usage_logs` | `model 1, timestamp desc` | - |
| `suppression_list` | `email` | unique=True |
| `suppression_list` | `reason` | - |
| `suppression_list` | `suppressed_at` | - |
| `campaign_sends` | `idempotency_key` | unique=True, sparse=True |
| `campaign_sends` | `campaign_id` | - |
| `campaign_sends` | `recipient_id` | - |
| `campaign_sends` | `sent_at` | - |
| `campaign_sends` | `status` | sparse=True |
| `campaign_sends` | `campaign_id 1, status 1, created_at desc` | name=campaign_sends_analytics |
| `email_audit_log` | `campaign_id 1, timestamp desc` | - |
| `email_audit_log` | `timestamp` | - |
| `email_audit_log` | `action` | - |
| `audit_log` | `entity_type 1, entity_id 1, timestamp desc` | - |
| `audit_log` | `timestamp` | - |
| `audit_log` | `user_id` | sparse=True |
| `audit_log` | `action` | - |
| `ai_review_queue` | `status 1, queued_at desc` | - |
| `ai_review_queue` | `entity_type` | - |
| `imap_accounts` | `email` | unique=True |
| `imap_accounts` | `is_active` | - |
| `email_leads` | `email_id` | unique=True |
| `email_leads` | `segment` | - |
| `email_leads` | `from_email` | - |
| `email_leads` | `received_at` | - |
| `campaign_recipients` | `campaign_id` | - |
| `campaign_recipients` | `lead_id` | - |
| `campaign_recipients` | `ab_variant` | sparse=True |
| `campaign_recipients` | `engagement_status` | sparse=True |
| `campaign_recipients` | `campaign_id 1, ab_variant 1` | name=campaign_recipients_ab_test |
| `campaign_recipients` | `campaign_id 1, engagement_status 1` | name=campaign_recipients_engagement |
| `linkedin_connections` | `lead_id` | - |
| `linkedin_connections` | `session_id` | sparse=True |
| `linkedin_connections` | `status` | sparse=True |
| `linkedin_connections` | `sent_at` | sparse=True |
| `linkedin_connections` | `accepted_at` | sparse=True |
| `linkedin_connections` | `lead_id 1, status 1` | name=linkedin_connections_by_lead_status |
| `linkedin_connections` | `session_id 1, sent_at desc` | name=linkedin_connections_session_timeline |
| `linkedin_sessions` | `session_id` | unique=True |
| `linkedin_sessions` | `email` | sparse=True |
| `linkedin_sessions` | `status` | sparse=True |
| `linkedin_sessions` | `login_date` | sparse=True |
| `linkedin_sessions` | `last_active` | sparse=True |
| `linkedin_messages` | `lead_id` | - |
| `linkedin_messages` | `connection_id` | sparse=True |
| `linkedin_messages` | `sent_at` | - |
| `linkedin_messages` | `read_at` | sparse=True |
| `linkedin_messages` | `replied_at` | sparse=True |
| `linkedin_messages` | `lead_id 1, sent_at desc` | name=linkedin_messages_by_lead_timeline |
| `linkedin_activities` | `session_id` | - |
| `linkedin_activities` | `date` | - |
| `linkedin_activities` | `date 1, session_id 1` | name=linkedin_activities_daily_summary |
| `linkedin_activities` | `session_id desc, date desc` | name=linkedin_activities_session_timeline |
| `linkedin_templates` | `name` | sparse=True |
| `linkedin_templates` | `created_at` | sparse=True |
| `domain_health` | `domain` | unique=True |
| `domain_health` | `last_checked` | sparse=True |
| `gmail_account_usage` | `account_id` | unique=True, sparse=True |
| `gmail_account_usage` | `last_sync` | sparse=True |
| `gmail_account_usage` | `account_id 1, last_sync desc` | name=gmail_account_usage_sync_tracking |
| `sales_accounts` | `account_name` | - |
| `sales_accounts` | `company` | - |
| `sales_accounts` | `status` | - |
| `sales_accounts` | `createdAt` | - |
| `sales_accounts` | `status 1, createdAt desc` | name=sales_accounts_status_date |
| `search_cache` | `query_hash` | unique=True |
| `search_cache` | `created_at` | - |
| `search_cache` | `provider` | - |
| `search_cache` | `job_title 1, industry 1, location 1` | name=search_cache_components |
| `search_cache` | `expires_at` | expireAfterSeconds=0 |
| `search_cache_metrics` | `date` | - |
| `search_cache_metrics` | `date 1, hour 1` | - |
| `dedup_index` | `linkedin_url_hash` | unique=True, sparse=True |
| `dedup_index` | `email_hash` | sparse=True |
| `dedup_index` | `name_company_hash` | sparse=True |
| `dedup_index` | `lead_id` | - |
| `dedup_index` | `created_at` | - |
| `dedup_logs` | `rejected_at` | - |
| `dedup_logs` | `reason` | - |
| `dedup_logs` | `source` | - |
| `rfqs` | `status 1, created_at desc` | name=rfqs_status_date |
| `leads_raw` | `email` | unique=True, sparse=True |
| `leads_raw` | `linkedin_url` | unique=True, sparse=True |
| `web_sites` | `domain` | unique=True |
| `web_sites` | `bu` | - |
| `web_visitors` | `visitor_id` | unique=True |
| `web_visitors` | `contact_id` | sparse=True |
| `web_visitors` | `lead_id` | sparse=True |
| `web_visitors` | `last_seen` | - |
| `web_sessions` | `session_id` | unique=True |
| `web_sessions` | `visitor_id` | - |
| `web_sessions` | `started_at 1, bu 1` | - |
| `web_events` | `visitor_id` | - |
| `web_events` | `at 1, bu 1` | - |
| `web_events` | `type` | - |
| `consents` | `visitor_id` | - |
| `consents` | `at` | - |
| `touchpoints` | `tp_key` | unique=True |
| `touchpoints` | `lead_id 1, at 1` | - |
| `touchpoints` | `contact_id` | sparse=True |
| `touchpoints` | `visitor_id` | sparse=True |
| `touchpoints` | `click_ids.gclid` | sparse=True |
| `touchpoints` | `click_ids.fbclid` | sparse=True |
| `touchpoints` | `click_ids.li_fat_id` | sparse=True |
| `touchpoints` | `campaign_id` | sparse=True |
| `attribution_results` | `lead_id 1, conversion_id 1, model 1` | unique=True |
| `attribution_results` | `bu 1, model 1, event 1` | - |
| `ga4_daily` | `property_id 1, date 1, dims_key 1` | unique=True |
| `ga4_daily` | `date 1, bu 1` | - |
| `gsc_queries_daily` | `site 1, date 1, query 1, page 1, country 1, device 1` | unique=True |
| `gsc_queries_daily` | `date 1, bu 1` | - |
| `gsc_pages_daily` | `site 1, date 1, page 1` | unique=True |
| `gsc_pages_daily` | `date 1, bu 1` | - |
| `gsc_sitemaps` | `site 1, path 1` | unique=True |
| `gsc_url_index` | `url` | unique=True |
| `gsc_url_index` | `site` | - |
| `seo_audits` | `site 1, started_at desc` | - |
| `seo_issues` | `key` | unique=True |
| `seo_issues` | `site 1, status 1, severity 1` | - |
| `seo_issues` | `audit_id` | - |
| `cwv_results` | `url 1, strategy 1, date 1` | - |
| `cwv_results` | `date 1, bu 1` | - |
| `keywords` | `bu 1, keyword 1` | unique=True |
| `keyword_positions` | `keyword_id 1, date 1` | unique=True |
| `keyword_positions` | `date 1, bu 1` | - |
| `content_gaps` | `bu 1, status 1` | - |
| `seo_fix_plans` | `site` | unique=True |
| `ad_accounts` | `platform 1, account_id 1` | unique=True |
| `ad_accounts` | `bu` | - |
| `ad_campaigns` | `platform 1, campaign_id 1` | unique=True |
| `ad_campaigns` | `bu` | - |
| `ad_groups` | `platform 1, group_id 1` | unique=True |
| `ad_groups` | `campaign_id` | - |
| `ads` | `platform 1, ad_id 1` | unique=True |
| `ads` | `campaign_id` | - |
| `ad_metrics_daily` | `platform 1, level 1, entity_id 1, date 1` | unique=True |
| `ad_metrics_daily` | `campaign_id` | - |
| `ad_metrics_daily` | `date 1, bu 1` | - |
| `search_terms` | `campaign_id 1, term 1, date 1` | unique=True |
| `search_terms` | `date 1, bu 1` | - |
| `offline_conversion_uploads` | `platform 1, lead_id 1, event 1` | unique=True |
| `offline_conversion_uploads` | `status` | - |
| `audiences` | `bu 1, platform 1, name 1` | unique=True |
| `social_accounts` | `platform 1, account_id 1` | unique=True |
| `social_accounts` | `bu` | - |
| `social_posts` | `platform 1, post_id 1` | unique=True, sparse=True |
| `social_posts` | `content_item_id` | - |
| `social_metrics_daily` | `platform 1, entity_id 1, date 1` | unique=True |
| `social_metrics_daily` | `date 1, bu 1` | - |
| `inbox_items` | `channel 1, external_id 1` | unique=True |
| `inbox_items` | `status 1, due_at 1` | - |
| `inbox_items` | `phone_hash` | sparse=True |
| `inbox_items` | `contact_id` | sparse=True |
| `inbox_items` | `lead_id` | sparse=True |
| `whatsapp_optins` | `phone_hash` | - |
| `whatsapp_optins` | `contact_id` | sparse=True |
| `marketing_touches` | `lead_id 1, at desc` | - |
| `marketing_touches` | `phone_hash` | sparse=True |
| `marketing_touches` | `email` | sparse=True |
| `lead_form_pending` | `leadgen_id` | unique=True |
| `lead_form_pending` | `status` | - |
| `whatsapp_templates` | `bu 1, name 1, language 1` | unique=True |
| `content_items` | `bu 1, channel 1, status 1` | - |
| `content_items` | `scheduled_for` | sparse=True |
| `brand_voice` | `bu` | unique=True |
| `experiments` | `bu 1, status 1` | - |
| `decision_candidates` | `decision_type 1, status 1` | - |
| `decision_candidates` | `entity_key 1, created_at desc` | - |
| `decisions` | `decision_type 1, status 1` | - |
| `decisions` | `entity_key 1, created_at desc` | - |
| `decisions` | `candidate_id` | - |
| `decision_outcomes` | `decision_id` | unique=True |
| `decision_outcomes` | `decision_type 1, measured_at desc` | - |
| `marketing_eval_cases` | `key` | unique=True |
| `marketing_eval_cases` | `decision_type` | - |
| `marketing_eval_runs` | `at desc` | - |
| `marketing_reports` | `week` | unique=True |
| `marketing_kpi_snapshots` | `kpi 1, date 1, bu 1` | unique=True |
| `marketing_kpi_snapshots` | `date 1, bu 1` | - |

### `cint_research` (47 indexes in 12 collections)

| collection | index keys | options |
|---|---|---|
| `cint_surveys` | `survey_id 1` | unique=True |
| `cint_surveys` | `is_active 1` | - |
| `cint_surveys` | `is_live 1` | - |
| `cint_surveys` | `country_language 1` | - |
| `cint_surveys` | `buyer_id 1` | - |
| `cint_surveys` | `message_reason 1` | - |
| `cint_surveys` | `received_at desc` | - |
| `cint_surveys` | `total_remaining 1` | - |
| `cint_surveys` | `survey_id 1, is_active 1` | - |
| `cint_entry_links` | `survey_id 1` | unique=True |
| `cint_entry_links` | `created_at desc` | - |
| `cint_entry_links` | `updated_at desc` | - |
| `cint_settings` | `user_id 1` | - |
| `cint_settings` | `supplier_code 1` | - |
| `cint_settings` | `is_active 1` | - |
| `cint_filters` | `user_id 1` | - |
| `cint_filters` | `name 1` | - |
| `cint_metrics` | `survey_id 1` | unique=True |
| `cint_metrics` | `last_updated desc` | - |
| `cint_metrics` | `last_allocation desc` | - |
| `cint_subscriptions` | `supplier_code 1` | unique=True |
| `cint_subscriptions` | `status 1` | - |
| `cint_subscriptions` | `last_webhook_received_at desc` | - |
| `cint_buyer_stats` | `buyer_name 1` | unique=True |
| `cint_buyer_stats` | `conversion_rate desc` | - |
| `cint_buyer_stats` | `last_updated desc` | - |
| `cint_respondent_outcomes` | `respondent_id 1` | - |
| `cint_respondent_outcomes` | `session_id 1` | unique=True |
| `cint_respondent_outcomes` | `survey_id 1` | - |
| `cint_respondent_outcomes` | `marketplace_status 1` | - |
| `cint_respondent_outcomes` | `client_status 1` | - |
| `cint_respondent_outcomes` | `received_at desc` | - |
| `cint_respondent_outcomes` | `entry_date desc, last_date desc` | - |
| `respondents` | `provider 1` | - |
| `respondents` | `supplier_code 1` | - |
| `surveys` | `provider 1` | - |
| `surveys` | `provider 1, external_id 1` | - |
| `surveys` | `provider 1, is_active 1` | - |
| `survey_metrics` | `survey_id 1` | - |
| `survey_metrics` | `provider 1` | - |
| `survey_metrics` | `last_updated desc` | - |
| `allocation_log` | `respondent_id 1` | - |
| `allocation_log` | `survey_id 1` | - |
| `allocation_log` | `provider 1` | - |
| `allocation_log` | `timestamp desc` | - |
| `allocation_log` | `status 1` | - |
| `allocation_log` | `timestamp 1` | expireAfterSeconds=2592000 |

### `cpx_research` (14 indexes in 3 collections)

| collection | index keys | options |
|---|---|---|
| `cpx_surveys` | `survey_id` | unique=True |
| `cpx_surveys` | `status` | - |
| `cpx_surveys` | `loi` | - |
| `cpx_surveys` | `cpi` | - |
| `cpx_surveys` | `last_updated` | - |
| `cpx_surveys` | `loi 1, cpi desc` | - |
| `cpx_surveys` | `payout` | - |
| `cpx_surveys` | `country` | - |
| `cpx_surveys` | `category` | - |
| `cpx_surveys` | `country 1, last_updated desc` | - |
| `cpx_filters` | `name` | - |
| `cpx_diagnostic_logs` | `timestamp 1` | expireAfterSeconds=604800 |
| `cpx_diagnostic_logs` | `country_code` | - |
| `cpx_diagnostic_logs` | `outcome` | - |

### `traffic_flow_db` (11 indexes in 2 collections)

| collection | index keys | options |
|---|---|---|
| `url_parameters` | `vendorId` | - |
| `url_parameters` | `status` | - |
| `url_parameters` | `createdAt` | - |
| `url_parameters` | `callback_key` | unique=True, sparse=True |
| `url_parameters` | `cint_hashed_pid` | - |
| `url_parameters` | `createdAt desc, status 1` | - |
| `url_parameters` | `vendorId 1, status 1, createdAt desc` | name=url_params_vendor_status_date |
| `cpx_callback_logs` | `timestamp` | - |
| `cpx_callback_logs` | `transaction_id` | - |
| `cpx_callback_logs` | `status` | - |
| `cpx_callback_logs` | `timestamp desc` | - |

### `ai_governance` (2 indexes in 2 collections)

| collection | index keys | options |
|---|---|---|
| `gemini_daily_usage` | `date 1` | unique=True |
| `email_classification_guard` | `email_id 1` | unique=True, name=unique_email_classification |

Total registry entries: 423 across 11 databases.

## Dedupe keys (decisions)

| registry entry | asked for | writers actually write | decision |
|---|---|---|---|
| `crm_db.accounts` | unique `domain_normalized` | no `domain_normalized` field anywhere; crm writers use `domain` | non-unique `domain` |
| `crm_db.contacts` | unique `email_lower` | no `email_lower` field; `crm_service` writes `email` lowercased, other writers do not | non-unique `email` |
| `torpedo.outreach_leads_v2` | unique `email_lower` | no `email_lower`; `canonical_ingestion` writes `email` lowercased and enrolls one doc per (email, campaign_id) | non-unique `email` plus compound (email, campaign_id). A unique `email` is contradicted by canonical_ingestion. See conflicts. |
| `torpedo_gmail.email_metadata` | unique `message_id` | no `message_id`; writers use `gmail_message_id`, and `gmail_service`/`gmail_workspace_service` create unique (mailbox_id, gmail_message_id) | unique compound (mailbox_id, gmail_message_id), plus the pre-existing unique single `gmail_message_id` from HEAD (flagged below) |

## Conflicts

Same collection and keys with different options (or the same name with different keys) in a file still outside the registry. Matched by collection name, so the database is inferred where the file does not name it. `background=True` is ignored in the comparison.

| file:line | collection | writer says | registry says | effect |
|---|---|---|---|---|
| `outreach_engine/workflow_engine.py:72-73`, `outreach_engine/migration.py:431-432` | `torpedo.outreach_leads_v2` | unique `lead_id`, unique `email` | non-unique `lead_id`, `email` | Whichever runs first owns the `email_1`/`lead_id_1` name. The other fails with IndexOptionsConflict, swallowed by its try. canonical_ingestion needs non-unique email (one doc per campaign), so the workflow unique is the suspect. Decide before enforcing. |
| `leads/email_processor.py:56` | `email_automation.leads_raw` | non-unique `email` | unique+sparse `email` | Conflict. Keep the unique (canonical_ingestion relies on it). |
| `leads/search_cache.py:59` | `email_automation.search_cache` | same keys, default name | name `search_cache_components` | Same keys under two names is rejected by MongoDB. Pick one name. |
| `app/services/survey_allocation_service.py:95` | `cint_research.survey_metrics` (inferred) | unique `survey_id` | non-unique `survey_id` | Registry follows database_setup_cint.py. Decide which is intended. |
| `main.py:3969` | `email_automation.leads` (inferred) | unique+sparse `email` | sparse `email` | Unique is not in the registry. Add it only after checking for duplicate emails in the collection. |
| `routers/panel_admin.py:61` | `campaign_platform.panelists` | non-unique `email` | unique `email` | Whichever runs first owns `email_1`. The unique is the intended one (panel signup). |
| (registry, from HEAD) `torpedo_gmail.email_metadata` | - | writers create unique (mailbox_id, gmail_message_id) | also unique single `gmail_message_id` | Single-field unique blocks the same Gmail message in two mailboxes. Owner decision: drop it. Kept here because HEAD had it. |

## Cleanup backlog: files that still call create_index

These files still create indexes themselves. They are not removed in this change. Moving each into `INDEXES` is the cleanup. Counts are `create_index` call sites (519 total, outside tests and indexes.py).

- `ai_governance/governance_checks.py` (2)
- `app/services/cpx_service.py` (9)
- `app/services/gmail_service.py` (9)
- `app/services/gmail_workspace_service.py` (6)
- `app/services/mail_categorizer.py` (2)
- `app/services/outreach/email_validator.py` (2)
- `app/services/survey_allocation_service.py` (12)
- `app/services/traffic_service.py` (1)
- `app/services/yield_init.py` (1)
- `audit.py` (4)
- `automation/decision_logger.py` (6)
- `automation/reply_engine.py` (3)
- `backfill/steps.py` (3)
- `campaigns/models.py` (13)
- `campaigns/suppression.py` (3)
- `database_setup_cint.py` (47)
- `email_sync/alias_resolver.py` (2)
- `email_sync/department_router.py` (3)
- `email_sync/historical_classifier.py` (4)
- `email_sync/llm_email_classifier.py` (5)
- `email_sync/orchestrator.py` (1)
- `email_sync/rate_limiter.py` (1)
- `email_sync/state_machine.py` (1)
- `email_sync/storage.py` (14)
- `leads/agent_router.py` (5)
- `leads/ai_classifier.py` (1)
- `leads/batch_enrichment.py` (7)
- `leads/canonical_ingestion.py` (2)
- `leads/clay_indexes.py` (37)
- `leads/company_cache.py` (5)
- `leads/company_fit.py` (2)
- `leads/deduplication.py` (7)
- `leads/email_pattern_system.py` (6)
- `leads/email_processor.py` (9)
- `leads/google_rate_limit.py` (3)
- `leads/icp_config.py` (2)
- `leads/imap_leads_service.py` (4)
- `leads/query_generator.py` (2)
- `leads/review_queue.py` (3)
- `leads/router.py` (10)
- `leads/router_shared.py` (8)
- `leads/search_cache.py` (7)
- `leads/service.py` (17)
- `leads/url_validator.py` (5)
- `linkedin_automation/database.py` (11)
- `linkedin_automation/service.py` (5)
- `main.py` (11)
- `marketing/schema.py` (1)
- `mcp/action_router.py` (5)
- `messaging/log.py` (3)
- `messaging/suppression.py` (3)
- `migrations/001_init_crm_collections.py` (19)
- `migrations/005_create_indexes.py` (38)
- `migrations/006_add_ad_tracking_fields.py` (5)
- `migrations/007_sfw_quality_indexes.py` (1)
- `migrations/008_client_rejects.py` (1)
- `migrations/009_survey_routing.py` (1)
- `outreach_engine/logging_service.py` (6)
- `outreach_engine/mailbox_manager.py` (3)
- `outreach_engine/migration.py` (19)
- `outreach_engine/reply_engine/models.py` (1)
- `outreach_engine/scheduler.py` (4)
- `outreach_engine/sending_engine.py` (4)
- `outreach_engine/workflow_engine.py` (7)
- `rbac/service.py` (5)
- `routers/classified_gmail.py` (6)
- `routers/company_cache.py` (6)
- `routers/email_patterns.py` (3)
- `routers/panel.py` (2)
- `routers/panel_admin.py` (2)
- `routers/settings.py` (2)
- `routers/vendor_leads.py` (4)
- `sales/schemas.py` (6)
- `scripts/add_soft_delete_fields.py` (1)
- `scripts/create_indexes.py` (2)
- `scripts/create_performance_indexes.py` (2)
- `scripts/dedupe_enriched.py` (1)
- `scripts/dedupe_panelists.py` (1)
- `scripts/migrate_suppressions.py` (1)
- `scripts/migrate_survey_click_tracking.py` (6)
- `scripts/shadow_replay.py` (1)
- `services/panel_bounce_handler.py` (13)
- `workflows/approval_engine.py` (11)

Coverage note: the scan resolves `db['x']`, `db.x` and simple variable assignments. `self.x` receivers and computed names are not resolved, so the conflict list is a lower bound.

## Startup check

`startup_checks._audit_indexes` runs `ensure_indexes(build=AUTO_CREATE_INDEXES)` once, then the older subset audit. `_ensure_messaging_indexes` also runs (messaging/suppression.py, messaging/log.py) and is outside the registry.

