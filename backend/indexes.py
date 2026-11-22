"""
DATABASE INDEX REGISTRY
=======================

Every index the backend expects lives in ONE registry, ``INDEXES``, keyed by
database name and then by collection. Each entry is ``(keys, options)``:

    keys     "field"                       ascending single field
             [("a", 1), ("b", -1)]         compound; 1 / -1 / "text" / "hashed"
    options  kwargs for pymongo create_index: unique, sparse, name,
             expireAfterSeconds, partialFilterExpression ...

The registry is documented per database and collection, with the files that
still create indexes themselves, in docs/mongo_index_registry.md.

Entry points (all go through the shared handles in backend/db.py):

    ensure_indexes(db_names=None, client=None, build=True) -> dict
        Idempotent. Reports, per database, how many indexes were created,
        already existed, conflicted (same keys or name with different options,
        which MongoDB rejects with IndexOptionsConflict / IndexKeySpecsConflict)
        or failed. Never raises for a single bad index.
        build=False is a read-only comparison: nothing is created, and the
        indexes that are absent are listed under "missing".

    setup_indexes(db_manager=None)      alias: ensure_indexes(build=True)
    create_index_safe(collection, keys, **kwargs)
                                        helper for one-off callers
    drop_all_indexes(db_manager=None, confirm=False)

Run as a maintenance task (builds everything, logs a summary):
    python indexes.py
"""

import logging

from pymongo.errors import OperationFailure, PyMongoError

logger = logging.getLogger(__name__)

# MongoDB error codes for "an index with this name/keys exists with other options".
_CONFLICT_CODES = {85, 86}  # 85 IndexOptionsConflict, 86 IndexKeySpecsConflict

INDEXES = {
    "crm_db": {
        # migrations/001_init_crm_collections.py + crm_service / mail_pipeline lookups.
        # Non-unique throughout: 001 defines no unique constraints, and the
        # writers do not guarantee uniqueness on these fields.
        "accounts": [
            ("name", {}),
            ("account_type", {}),
            ("status", {}),
            ("domain", {}),            # written by crm writers; there is no domain_normalized field
            ("root_domain", {}),
            ("name_normalized", {}),   # crm_service.find_account_by_name
        ],
        "contacts": [
            ("email", {}),             # crm_service writes email lowercased; not unique (other writers do not lowercase)
            ("account_id", {}),
        ],
        "leads": [
            ("email", {}),
            ("status", {}),
        ],
        "opportunities": [
            ("account_id", {}),
            ("status", {}),
            ("stage", {}),
        ],
        "activities": [
            ("contact_id", {}),
            ("account_id", {}),
            ("created_at", {}),
        ],
        "tasks": [
            ("owner_id", {}),
            ("status", {}),
            ("due_date", {}),
        ],
        "ai_decisions": [
            ("agent_name", {}),
            ("status", {}),
            ([("linked_object_type", 1), ("linked_object_id", 1)], {}),
        ],
    },
    "torpedo": {
        # Live outreach v2. Collection names from outreach_engine/migration.py
        # NEW_COLLECTIONS, sending_engine, workflow_engine, scheduler,
        # mailbox_manager, logging_service, leads/canonical_ingestion.py.
        # The uniques below are only the ones the writers enforce today.
        "outreach_leads_v2": [
            # email is NOT unique: canonical_ingestion enrolls one lead per
            # (email, campaign_id), so one address legitimately has several docs.
            ("email", {}),
            ([("email", 1), ("campaign_id", 1)], {}),
            ("lead_id", {}),
            ([("workflow_id", 1), ("workflow_status", 1), ("next_send_at", 1)], {}),
            ("assigned_mailbox_id", {}),
            ("next_send_at", {}),
        ],
        "outreach_campaigns_v2": [
            ("campaign_id", {}),
            ("status", {}),
        ],
        "outreach_templates_v2": [
            ("template_id", {}),
            ([("company_brand", 1), ("step_type", 1)], {}),
        ],
        "outreach_sends_v2": [
            ("message_id", {"unique": True}),   # sending_engine + workflow_engine enforce this
            ([("campaign_id", 1), ("lead_id", 1)], {}),
            ([("status", 1), ("scheduled_at", 1)], {}),
        ],
        "outreach_send_logs": [
            ([("logged_at", -1)], {}),
            ([("campaign_id", 1), ("logged_at", -1)], {}),
            ([("mailbox_used", 1), ("logged_at", -1)], {}),
            ("status", {}),
        ],
        "outreach_error_logs": [
            ([("logged_at", -1)], {}),
            ("error_type", {}),
        ],
        "outreach_send_queue": [
            # Idempotency guard: one queued step per lead per campaign (scheduler.py).
            ([("campaign_id", 1), ("lead_id", 1), ("step_number", 1)],
             {"unique": True, "name": "idempotency_unique_idx"}),
            ([("scheduled_at", 1), ("status", 1)], {}),
            ("campaign_id", {}),
            ("lead_id", {}),
        ],
        "outreach_mailboxes": [
            ("mailbox_id", {"unique": True}),
            ("email_address", {"unique": True}),
            ([("health_status", 1), ("is_active", 1)], {}),
        ],
        "outreach_bounce_suppression": [
            ("email", {"unique": True}),        # sending_engine suppression; canonical_ingestion reads it
        ],
    },
    "finance_db": {
        "invoices": [
            ('invoice_number', {'unique': True, 'sparse': True}),
            ('idempotency_key', {'unique': True, 'sparse': True}),
            ('customer_id', {'sparse': True}),
            ('customer_name', {}),
            ('status', {}),
            ('due_date', {}),
            ('created_at', {}),
            ([('status', 1), ('due_date', 1)], {}),
            ([('status', 1), ('created_at', -1)], {'name': 'invoices_status_date'}),
            ([('customer_id', 1), ('status', 1)], {'name': 'invoices_customer_status'}),
        ],
        "customers": [
            ('name', {}),
            ('email', {'sparse': True}),
            ('operations_client_id', {'sparse': True}),
            ('createdAt', {}),
        ],
        "billing_vendors": [
            ('name', {}),
            ('email', {'sparse': True}),
            ('status', {}),
            ('createdAt', {}),
        ],
        "bills": [
            ([('status', 1), ('due_date', 1)], {'name': 'bills_status_due'}),
            ([('vendor_id', 1), ('status', 1)], {'name': 'bills_vendor_status'}),
        ],
        "expenses": [
            ([('approval_status', 1), ('created_at', -1)], {'name': 'expenses_approval_date'}),
        ],
        "payments_received": [
            ([('invoice_id', 1), ('created_at', -1)], {'name': 'payments_received_invoice_date'}),
        ],
        "payments_made": [
            ([('bill_id', 1), ('created_at', -1)], {'name': 'payments_made_bill_date'}),
        ],
        "purchase_orders": [
            ([('status', 1), ('created_at', -1)], {'name': 'po_status_date'}),
        ],
    },
    "torpedo_gmail": {
        "email_metadata": [
            ('gmail_message_id', {'unique': True}),
            ('mailbox_id', {}),
            ('from_email', {}),
            ('ai_category', {'sparse': True}),
            ('ai_analysis', {}),
            ([('mailbox_id', 1), ('timestamp', -1)], {}),
            ([('ai_category', 1), ('ai_confidence', -1)], {}),
            ([('ai_category', 1), ('mailbox_id', 1)], {}),
            ([('mailbox_id', 1), ('ai_category', 1), ('timestamp', -1)], {'name': 'email_metadata_mailbox_category_time'}),
            ([("mailbox_id", 1), ("gmail_message_id", 1)], {"unique": True}),  # gmail_service / gmail_workspace_service
        ],
        "parallel_sync_progress": [
            ('email', {'unique': True}),
            ('status', {}),
            ([('status', 1), ('updated_at', -1)], {}),
        ],
        "imap_accounts": [
            ('email', {'unique': True}),
            ('is_active', {}),
        ],
        "email_sync_log": [
            ('account_email', {}),
            ('started_at', {}),
            ([('account_email', 1), ('started_at', -1)], {}),
        ],
    },
    "campaign_platform": {
        "panelists": [
            ('email', {'unique': True}),
            ('country', {}),
            ('status', {}),
            ('double_opt_in_completed', {}),
            ([('status', 1), ('created_at', -1)], {'name': 'panelists_status_date'}),
            ([('status', 1), ('last_invited_at', 1)], {'name': 'panelists_status_last_invited'}),
            ([('double_opt_in_completed', 1), ('last_login_invite_sent_at', 1)], {'name': 'panelists_optin_last_login_invite'}),
            ('sfw_profile_complete', {'sparse': True}),
            ('sfw_last_login', {'sparse': True}),
            ('sfw_country', {'sparse': True}),
            ('invite_clicked_at', {'sparse': True}),
            ('last_invited_at', {'sparse': True}),
        ],
        "panel_invitation_log": [
            ('email', {}),
            ([('email', 1), ('sent_at', -1)], {'name': 'invitation_log_email_sent'}),
            ('batch_id', {}),
            ('status', {}),
            ('type', {}),
            ('ses_message_id', {'sparse': True}),
            ('invite_token', {'unique': True, 'sparse': True}),
        ],
        "panel_sessions": [
            ('expires_at', {'expireAfterSeconds': 0}),   # TTL: member sessions are purged once expired
        ],
        "panel_email_suppression": [
            ('email', {'unique': True}),
            ('reason', {}),
        ],
        "panel_rewards": [
            ('panelist_id', {}),
            ([('type', 1), ('status', 1)], {'name': 'rewards_type_status'}),
        ],
    },
    "torpedo_settings": {
    },
    "email_automation": {
        "users": [
            ('username', {'unique': True}),
            ('email', {'sparse': True}),
            ('createdAt', {}),
        ],
        "contacts": [
            ('email', {'unique': True}),
            ('listId', {}),
            ([('firstName', 1), ('lastName', 1)], {}),
            ('tags', {}),
            ('createdAt', {}),
            ([('email', 'text'), ('firstName', 'text'), ('lastName', 'text'), ('company', 'text')], {'name': 'contacts_text_search'}),
        ],
        "rfq_review_queue": [
            ('source_email_id', {'unique': True}),
            ('status', {}),
        ],
        "lists": [
            ('name', {}),
            ('createdAt', {}),
        ],
        "templates": [
            ('name', {}),
            ('createdAt', {}),
        ],
        "projects": [
            ('name', {}),
            ('status', {}),
            ('createdAt', {}),
            ([('projectStatus', 1), ('createdAt', -1)], {'name': 'projects_status_date'}),
            ([('user_id', 1), ('createdAt', -1)], {'name': 'projects_user_date'}),
        ],
        "leads": [
            ('email', {'sparse': True}),
            ('linkedin_url', {'sparse': True}),
            ('source', {}),
            ('classification_status', {}),
            ('seniority', {}),
            ('country', {}),
            ('createdAt', {}),
            ([('email', 'text'), ('name', 'text'), ('company', 'text'), ('title', 'text')], {'name': 'leads_text_search'}),
            ('engagement_score', {'sparse': True}),
            ('reengagement_eligible', {'sparse': True}),
            ('last_outreach_date', {'sparse': True}),
            ('linkedin_connection_status', {'sparse': True}),
            ([('engagement_score', -1), ('reengagement_eligible', 1), ('last_outreach_date', -1)], {'name': 'leads_reengagement_query'}),
            ([('source', 1), ('createdAt', -1)], {'name': 'leads_source_date'}),
            ([('classification_status', 1), ('createdAt', -1)], {'name': 'leads_classification_date'}),
            ([('country', 1), ('seniority', 1), ('createdAt', -1)], {'name': 'leads_country_seniority_date'}),
        ],
        "web_search_jobs": [
            ('job_id', {'unique': True}),
            ('status', {}),
            ('created_at', {}),
            ([('status', 1), ('created_at', -1)], {}),
        ],
        "panel_vendors": [
            ('name', {}),
            ('email', {'sparse': True}),
            ('status', {}),
            ('createdAt', {}),
            ('vid', {'unique': True, 'sparse': True}),
            ([('status', 1), ('createdAt', -1)], {'name': 'panel_vendors_status_date'}),
        ],
        "clients": [
            ('name', {}),
            ('email', {'sparse': True}),
            ('status', {}),
            ('sales_account_id', {'sparse': True}),
            ('createdAt', {}),
            ([('status', 1), ('createdAt', -1)], {'name': 'clients_status_date'}),
        ],
        "vendors": [
            ('name', {}),
            ('status', {}),
        ],
        "openai_usage_logs": [
            ('timestamp', {}),
            ([('source', 1), ('timestamp', -1)], {}),
            ([('model', 1), ('timestamp', -1)], {}),
        ],
        "suppression_list": [
            ('email', {'unique': True}),
            ('reason', {}),
            ('suppressed_at', {}),
        ],
        "campaign_sends": [
            ('idempotency_key', {'unique': True, 'sparse': True}),
            ('campaign_id', {}),
            ('recipient_id', {}),
            ('sent_at', {}),
            ('status', {'sparse': True}),
            ([('campaign_id', 1), ('status', 1), ('created_at', -1)], {'name': 'campaign_sends_analytics'}),
        ],
        "email_audit_log": [
            ([('campaign_id', 1), ('timestamp', -1)], {}),
            ('timestamp', {}),
            ('action', {}),
        ],
        "audit_log": [
            ([('entity_type', 1), ('entity_id', 1), ('timestamp', -1)], {}),
            ('timestamp', {}),
            ('user_id', {'sparse': True}),
            ('action', {}),
        ],
        "ai_review_queue": [
            ([('status', 1), ('queued_at', -1)], {}),
            ('entity_type', {}),
        ],
        "imap_accounts": [
            ('email', {'unique': True}),
            ('is_active', {}),
        ],
        "email_leads": [
            ('email_id', {'unique': True}),
            ('segment', {}),
            ('from_email', {}),
            ('received_at', {}),
        ],
        "campaign_recipients": [
            ('campaign_id', {}),
            ('lead_id', {}),
            ('ab_variant', {'sparse': True}),
            ('engagement_status', {'sparse': True}),
            ([('campaign_id', 1), ('ab_variant', 1)], {'name': 'campaign_recipients_ab_test'}),
            ([('campaign_id', 1), ('engagement_status', 1)], {'name': 'campaign_recipients_engagement'}),
        ],
        "linkedin_connections": [
            ('lead_id', {}),
            ('session_id', {'sparse': True}),
            ('status', {'sparse': True}),
            ('sent_at', {'sparse': True}),
            ('accepted_at', {'sparse': True}),
            ([('lead_id', 1), ('status', 1)], {'name': 'linkedin_connections_by_lead_status'}),
            ([('session_id', 1), ('sent_at', -1)], {'name': 'linkedin_connections_session_timeline'}),
        ],
        "linkedin_sessions": [
            ('session_id', {'unique': True}),
            ('email', {'sparse': True}),
            ('status', {'sparse': True}),
            ('login_date', {'sparse': True}),
            ('last_active', {'sparse': True}),
        ],
        "linkedin_messages": [
            ('lead_id', {}),
            ('connection_id', {'sparse': True}),
            ('sent_at', {}),
            ('read_at', {'sparse': True}),
            ('replied_at', {'sparse': True}),
            ([('lead_id', 1), ('sent_at', -1)], {'name': 'linkedin_messages_by_lead_timeline'}),
        ],
        "linkedin_activities": [
            ('session_id', {}),
            ('date', {}),
            ([('date', 1), ('session_id', 1)], {'name': 'linkedin_activities_daily_summary'}),
            ([('session_id', -1), ('date', -1)], {'name': 'linkedin_activities_session_timeline'}),
        ],
        "linkedin_templates": [
            ('name', {'sparse': True}),
            ('created_at', {'sparse': True}),
        ],
        "domain_health": [
            ('domain', {'unique': True}),
            ('last_checked', {'sparse': True}),
        ],
        "gmail_account_usage": [
            ('account_id', {'unique': True, 'sparse': True}),
            ('last_sync', {'sparse': True}),
            ([('account_id', 1), ('last_sync', -1)], {'name': 'gmail_account_usage_sync_tracking'}),
        ],
        "sales_accounts": [
            ('account_name', {}),
            ('company', {}),
            ('status', {}),
            ('createdAt', {}),
            ([('status', 1), ('createdAt', -1)], {'name': 'sales_accounts_status_date'}),
        ],
        "search_cache": [
            ('query_hash', {'unique': True}),
            ('created_at', {}),
            ('provider', {}),
            ([('job_title', 1), ('industry', 1), ('location', 1)], {'name': 'search_cache_components'}),
            ("expires_at", {"expireAfterSeconds": 0}),   # TTL, search_cache expiry
        ],
        "search_cache_metrics": [
            ('date', {}),
            ([('date', 1), ('hour', 1)], {}),
        ],
        "dedup_index": [
            ('linkedin_url_hash', {'unique': True, 'sparse': True}),
            ('email_hash', {'sparse': True}),
            ('name_company_hash', {'sparse': True}),
            ('lead_id', {}),
            ('created_at', {}),
        ],
        "dedup_logs": [
            ('rejected_at', {}),
            ('reason', {}),
            ('source', {}),
        ],
        "rfqs": [
            ([('status', 1), ('created_at', -1)], {'name': 'rfqs_status_date'}),
        ],
        "leads_raw": [
            ("email", {"unique": True, "sparse": True}),   # canonical_ingestion.py
            ("linkedin_url", {"unique": True, "sparse": True}),
        ],
        # marketing/schema.py (DB = email_automation; not written by any crm writer)
        "web_sites": [
            ('domain', {'unique': True}),
            ('bu', {}),
        ],
        "web_visitors": [
            ('visitor_id', {'unique': True}),
            ('contact_id', {'sparse': True}),
            ('lead_id', {'sparse': True}),
            ('last_seen', {}),
        ],
        "web_sessions": [
            ('session_id', {'unique': True}),
            ('visitor_id', {}),
            ([('started_at', 1), ('bu', 1)], {}),
        ],
        "web_events": [
            ('visitor_id', {}),
            ([('at', 1), ('bu', 1)], {}),
            ('type', {}),
        ],
        "consents": [
            ('visitor_id', {}),
            ('at', {}),
        ],
        "touchpoints": [
            ('tp_key', {'unique': True}),
            ([('lead_id', 1), ('at', 1)], {}),
            ('contact_id', {'sparse': True}),
            ('visitor_id', {'sparse': True}),
            ('click_ids.gclid', {'sparse': True}),
            ('click_ids.fbclid', {'sparse': True}),
            ('click_ids.li_fat_id', {'sparse': True}),
            ('campaign_id', {'sparse': True}),
        ],
        "attribution_results": [
            ([('lead_id', 1), ('conversion_id', 1), ('model', 1)], {'unique': True}),
            ([('bu', 1), ('model', 1), ('event', 1)], {}),
        ],
        "ga4_daily": [
            ([('property_id', 1), ('date', 1), ('dims_key', 1)], {'unique': True}),
            ([('date', 1), ('bu', 1)], {}),
        ],
        "gsc_queries_daily": [
            ([('site', 1), ('date', 1), ('query', 1), ('page', 1), ('country', 1), ('device', 1)], {'unique': True}),
            ([('date', 1), ('bu', 1)], {}),
        ],
        "gsc_pages_daily": [
            ([('site', 1), ('date', 1), ('page', 1)], {'unique': True}),
            ([('date', 1), ('bu', 1)], {}),
        ],
        "gsc_sitemaps": [
            ([('site', 1), ('path', 1)], {'unique': True}),
        ],
        "gsc_url_index": [
            ('url', {'unique': True}),
            ('site', {}),
        ],
        "seo_audits": [
            ([('site', 1), ('started_at', -1)], {}),
        ],
        "seo_issues": [
            ('key', {'unique': True}),
            ([('site', 1), ('status', 1), ('severity', 1)], {}),
            ('audit_id', {}),
        ],
        "cwv_results": [
            ([('url', 1), ('strategy', 1), ('date', 1)], {}),
            ([('date', 1), ('bu', 1)], {}),
        ],
        "keywords": [
            ([('bu', 1), ('keyword', 1)], {'unique': True}),
        ],
        "keyword_positions": [
            ([('keyword_id', 1), ('date', 1)], {'unique': True}),
            ([('date', 1), ('bu', 1)], {}),
        ],
        "content_gaps": [
            ([('bu', 1), ('status', 1)], {}),
        ],
        "seo_fix_plans": [
            ('site', {'unique': True}),
        ],
        "ad_accounts": [
            ([('platform', 1), ('account_id', 1)], {'unique': True}),
            ('bu', {}),
        ],
        "ad_campaigns": [
            ([('platform', 1), ('campaign_id', 1)], {'unique': True}),
            ('bu', {}),
        ],
        "ad_groups": [
            ([('platform', 1), ('group_id', 1)], {'unique': True}),
            ('campaign_id', {}),
        ],
        "ads": [
            ([('platform', 1), ('ad_id', 1)], {'unique': True}),
            ('campaign_id', {}),
        ],
        "ad_metrics_daily": [
            ([('platform', 1), ('level', 1), ('entity_id', 1), ('date', 1)], {'unique': True}),
            ('campaign_id', {}),
            ([('date', 1), ('bu', 1)], {}),
        ],
        "search_terms": [
            ([('campaign_id', 1), ('term', 1), ('date', 1)], {'unique': True}),
            ([('date', 1), ('bu', 1)], {}),
        ],
        "offline_conversion_uploads": [
            ([('platform', 1), ('lead_id', 1), ('event', 1)], {'unique': True}),
            ('status', {}),
        ],
        "audiences": [
            ([('bu', 1), ('platform', 1), ('name', 1)], {'unique': True}),
        ],
        "social_accounts": [
            ([('platform', 1), ('account_id', 1)], {'unique': True}),
            ('bu', {}),
        ],
        "social_posts": [
            ([('platform', 1), ('post_id', 1)], {'unique': True, 'sparse': True}),
            ('content_item_id', {}),
        ],
        "social_metrics_daily": [
            ([('platform', 1), ('entity_id', 1), ('date', 1)], {'unique': True}),
            ([('date', 1), ('bu', 1)], {}),
        ],
        "inbox_items": [
            ([('channel', 1), ('external_id', 1)], {'unique': True}),
            ([('status', 1), ('due_at', 1)], {}),
            ('phone_hash', {'sparse': True}),
            ('contact_id', {'sparse': True}),
            ('lead_id', {'sparse': True}),
        ],
        "whatsapp_optins": [
            ('phone_hash', {}),
            ('contact_id', {'sparse': True}),
        ],
        "marketing_touches": [
            ([('lead_id', 1), ('at', -1)], {}),
            ('phone_hash', {'sparse': True}),
            ('email', {'sparse': True}),
        ],
        "lead_form_pending": [
            ('leadgen_id', {'unique': True}),
            ('status', {}),
        ],
        "whatsapp_templates": [
            ([('bu', 1), ('name', 1), ('language', 1)], {'unique': True}),
        ],
        "content_items": [
            ([('bu', 1), ('channel', 1), ('status', 1)], {}),
            ('scheduled_for', {'sparse': True}),
        ],
        "brand_voice": [
            ('bu', {'unique': True}),
        ],
        "experiments": [
            ([('bu', 1), ('status', 1)], {}),
        ],
        "decision_candidates": [
            ([('decision_type', 1), ('status', 1)], {}),
            ([('entity_key', 1), ('created_at', -1)], {}),
        ],
        "decisions": [
            ([('decision_type', 1), ('status', 1)], {}),
            ([('entity_key', 1), ('created_at', -1)], {}),
            ('candidate_id', {}),
        ],
        "decision_outcomes": [
            ('decision_id', {'unique': True}),
            ([('decision_type', 1), ('measured_at', -1)], {}),
        ],
        "marketing_eval_cases": [
            ('key', {'unique': True}),
            ('decision_type', {}),
        ],
        "marketing_eval_runs": [
            ([('at', -1)], {}),   # marketing/schema.py has this as a bare tuple (unpack bug, see HANDOFF)
        ],
        "marketing_reports": [
            ('week', {'unique': True}),
        ],
        "marketing_kpi_snapshots": [
            ([('kpi', 1), ('date', 1), ('bu', 1)], {'unique': True}),
            ([('date', 1), ('bu', 1)], {}),
        ],
    },
    "cint_research": {
        # database_setup_cint.py (setup_cint_database, default db name cint_research)
        "cint_surveys": [
            ([('survey_id', 1)], {'unique': True}),
            ([('is_active', 1)], {}),
            ([('is_live', 1)], {}),
            ([('country_language', 1)], {}),
            ([('buyer_id', 1)], {}),
            ([('message_reason', 1)], {}),
            ([('received_at', -1)], {}),
            ([('total_remaining', 1)], {}),
            ([('survey_id', 1), ('is_active', 1)], {}),
        ],
        "cint_entry_links": [
            ([('survey_id', 1)], {'unique': True}),
            ([('created_at', -1)], {}),
            ([('updated_at', -1)], {}),
        ],
        "cint_settings": [
            ([('user_id', 1)], {}),
            ([('supplier_code', 1)], {}),
            ([('is_active', 1)], {}),
        ],
        "cint_filters": [
            ([('user_id', 1)], {}),
            ([('name', 1)], {}),
        ],
        "cint_metrics": [
            ([('survey_id', 1)], {'unique': True}),
            ([('last_updated', -1)], {}),
            ([('last_allocation', -1)], {}),
        ],
        "cint_subscriptions": [
            ([('supplier_code', 1)], {'unique': True}),
            ([('status', 1)], {}),
            ([('last_webhook_received_at', -1)], {}),
        ],
        "cint_buyer_stats": [
            ([('buyer_name', 1)], {'unique': True}),
            ([('conversion_rate', -1)], {}),
            ([('last_updated', -1)], {}),
        ],
        "cint_respondent_outcomes": [
            ([('respondent_id', 1)], {}),
            ([('session_id', 1)], {'unique': True}),
            ([('survey_id', 1)], {}),
            ([('marketplace_status', 1)], {}),
            ([('client_status', 1)], {}),
            ([('received_at', -1)], {}),
            ([('entry_date', -1), ('last_date', -1)], {}),
        ],
        "respondents": [
            ([('provider', 1)], {}),
            ([('supplier_code', 1)], {}),
        ],
        "surveys": [
            ([('provider', 1)], {}),
            ([('provider', 1), ('external_id', 1)], {}),
            ([('provider', 1), ('is_active', 1)], {}),
        ],
        "survey_metrics": [
            ([('survey_id', 1)], {}),
            ([('provider', 1)], {}),
            ([('last_updated', -1)], {}),
        ],
        "allocation_log": [
            ([('respondent_id', 1)], {}),
            ([('survey_id', 1)], {}),
            ([('provider', 1)], {}),
            ([('timestamp', -1)], {}),
            ([('status', 1)], {}),
            ([('timestamp', 1)], {'expireAfterSeconds': 2592000}),
        ],
    },
    "cpx_research": {
        "cpx_surveys": [
            ('survey_id', {'unique': True}),
            ('status', {}),
            ('loi', {}),
            ('cpi', {}),
            ('last_updated', {}),
            ([('loi', 1), ('cpi', -1)], {}),
            ("payout", {}),
            ("country", {}),
            ("category", {}),
            ([("country", 1), ("last_updated", -1)], {}),
        ],
        "cpx_filters": [
            ('name', {}),
        ],
        "cpx_diagnostic_logs": [
            ([("timestamp", 1)], {"expireAfterSeconds": 604800}),
            ("country_code", {}),
            ("outcome", {}),
        ],
    },
    "traffic_flow_db": {
        "url_parameters": [
            ('vendorId', {}),
            ('status', {}),
            ('createdAt', {}),
            ('callback_key', {'unique': True, 'sparse': True}),
            ('cint_hashed_pid', {}),
            ([('createdAt', -1), ('status', 1)], {}),
            ([('vendorId', 1), ('status', 1), ('createdAt', -1)], {'name': 'url_params_vendor_status_date'}),
        ],
        "cpx_callback_logs": [
            ('timestamp', {}),
            ('transaction_id', {}),
            ('status', {}),
            ([('timestamp', -1)], {}),
        ],
    },
    "ai_governance": {
        # ai_governance/governance_checks.py (db.ai_governance())
        "gemini_daily_usage": [
            ([("date", 1)], {"unique": True}),   # USAGE_COLLECTION default (env AI_USAGE_COLLECTION may differ)
        ],
        "email_classification_guard": [
            ([("email_id", 1)], {"unique": True, "name": "unique_email_classification"}),
        ],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _default_name(keys):
    """MongoDB's default index name: field_direction joined by underscores."""
    return "_".join("%s_%s" % (f, d) for f, d in _norm_keys(keys))


def _norm_keys(keys):
    if isinstance(keys, str):
        return [(keys, 1)]
    return [tuple(k) for k in keys]


def _spec_name(keys, opts):
    return opts.get("name") or _default_name(keys)


def _by_name(db_name):
    """Shared database handle from backend/db.py."""
    try:
        from db import by_name
    except ImportError:
        from backend.db import by_name
    return by_name(db_name)


def create_index_safe(collection, keys, **kwargs):
    """
    Safely create one index, logging any error instead of raising.

    Args:
        collection: MongoDB collection
        keys: Index keys (field or list of tuples)
        **kwargs: Additional index options (unique, sparse, etc.)
    """
    try:
        index_name = collection.create_index(keys, background=True, **kwargs)
        logger.info("Index created: %s.%s", collection.name, index_name)
        return index_name
    except OperationFailure as e:
        if "already exists" in str(e):
            logger.debug("Index already exists on %s", collection.name)
        else:
            logger.warning("Could not create index on %s: %s", collection.name, e)
    except Exception as e:
        logger.warning("Index creation failed for %s: %s", collection.name, e)
    return None


# ---------------------------------------------------------------------------
# Registry driver
# ---------------------------------------------------------------------------
def _new_stats():
    return {"created": 0, "existing": 0, "conflicts": [], "failed": [], "missing": []}


def ensure_indexes(db_names=None, client=None, build=True):
    """
    Bring every registry index into existence, one database at a time.

    Args:
        db_names: iterable of database names; default is the whole registry.
        client: optional pymongo client; default uses backend/db.py handles.
        build: False makes this a read-only comparison (nothing is created).

    Returns:
        {db_name: {"created": int, "existing": int, "conflicts": [str],
                   "failed": [str], "missing": [str]}}
        "missing" is only filled when build is False.
    """
    names = list(db_names) if db_names else list(INDEXES)
    summary = {}
    for db_name in names:
        stats = _new_stats()
        summary[db_name] = stats
        if db_name not in INDEXES:
            stats["failed"].append("unknown database %r (not in INDEXES)" % db_name)
            continue
        try:
            handle = client[db_name] if client is not None else _by_name(db_name)
        except Exception as e:
            stats["failed"].append("no database handle: %s" % e)
            logger.warning("index registry: skipping %s, no handle: %s", db_name, e)
            continue

        for coll_name, specs in INDEXES[db_name].items():
            coll = handle[coll_name]
            try:
                info = coll.index_information()
            except PyMongoError as e:
                stats["failed"].append("%s: index_information: %s" % (coll_name, e))
                continue

            for keys, opts in specs:
                opts = dict(opts)
                name = _spec_name(keys, opts)
                want = _norm_keys(keys)

                if name in info:
                    # text/hashed indexes report internal keys (_fts/_ftsx), so compare by name only.
                    special = any(d in ("text", "hashed") for _, d in want)
                    if special or [tuple(k) for k in info[name].get("key", [])] == want:
                        stats["existing"] += 1
                    else:
                        stats["conflicts"].append("%s.%s: name taken by different keys" % (coll_name, name))
                    continue

                same_keys = [n for n, spec in info.items()
                             if [tuple(k) for k in spec.get("key", [])] == want]
                if same_keys:
                    stats["conflicts"].append("%s.%s: same keys already indexed as %s"
                                              % (coll_name, name, same_keys[0]))
                    continue

                if not build:
                    stats["missing"].append("%s.%s" % (coll_name, name))
                    continue

                opts.setdefault("background", True)
                try:
                    coll.create_index(keys if isinstance(keys, str) else want, **opts)
                    stats["created"] += 1
                except OperationFailure as e:
                    detail = "%s.%s: %s" % (coll_name, name, e)
                    if e.code in _CONFLICT_CODES:
                        stats["conflicts"].append(detail)
                    else:
                        stats["failed"].append(detail)
                except PyMongoError as e:
                    stats["failed"].append("%s.%s: %s" % (coll_name, name, e))

        logger.info(
            "index registry %s: created=%d existing=%d conflicts=%d failed=%d missing=%d",
            db_name, stats["created"], stats["existing"], len(stats["conflicts"]),
            len(stats["failed"]), len(stats["missing"]))
        for line in stats["conflicts"] + stats["failed"]:
            logger.warning("index registry %s: %s", db_name, line)
    return summary


def setup_indexes(db_manager=None):
    """
    Backward-compatible entry point: build every registry index.

    Args:
        db_manager: Optional DatabaseManager instance (its .client is used).
    """
    client = getattr(db_manager, "client", None) if db_manager is not None else None
    print("Setting up database indexes...")
    summary = ensure_indexes(client=client, build=True)
    failed = sum(len(s["failed"]) + len(s["conflicts"]) for s in summary.values())
    print("Database indexes setup complete (%d problems, see log)." % failed)
    return True


def drop_all_indexes(db_manager=None, confirm=False):
    """
    Drop all non-system indexes. USE WITH CAUTION!

    Args:
        db_manager: Optional DatabaseManager instance
        confirm: Must be True to actually drop indexes
    """
    if not confirm:
        print("To drop indexes, call with confirm=True")
        return False

    try:
        from database import get_db_manager
        if db_manager is None:
            db_manager = get_db_manager()
    except ImportError:
        from .database import get_db_manager
        if db_manager is None:
            db_manager = get_db_manager()

    client = db_manager.client

    databases = ["email_automation", "finance_db", "traffic_flow_db", "cpx_research", "torpedo_settings"]

    for db_name in databases:
        db = client[db_name]
        for collection_name in db.list_collection_names():
            try:
                db[collection_name].drop_indexes()
                print("Dropped indexes on %s.%s" % (db_name, collection_name))
            except Exception as e:
                print("Error dropping indexes on %s.%s: %s" % (db_name, collection_name, e))

    print("All indexes dropped")
    return True


if __name__ == "__main__":
    setup_indexes()
