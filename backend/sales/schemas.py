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


DEFAULT_ICP_SEGMENTS = [
    {
        "slug": "bimwave",
        "name": "BIMwave",
        "description": "AEC / BIM / Construction-tech companies using Revit, IFC or BIM workflows",
        "criteria": {
            "keywords": ["BIM", "Revit", "IFC", "AEC", "construction tech", "architecture"],
            "industries": ["Architecture", "Construction", "Civil Engineering", "Real Estate Tech"],
            "company_sizes": ["11-50", "51-200"],
        },
        "color": "#1e40af",
        "outreach_config": {
            "service_name": "BIMwave",
            "value_proposition": (
                "We help AEC firms consolidate their BIM + data workflows — "
                "cutting coordination overhead and rework by automating model QA, "
                "clash detection pipelines, and cross-discipline data handovers."
            ),
            "pain_points": [
                "manual clash coordination between disciplines",
                "slow IFC export / import cycles holding up delivery",
                "BIM data locked in silos across Revit, Navisworks, and the CDE",
            ],
            "call_to_action": "Could we get 20 minutes to show you what BIMwave does on a real project?",
            "sender_name": "",
            "sender_title": "Account Executive, BIMwave",
        },
    },
    {
        "slug": "survey_fieldwork",
        "name": "Survey Fieldwork",
        "description": "Market research agencies running online or offline fieldwork surveys",
        "criteria": {
            "keywords": ["market research", "survey", "fieldwork", "panel", "CATI", "data collection"],
            "industries": ["Market Research", "Data Collection", "Research Services"],
            "company_sizes": ["51-200", "201-1000"],
        },
        "color": "#065f46",
        "outreach_config": {
            "service_name": "Survey Fieldwork",
            "value_proposition": (
                "We provide end-to-end B2B and consumer survey panels across 50+ markets — "
                "fast turnaround, IR-guaranteed samples, and a live dashboard so you "
                "can monitor quotas in real time without chasing your fieldwork vendor."
            ),
            "pain_points": [
                "low incidence rates blowing up fieldwork budgets",
                "slow turnaround from offshore panels killing client timelines",
                "lack of transparency on sample quality mid-field",
            ],
            "call_to_action": "Happy to run a quick feasibility on your next study — no commitment needed.",
            "sender_name": "",
            "sender_title": "Business Development, Survey Fieldwork",
        },
    },
    {
        "slug": "cogentix",
        "name": "Cogentix",
        "description": "B2B SaaS companies seeking sales automation and outreach solutions",
        "criteria": {
            "keywords": ["SaaS", "sales automation", "outreach", "B2B", "CRM", "lead generation"],
            "industries": ["Technology", "Software", "SaaS", "B2B Services"],
            "company_sizes": ["11-50", "51-200", "201-1000"],
        },
        "color": "#5b21b6",
        "outreach_config": {
            "service_name": "Cogentix",
            "value_proposition": (
                "We help B2B sales teams build and run AI-powered outreach pipelines — "
                "from lead discovery and email construction to personalised drafts and "
                "reply tracking — without adding headcount."
            ),
            "pain_points": [
                "reps spending 40%+ of their day on prospecting instead of selling",
                "generic outreach getting buried in crowded inboxes",
                "no visibility into which leads are actually engaging",
            ],
            "call_to_action": "Worth a 15-minute call to see if this fits your current stack?",
            "sender_name": "",
            "sender_title": "Growth, Cogentix",
        },
    },
]


def setup_icp_segments_collection(db=None):
    """
    Create indexes for icp_segments collection and seed defaults if empty.
    """
    if db is None:
        db = get_sales_db()

    col = db["icp_segments"]
    indexes = [
        IndexModel([("slug", ASCENDING)], unique=True, name="idx_icp_slug"),
    ]
    col.create_indexes(indexes)

    # Seed defaults if collection is empty
    if col.count_documents({}) == 0:
        from datetime import datetime
        now = datetime.utcnow()
        for seg in DEFAULT_ICP_SEGMENTS:
            col.update_one(
                {"slug": seg["slug"]},
                {"$setOnInsert": {**seg, "created_at": now}},
                upsert=True,
            )
        logger.info("✅ icp_segments seeded with defaults")

    # Also add icp_tags index on leads
    leads_col = db["leads"]
    try:
        leads_col.create_index([("icp_tags", ASCENDING)], name="idx_leads_icp_tags", sparse=True)
    except Exception:
        pass  # index may already exist

    logger.info("✅ icp_segments collection indexes created")
    return col


def setup_all():
    """Create all sales collection indexes."""
    db = get_sales_db()
    setup_leads_collection(db)
    setup_company_domains_collection(db)
    setup_email_events_collection(db)
    setup_rfqs_collection(db)
    setup_icp_segments_collection(db)
    logger.info("✅ All sales schemas set up")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    setup_all()
