"""
Sales Schema Setup
Creates collections, indexes, and validation for the sales module.
Four collections: leads, company_domains, email_events, rfqs.
"""

import os
import logging
from pymongo import MongoClient, IndexModel, ASCENDING, DESCENDING
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")


def get_sales_db():
    """Get the email_automation database for sales collections."""
    client = MongoClient(MONGO_URI)
    return client["email_automation"]


def setup_leads_collection(db=None):
    """
    Create indexes for the unified leads collection.
    Replaces: leads_raw, leads_enriched, contacts, email_leads, sales_accounts.
    """
    if db is None:
        db = get_sales_db()

    col = db["leads"]
    indexes = [
        IndexModel([("email", ASCENDING)], unique=True, sparse=True, name="idx_leads_email"),
        IndexModel([("domain", ASCENDING)], name="idx_leads_domain"),
        IndexModel([("stage", ASCENDING)], name="idx_leads_stage"),
        IndexModel([("source", ASCENDING)], name="idx_leads_source"),
        IndexModel([("last_contacted", DESCENDING)], name="idx_leads_last_contacted"),
        IndexModel([("track", ASCENDING)], name="idx_leads_track"),
        IndexModel([("archived", ASCENDING)], name="idx_leads_archived"),
        IndexModel([("email_draft.status", ASCENDING)], sparse=True, name="idx_leads_draft_status"),
        IndexModel([("reengagement_eligible_at", ASCENDING)], sparse=True, name="idx_leads_reengagement"),
        IndexModel([("created_at", DESCENDING)], name="idx_leads_created"),
    ]
    col.create_indexes(indexes)
    logger.info("✅ leads collection indexes created")
    return col


def setup_company_domains_collection(db=None):
    """
    Create indexes for the company_domains (email pattern cache) collection.
    """
    if db is None:
        db = get_sales_db()

    col = db["company_domains"]
    indexes = [
        IndexModel([("domain", ASCENDING)], unique=True, name="idx_company_domains_domain"),
    ]
    col.create_indexes(indexes)
    logger.info("✅ company_domains collection indexes created")
    return col


def setup_email_events_collection(db=None):
    """
    Create indexes for the email_events (tracking) collection.
    """
    if db is None:
        db = get_sales_db()

    col = db["email_events"]
    indexes = [
        IndexModel([("lead_id", ASCENDING)], name="idx_events_lead_id"),
        IndexModel([("event_type", ASCENDING)], name="idx_events_type"),
        IndexModel([("timestamp", DESCENDING)], name="idx_events_timestamp"),
        IndexModel([("campaign_id", ASCENDING)], sparse=True, name="idx_events_campaign"),
        IndexModel([("lead_id", ASCENDING), ("event_type", ASCENDING)], name="idx_events_lead_type"),
    ]
    col.create_indexes(indexes)
    logger.info("✅ email_events collection indexes created")
    return col


def setup_rfqs_collection(db=None):
    """
    Ensure rfqs indexes exist. Adds lead_id index (replaces contact_id).
    """
    if db is None:
        db = get_sales_db()

    col = db["rfqs"]
    indexes = [
        IndexModel([("lead_id", ASCENDING)], name="idx_rfqs_lead_id"),
        IndexModel([("status", ASCENDING)], name="idx_rfqs_status"),
        IndexModel([("created_at", DESCENDING)], name="idx_rfqs_created"),
        IndexModel([("rfq_id", ASCENDING)], unique=True, sparse=True, name="idx_rfqs_rfq_id"),
    ]
    col.create_indexes(indexes)
    logger.info("✅ rfqs collection indexes created")
    return col


def setup_all():
    """Create all sales collection indexes."""
    db = get_sales_db()
    setup_leads_collection(db)
    setup_company_domains_collection(db)
    setup_email_events_collection(db)
    setup_rfqs_collection(db)
    logger.info("✅ All sales schemas set up")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    setup_all()
