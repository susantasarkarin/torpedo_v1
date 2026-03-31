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


# 5 classification baskets — A through E
DEFAULT_ICP_SEGMENTS = [
    # ── Basket A: Survey Fieldwork ─────────────────────────────────────────
    {
        "slug": "survey_fieldwork",
        "basket_code": "A",
        "name": "Survey Fieldwork (SFW)",
        "description": "Sampling & fieldwork buyers: MR agencies, research ops, and panel-dependent study runners.",
        "criteria": {
            "industries": [
                "Market Research", "Research Agency", "Consumer Insights",
                "Data Collection", "Panel Services", "MR Technology", "Fieldwork",
            ],
            "departments": ["Research Operations", "Insights", "Data", "Field Services", "Sampling"],
            "seniority": ["VP", "Director", "Manager", "C-Suite"],
            "buying_roles": ["Decision Maker", "Influencer"],
            "company_sizes": ["Mid-Market", "Enterprise"],
            "keywords": [
                "panel", "fieldwork", "survey", "cati", "cawi", "tracker",
                "quantitative", "sample", "incidence rate", "ir rate", "respondent", "omnibus",
            ],
        },
        "color": "#065f46",
        "outreach_config": {
            "service_name": "Survey Fieldwork (SFW)",
            "value_proposition": (
                "We provide end-to-end B2B and consumer survey panels across 50+ markets — "
                "IR-guaranteed samples, live quota dashboards, and same-week turnaround "
                "so your studies hit deadline without last-minute fieldwork panic."
            ),
            "pain_points": [
                "low incidence rates blowing up fieldwork budgets and timelines",
                "slow turnaround from offshore panels killing client delivery schedules",
                "no real-time visibility on sample quality or quota progress mid-field",
            ],
            "call_to_action": "Happy to run a quick feasibility check on your next study — no commitment.",
            "sender_name": "",
            "sender_title": "Business Development, Survey Fieldwork",
        },
    },
    # ── Basket B: Cogentix Research ────────────────────────────────────────
    {
        "slug": "cogentix",
        "basket_code": "B",
        "name": "Cogentix Research",
        "description": "Brand & consumer insights buyers commissioning brand health, ad effectiveness, or NPS research.",
        "criteria": {
            "industries": [
                "FMCG", "Consumer Goods", "Retail", "Healthcare", "Pharma",
                "Media", "Fintech", "Financial Services", "Advertising Agency",
                "Brand Consulting", "CPG", "Insurance", "Telecom",
            ],
            "departments": ["Marketing", "Brand", "Consumer Insights", "Strategy", "Product", "Growth"],
            "seniority": ["VP", "C-Suite", "Director", "Manager"],
            "buying_roles": ["Decision Maker", "Influencer", "Champion"],
            "keywords": [
                "brand health", "ad effectiveness", "concept testing", "nps",
                "satisfaction", "brand tracking", "customer experience",
                "brand equity", "awareness", "consideration", "purchase intent",
            ],
        },
        "color": "#5b21b6",
        "outreach_config": {
            "service_name": "Cogentix Research",
            "value_proposition": (
                "We run brand health, ad effectiveness, and concept test studies for "
                "consumer-facing companies — fast-turn trackers with actionable dashboards "
                "so marketing and insights teams can move quickly on what the data says."
            ),
            "pain_points": [
                "brand tracking results arriving too late to influence campaign decisions",
                "no single view across brand health, ad recall, and customer satisfaction",
                "agency deliverables heavy on slides, light on actionable direction",
            ],
            "call_to_action": "Worth a 20-minute call to walk through our tracker methodology?",
            "sender_name": "",
            "sender_title": "Client Solutions, Cogentix Research",
        },
    },
    # ── Basket C: BIMwave ──────────────────────────────────────────────────
    {
        "slug": "bimwave",
        "basket_code": "C",
        "name": "BIMwave",
        "description": "AEC & built-environment buyers using or transitioning to Revit / BIM workflows.",
        "criteria": {
            "industries": [
                "Architecture", "Construction", "Engineering", "Real Estate Development",
                "Interior Design", "MEP", "Infrastructure", "BIM Services",
            ],
            "departments": ["Architecture", "Engineering", "Project Management", "Construction", "Design", "BIM"],
            "geographies": ["US", "UK", "Australia", "Canada", "Middle East", "UAE", "Saudi", "Qatar"],
            "keywords": [
                "revit", "bim", "ifc", "aec", "autocad", "navisworks", "archicad",
                "civil engineering", "structural", "mechanical engineering",
            ],
        },
        "color": "#1e40af",
        "outreach_config": {
            "service_name": "BIMwave",
            "value_proposition": (
                "We help AEC firms streamline their BIM + data workflows — "
                "automating model QA, clash detection pipelines, and cross-discipline "
                "data handovers to cut coordination overhead and delivery rework."
            ),
            "pain_points": [
                "manual clash coordination between disciplines slowing delivery",
                "slow IFC export and import cycles causing scheduling risk",
                "BIM data locked in silos across Revit, Navisworks, and the CDE",
            ],
            "call_to_action": "Could we get 20 minutes to show you what BIMwave does on a live project?",
            "sender_name": "",
            "sender_title": "Account Executive, BIMwave",
        },
    },
    # ── Basket D: Dual Fit ─────────────────────────────────────────────────
    {
        "slug": "dual_fit",
        "basket_code": "D",
        "name": "Dual Fit (SFW + Cogentix)",
        "description": "MR agencies that also commission brand research, or healthcare/pharma insights teams doing both fieldwork and brand tracking.",
        "criteria": {
            "note": "Qualifies for both Basket A (SFW) and Basket B (Cogentix). Assigned by engine when both thresholds are met.",
        },
        "color": "#0e7490",
        "outreach_config": {
            "service_name": "Survey Fieldwork & Cogentix Research",
            "value_proposition": (
                "We serve both sides of the research equation — panel & sampling capacity "
                "through SFW, and brand tracking / consumer insights through Cogentix Research — "
                "so you get end-to-end coverage without managing two vendor relationships."
            ),
            "pain_points": [
                "managing separate vendors for fieldwork and brand research creates coordination overhead",
                "inconsistent sampling methodology between trackers and ad-hoc studies",
                "no single partner accountable across both operational and strategic research needs",
            ],
            "call_to_action": "Open to a joint capabilities call covering both our fieldwork and insights offering?",
            "sender_name": "",
            "sender_title": "Strategic Accounts",
        },
    },
    # ── Basket E: Nurture ──────────────────────────────────────────────────
    {
        "slug": "nurture",
        "basket_code": "E",
        "name": "Nurture / Unqualified",
        "description": "Leads that do not meet basket criteria: wrong industry, low seniority with no buying signal, or predicted email with confidence < 50%.",
        "criteria": {
            "note": "Fallback basket when A/B/C/D thresholds are not met, or email_status=predicted with confidence_score < 50.",
        },
        "color": "#6b7280",
        "outreach_config": {
            "service_name": "our services",
            "value_proposition": "We help research and AEC teams work faster and smarter.",
            "pain_points": [],
            "call_to_action": "Would you be open to a quick call to explore if we can help?",
            "sender_name": "",
            "sender_title": "",
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

    # Always upsert defaults so schema/outreach_config stays current
    from datetime import datetime
    now = datetime.utcnow()
    for seg in DEFAULT_ICP_SEGMENTS:
        col.update_one(
            {"slug": seg["slug"]},
            {
                "$set": {**seg, "updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
    logger.info("✅ icp_segments upserted with current defaults")

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
