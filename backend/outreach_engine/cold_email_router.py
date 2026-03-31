"""
COLD EMAIL ROUTING ENGINE
==========================

Routes cold outreach emails to specific sender mailboxes based on the
service type / category of the lead.

Routing Rules:
    - Data Services leads → indira@surveyfieldwork.com
    - Consumer Insights leads → meera@cogentixresearch.com
    - Default / Unclassified → round-robin from available mailboxes

Service classification is based on:
    - Campaign tags/type
    - Lead's company industry
    - Lead's title / department
    - Manual override via lead_service_type field
"""

import logging
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)


# ============== ROUTING CONFIGURATION ==============

# Service type to sender email mapping
SERVICE_MAILBOX_ROUTING = {
    "data_services": {
        "sender_email": "indira@surveyfieldwork.com",
        "sender_name": "Indira",
        "description": "Data collection, fieldwork, surveys, data services",
    },
    "consumer_insights": {
        "sender_email": "meera@cogentixresearch.com",
        "sender_name": "Meera",
        "description": "Consumer insights, market research, qualitative research",
    },
    "bimwave": {
        "sender_email": "susanta@bimwaveconsultants.com",
        "sender_name": "Susanta",
        "description": "BIM, architecture, construction, AEC industry",
    },
}

# Default mailbox if no service type matches
DEFAULT_MAILBOX = "indira@surveyfieldwork.com"

# ICP basket → service type mapping
BASKET_SERVICE_MAP = {
    "A": "data_services",
    "B": "consumer_insights",
    "C": "bimwave",
}

# Keywords for auto-classifying leads into service types
DATA_SERVICES_KEYWORDS = {
    "industries": [
        "data collection", "fieldwork", "survey", "panel", "sampling",
        "quantitative research", "data services", "data analytics",
        "polling", "market measurement", "tracking study",
    ],
    "titles": [
        "data", "operations", "fieldwork", "project manager",
        "research operations", "survey", "sample",
    ],
    "campaign_tags": [
        "data_services", "fieldwork", "surveys", "data", "quantitative",
    ],
}

CONSUMER_INSIGHTS_KEYWORDS = {
    "industries": [
        "consumer insights", "market research", "qualitative",
        "focus group", "ethnography", "brand strategy", "consumer behavior",
        "advertising research", "media research", "shopper insights",
        "innovation research", "product research",
    ],
    "titles": [
        "insights", "consumer", "brand", "marketing research",
        "qualitative", "strategy", "innovation",
    ],
    "campaign_tags": [
        "consumer_insights", "insights", "qualitative", "brand",
        "market_research",
    ],
}

BIMWAVE_KEYWORDS = {
    "industries": [
        "bim", "building information modeling", "architecture", "construction",
        "aec", "civil engineering", "structural engineering", "mep",
        "real estate development", "facilities management", "infrastructure",
        "urban planning", "interior design", "landscape architecture",
    ],
    "titles": [
        "bim", "architect", "project manager", "construction manager",
        "civil engineer", "structural engineer", "facility manager",
        "mep engineer", "revit", "autocad", "design manager",
        "site manager", "quantity surveyor",
    ],
    "campaign_tags": [
        "bimwave", "bim", "architecture", "construction", "aec",
    ],
}


def classify_service_type(
    lead_data: Dict[str, Any],
    campaign_data: Optional[Dict[str, Any]] = None
) -> str:
    """
    Classify a lead into a service type for email routing.

    Priority:
    1. ICP basket field (classification_basket A/B/C)
    2. Manual override (lead_service_type field)
    3. Campaign tags
    4. Lead's industry keywords
    5. Lead's title keywords
    6. Default to data_services

    Returns: 'data_services', 'consumer_insights', or 'bimwave'
    """
    # 1. ICP basket → deterministic routing
    basket = lead_data.get("classification_basket", "").upper()
    if basket in BASKET_SERVICE_MAP:
        return BASKET_SERVICE_MAP[basket]

    # 2. Manual override
    manual = lead_data.get("lead_service_type", "").strip().lower()
    if manual in SERVICE_MAILBOX_ROUTING:
        return manual

    def _match_keywords(text: str, keyword_list: list) -> bool:
        text_lower = text.lower()
        return any(kw in text_lower for kw in keyword_list)

    # 3. Campaign tags
    if campaign_data:
        campaign_tags = campaign_data.get("tags", [])
        campaign_type = campaign_data.get("campaign_type", "").lower()
        campaign_text = " ".join(campaign_tags) + " " + campaign_type

        if _match_keywords(campaign_text, BIMWAVE_KEYWORDS["campaign_tags"]):
            return "bimwave"
        if _match_keywords(campaign_text, CONSUMER_INSIGHTS_KEYWORDS["campaign_tags"]):
            return "consumer_insights"
        if _match_keywords(campaign_text, DATA_SERVICES_KEYWORDS["campaign_tags"]):
            return "data_services"

    # 4. Industry keywords
    industry = (
        lead_data.get("company_industry", "") or
        lead_data.get("industry", "") or
        ""
    )
    if _match_keywords(industry, BIMWAVE_KEYWORDS["industries"]):
        return "bimwave"
    if _match_keywords(industry, CONSUMER_INSIGHTS_KEYWORDS["industries"]):
        return "consumer_insights"
    if _match_keywords(industry, DATA_SERVICES_KEYWORDS["industries"]):
        return "data_services"

    # 5. Title keywords
    title = lead_data.get("title", "") or ""
    if _match_keywords(title, BIMWAVE_KEYWORDS["titles"]):
        return "bimwave"
    if _match_keywords(title, CONSUMER_INSIGHTS_KEYWORDS["titles"]):
        return "consumer_insights"
    if _match_keywords(title, DATA_SERVICES_KEYWORDS["titles"]):
        return "data_services"

    # 6. Default
    return "data_services"


def get_sender_for_lead(
    lead_data: Dict[str, Any],
    campaign_data: Optional[Dict[str, Any]] = None
) -> Tuple[str, str, str]:
    """
    Get the appropriate sender email, name, and service type for a lead.
    
    Returns: (sender_email, sender_name, service_type)
    """
    service_type = classify_service_type(lead_data, campaign_data)
    
    routing_config = SERVICE_MAILBOX_ROUTING.get(service_type)
    
    if routing_config:
        logger.info(
            f"Routing lead {lead_data.get('email', '?')} to "
            f"{routing_config['sender_email']} ({service_type})"
        )
        return (
            routing_config["sender_email"],
            routing_config["sender_name"],
            service_type
        )
    
    # Fallback
    logger.warning(f"No routing config for service_type={service_type}, using default")
    return DEFAULT_MAILBOX, "Indira", "data_services"


def get_routing_summary() -> Dict[str, Any]:
    """
    Get a summary of the routing configuration for admin display.
    """
    return {
        "routes": {
            service_type: {
                "sender_email": config["sender_email"],
                "sender_name": config["sender_name"],
                "description": config["description"],
            }
            for service_type, config in SERVICE_MAILBOX_ROUTING.items()
        },
        "default_mailbox": DEFAULT_MAILBOX,
        "classification_keywords": {
            "data_services": DATA_SERVICES_KEYWORDS,
            "consumer_insights": CONSUMER_INSIGHTS_KEYWORDS,
        }
    }
