"""
DATABASE INDEXES MODULE
Creates and maintains MongoDB indexes for optimal query performance.

Run this module to ensure all indexes are created:
    python -m backend.indexes

Or import and call setup_indexes() during application startup.
"""

from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.errors import OperationFailure
import logging

logger = logging.getLogger(__name__)


def create_index_safe(collection, keys, **kwargs):
    """
    Safely create an index, logging any errors.
    
    Args:
        collection: MongoDB collection
        keys: Index keys (field or list of tuples)
        **kwargs: Additional index options (unique, sparse, etc.)
    """
    try:
        index_name = collection.create_index(keys, background=True, **kwargs)
        logger.info(f"✅ Index created: {collection.name}.{index_name}")
        return index_name
    except OperationFailure as e:
        if "already exists" in str(e):
            logger.debug(f"Index already exists on {collection.name}")
        else:
            logger.warning(f"Could not create index on {collection.name}: {e}")
    except Exception as e:
        logger.warning(f"Index creation failed for {collection.name}: {e}")
    return None


def setup_indexes(db_manager=None):
    """
    Create all required indexes across the application databases.
    
    Args:
        db_manager: Optional DatabaseManager instance
    """
    try:
        from database import get_db_manager
        if db_manager is None:
            db_manager = get_db_manager()
    except ImportError:
        from .database import get_db_manager
        if db_manager is None:
            db_manager = get_db_manager()
    
    client = db_manager.client
    
    print("🔧 Setting up database indexes...")
    
    # ============== EMAIL AUTOMATION DATABASE ==============
    email_db = client["email_automation"]
    
    # Users collection
    users = email_db["users"]
    create_index_safe(users, "username", unique=True)
    create_index_safe(users, "email", sparse=True)
    create_index_safe(users, "createdAt")
    
    # Contacts collection
    contacts = email_db["contacts"]
    create_index_safe(contacts, "email", unique=True)
    create_index_safe(contacts, "listId")
    create_index_safe(contacts, [("firstName", ASCENDING), ("lastName", ASCENDING)])
    create_index_safe(contacts, "tags")
    create_index_safe(contacts, "createdAt")
    create_index_safe(contacts, [
        ("email", TEXT),
        ("firstName", TEXT),
        ("lastName", TEXT),
        ("company", TEXT)
    ], name="contacts_text_search")
    
    # Lists collection
    lists = email_db["lists"]
    create_index_safe(lists, "name")
    create_index_safe(lists, "createdAt")
    
    # Templates collection
    templates = email_db["templates"]
    create_index_safe(templates, "name")
    create_index_safe(templates, "createdAt")
    
    # Projects collection
    projects = email_db["projects"]
    create_index_safe(projects, "name")
    create_index_safe(projects, "status")
    create_index_safe(projects, "createdAt")
    
    # Leads collection
    leads = email_db["leads"]
    create_index_safe(leads, "email", sparse=True)
    create_index_safe(leads, "linkedin_url", sparse=True)
    create_index_safe(leads, "source")
    create_index_safe(leads, "classification_status")
    create_index_safe(leads, "seniority")
    create_index_safe(leads, "country")
    create_index_safe(leads, "createdAt")
    create_index_safe(leads, [
        ("email", TEXT),
        ("name", TEXT),
        ("company", TEXT),
        ("title", TEXT)
    ], name="leads_text_search")
    
    # Web Search Jobs collection
    web_search_jobs = email_db["web_search_jobs"]
    create_index_safe(web_search_jobs, "job_id", unique=True)
    create_index_safe(web_search_jobs, "status")
    create_index_safe(web_search_jobs, "created_at")
    create_index_safe(web_search_jobs, [("status", ASCENDING), ("created_at", DESCENDING)])
    
    # Panel Vendors collection (Operations)
    panel_vendors = email_db["panel_vendors"]
    create_index_safe(panel_vendors, "name")
    create_index_safe(panel_vendors, "email", sparse=True)
    create_index_safe(panel_vendors, "status")
    create_index_safe(panel_vendors, "createdAt")
    # Panel vendors VID unique constraint (sparse to allow nulls)
    create_index_safe(panel_vendors, "vid", unique=True, sparse=True)
    
    # Clients collection (Operations)
    clients = email_db["clients"]
    create_index_safe(clients, "name")
    create_index_safe(clients, "email", sparse=True)
    create_index_safe(clients, "status")
    create_index_safe(clients, "sales_account_id", sparse=True)
    create_index_safe(clients, "createdAt")
    
    # Vendors collection (for CPX callbacks)
    vendors = email_db["vendors"]
    create_index_safe(vendors, "name")
    create_index_safe(vendors, "status")
    
    # OpenAI Usage Logs
    openai_usage = email_db["openai_usage_logs"]
    create_index_safe(openai_usage, "timestamp")
    create_index_safe(openai_usage, [("source", ASCENDING), ("timestamp", DESCENDING)])
    create_index_safe(openai_usage, [("model", ASCENDING), ("timestamp", DESCENDING)])
    
    # ============== EMAIL SAFETY INDEXES ==============
    # Suppression List - unique email for global suppression
    suppression_list = email_db["suppression_list"]
    create_index_safe(suppression_list, "email", unique=True)
    create_index_safe(suppression_list, "reason")
    create_index_safe(suppression_list, "suppressed_at")
    
    # Campaign Sends - idempotency key to prevent duplicate sends
    campaign_sends = email_db["campaign_sends"]
    create_index_safe(campaign_sends, "idempotency_key", unique=True, sparse=True)
    create_index_safe(campaign_sends, "campaign_id")
    create_index_safe(campaign_sends, "recipient_id")
    create_index_safe(campaign_sends, "sent_at")
    
    # Email Audit Log - track all email operations
    email_audit_log = email_db["email_audit_log"]
    create_index_safe(email_audit_log, [("campaign_id", ASCENDING), ("timestamp", DESCENDING)])
    create_index_safe(email_audit_log, "timestamp")
    create_index_safe(email_audit_log, "action")
    
    # Audit Log - unified entity audit trail
    audit_log = email_db["audit_log"]
    create_index_safe(audit_log, [("entity_type", ASCENDING), ("entity_id", ASCENDING), ("timestamp", DESCENDING)])
    create_index_safe(audit_log, "timestamp")
    create_index_safe(audit_log, "user_id", sparse=True)
    create_index_safe(audit_log, "action")
    
    # AI Review Queue - low confidence classifications for human review
    ai_review_queue = email_db["ai_review_queue"]
    create_index_safe(ai_review_queue, [("status", ASCENDING), ("queued_at", DESCENDING)])
    create_index_safe(ai_review_queue, "entity_type")
    
    # IMAP Accounts
    imap_accounts = email_db["imap_accounts"]
    create_index_safe(imap_accounts, "email", unique=True)
    create_index_safe(imap_accounts, "is_active")
    
    # Email Leads
    email_leads = email_db["email_leads"]
    create_index_safe(email_leads, "email_id", unique=True)
    create_index_safe(email_leads, "segment")
    create_index_safe(email_leads, "from_email")
    create_index_safe(email_leads, "received_at")
    
    # ============== FINANCE DATABASE ==============
    finance_db = client["finance_db"]
    
    # Invoices collection
    invoices = finance_db["invoices"]
    create_index_safe(invoices, "invoice_number", unique=True, sparse=True)
    create_index_safe(invoices, "idempotency_key", unique=True, sparse=True)  # P0.14: Invoice idempotency
    create_index_safe(invoices, "customer_id", sparse=True)
    create_index_safe(invoices, "customer_name")
    create_index_safe(invoices, "status")
    create_index_safe(invoices, "due_date")
    create_index_safe(invoices, "created_at")
    create_index_safe(invoices, [("status", ASCENDING), ("due_date", ASCENDING)])
    
    # Customers collection
    customers = finance_db["customers"]
    create_index_safe(customers, "name")
    create_index_safe(customers, "email", sparse=True)
    create_index_safe(customers, "operations_client_id", sparse=True)
    create_index_safe(customers, "createdAt")
    
    # Billing Vendors collection
    billing_vendors = finance_db["billing_vendors"]
    create_index_safe(billing_vendors, "name")
    create_index_safe(billing_vendors, "email", sparse=True)
    create_index_safe(billing_vendors, "status")
    create_index_safe(billing_vendors, "createdAt")
    
    # ============== TRAFFIC FLOW DATABASE ==============
    traffic_db = client["traffic_flow_db"]
    
    # URL Parameters collection
    url_params = traffic_db["url_parameters"]
    create_index_safe(url_params, "vendor_id")
    create_index_safe(url_params, "status")
    create_index_safe(url_params, "created_at")
    create_index_safe(url_params, "callback_key", unique=True, sparse=True)  # P0.15: CPX callback idempotency
    
    # CPX Callback Logs
    cpx_callback_logs = traffic_db["cpx_callback_logs"]
    create_index_safe(cpx_callback_logs, "timestamp")
    create_index_safe(cpx_callback_logs, "transaction_id")
    create_index_safe(cpx_callback_logs, "status")
    create_index_safe(cpx_callback_logs, [("timestamp", DESCENDING)])
    
    # ============== CPX RESEARCH DATABASE ==============
    cpx_db = client["cpx_research"]
    
    # CPX Surveys collection
    cpx_surveys = cpx_db["cpx_surveys"]
    create_index_safe(cpx_surveys, "survey_id", unique=True)
    create_index_safe(cpx_surveys, "status")
    create_index_safe(cpx_surveys, "loi")
    create_index_safe(cpx_surveys, "cpi")
    create_index_safe(cpx_surveys, "last_updated")
    create_index_safe(cpx_surveys, [("loi", ASCENDING), ("cpi", DESCENDING)])
    
    # CPX Filters collection
    cpx_filters = cpx_db["cpx_filters"]
    create_index_safe(cpx_filters, "name")
    
    # ============== SETTINGS DATABASE ==============
    settings_db = client["torpedo_settings"]
    
    # App Settings collection (uses _id as key)
    # No additional indexes needed - _id is already indexed
    
    # ============== SALES DATABASE ==============
    # Sales Accounts (in email_automation for now)
    sales_accounts = email_db["sales_accounts"]
    create_index_safe(sales_accounts, "account_name")
    create_index_safe(sales_accounts, "company")
    create_index_safe(sales_accounts, "status")
    create_index_safe(sales_accounts, "createdAt")
    
    # ============== COST OPTIMIZATION INDEXES ==============
    
    # Search Cache - reduces Google CSE API calls by 70%+
    search_cache = email_db["search_cache"]
    create_index_safe(search_cache, "query_hash", unique=True)
    create_index_safe(search_cache, "created_at")
    create_index_safe(search_cache, "provider")
    create_index_safe(search_cache, [
        ("job_title", ASCENDING),
        ("industry", ASCENDING),
        ("location", ASCENDING)
    ], name="search_cache_components")
    # TTL index for automatic expiration
    try:
        search_cache.create_index("expires_at", expireAfterSeconds=0)
        logger.info("✅ TTL index created: search_cache.expires_at")
    except Exception as e:
        logger.debug(f"TTL index exists or failed: {e}")
    
    # Search Cache Metrics
    cache_metrics = email_db["search_cache_metrics"]
    create_index_safe(cache_metrics, "date")
    create_index_safe(cache_metrics, [("date", ASCENDING), ("hour", ASCENDING)])
    
    # Deduplication Index - fast lookups to prevent duplicate leads
    dedup_index = email_db["dedup_index"]
    create_index_safe(dedup_index, "linkedin_url_hash", unique=True, sparse=True)
    create_index_safe(dedup_index, "email_hash", sparse=True)
    create_index_safe(dedup_index, "name_company_hash", sparse=True)
    create_index_safe(dedup_index, "lead_id")
    create_index_safe(dedup_index, "created_at")
    
    # Deduplication Logs - audit trail of rejected duplicates
    dedup_logs = email_db["dedup_logs"]
    create_index_safe(dedup_logs, "rejected_at")
    create_index_safe(dedup_logs, "reason")
    create_index_safe(dedup_logs, "source")
    
    print("✅ Database indexes setup complete!")
    return True


def drop_all_indexes(db_manager=None, confirm=False):
    """
    Drop all non-system indexes. USE WITH CAUTION!
    
    Args:
        db_manager: Optional DatabaseManager instance
        confirm: Must be True to actually drop indexes
    """
    if not confirm:
        print("⚠️ To drop indexes, call with confirm=True")
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
                print(f"Dropped indexes on {db_name}.{collection_name}")
            except Exception as e:
                print(f"Error dropping indexes on {db_name}.{collection_name}: {e}")
    
    print("✅ All indexes dropped")
    return True


if __name__ == "__main__":
    # Run index setup when executed directly
    setup_indexes()
