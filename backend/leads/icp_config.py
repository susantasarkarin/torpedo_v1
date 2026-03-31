"""
ICP (Ideal Customer Profile) Configuration
==========================================
Stores and manages ICP definitions used for:
- Continuous lead generation (ICP-driven Google CSE queries)
- Filter-based lead classification (assign icp_segment to all leads)
- Per-ICP daily budget tracking in the scheduler
"""

import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_db = _client["email_automation"]
icp_configs_collection = _db["icp_configs"]

# Ensure unique index on slug
try:
    icp_configs_collection.create_index("slug", unique=True)
    icp_configs_collection.create_index("is_active")
except Exception:
    pass


# ============================================================
# DEFAULT ICP DEFINITIONS
# ============================================================

DEFAULT_ICPS = [
    {
        "slug": "bimwave",
        "name": "BIMwave Solutions",
        "description": "BIM outsourcing for Indian AEC firms targeting ISO 19650 compliance",
        "designations": [
            "BIM Manager", "BIM Coordinator", "Head of BIM", "Project Architect",
            "CAD Manager", "BIM Lead", "BIM Engineer", "Digital Delivery Manager",
            "Design Manager", "Associate Director", "Technical Director"
        ],
        "industries": [
            "Architecture", "Engineering", "Construction", "BIM", "AEC",
            "Infrastructure", "Civil Engineering", "Structural Engineering",
            "MEP Engineering", "Real Estate Development"
        ],
        "countries": ["India"],
        "seniority_levels": ["Director", "Manager", "VP", "Head"],
        "custom_context": 'site:linkedin.com/in/ BIM OR "Building Information Modelling" India',
        "daily_budget": 134,
        "is_active": True,
    },
    {
        "slug": "survey_fieldwork",
        "name": "Survey Fieldwork",
        "description": "Market research and survey panel provider for global mid-market researchers",
        "designations": [
            "Head of Insights", "Research Director", "VP Market Research",
            "Consumer Insights Manager", "Panel Manager", "Director of Research",
            "Head of Research", "Senior Research Manager", "Primary Research Manager",
            "Insights Director", "Market Research Manager"
        ],
        "industries": [
            "Market Research", "FMCG", "Retail", "Healthcare", "Financial Services",
            "Telecom", "Consumer Electronics", "Pharmaceuticals", "Media",
            "Consumer Goods", "Advertising"
        ],
        "countries": ["India", "United Kingdom", "Germany", "Singapore", "UAE"],
        "seniority_levels": ["Director", "VP", "C-Level", "Head"],
        "custom_context": 'site:linkedin.com/in/ "market research" OR "consumer insights" OR "panel"',
        "daily_budget": 133,
        "is_active": True,
    },
    {
        "slug": "cogentix",
        "name": "Cogentix Research",
        "description": "AI-native consumer intelligence platform for global mid-market brands",
        "designations": [
            "VP Marketing", "CMO", "Director of Marketing", "Head of Brand",
            "Marketing Director", "Chief Marketing Officer", "VP Brand",
            "Director of Consumer Insights", "Head of Marketing", "Senior Marketing Director",
            "Global Marketing Director"
        ],
        "industries": [
            "FMCG", "Retail", "Consumer Goods", "Food & Beverage", "Beauty",
            "Consumer Electronics", "Personal Care", "Household Products",
            "Apparel", "Beverage"
        ],
        "countries": ["India", "United Kingdom", "Germany", "Singapore", "UAE", "Australia"],
        "seniority_levels": ["VP", "C-Level", "Director"],
        "custom_context": 'site:linkedin.com/in/ "marketing director" OR "CMO" OR "VP marketing" FMCG OR retail',
        "daily_budget": 133,
        "is_active": True,
    },
]


# ============================================================
# HELPERS
# ============================================================

def seed_default_icps() -> int:
    """
    Seed the 3 default ICPs into the database. Idempotent — safe to call on every startup.
    Uses upsert on slug so existing customisations are preserved.

    Returns the number of ICPs upserted.
    """
    count = 0
    now = datetime.utcnow()
    for icp in DEFAULT_ICPS:
        icp_data = {**icp, "updated_at": now}
        result = icp_configs_collection.update_one(
            {"slug": icp["slug"]},
            {
                "$set": icp_data,
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        if result.upserted_id:
            count += 1
    return count


def get_active_icps() -> List[Dict[str, Any]]:
    """Return all active ICP configs, sorted by slug."""
    return list(icp_configs_collection.find({"is_active": True}, {"_id": 0}).sort("slug", 1))


def get_all_icps() -> List[Dict[str, Any]]:
    """Return all ICP configs (active and inactive)."""
    return list(icp_configs_collection.find({}, {"_id": 0}).sort("is_active", -1).sort("slug", 1))


def get_icp_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Return a single ICP config by slug, or None."""
    return icp_configs_collection.find_one({"slug": slug}, {"_id": 0})


def create_icp(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Insert a new ICP config. Raises ValueError on duplicate slug.
    Returns the created ICP dict.
    """
    slug = data.get("slug", "").strip().lower()
    if not slug:
        raise ValueError("slug is required")
    if icp_configs_collection.find_one({"slug": slug}):
        raise ValueError(f"ICP with slug '{slug}' already exists")
    now = datetime.utcnow()
    doc = {
        "slug": slug,
        "name": data.get("name", slug),
        "description": data.get("description", ""),
        "designations": data.get("designations", []),
        "industries": data.get("industries", []),
        "countries": data.get("countries", []),
        "seniority_levels": data.get("seniority_levels", []),
        "custom_context": data.get("custom_context", ""),
        "daily_budget": int(data.get("daily_budget", 100)),
        "is_active": bool(data.get("is_active", True)),
        "created_at": now,
        "updated_at": now,
    }
    icp_configs_collection.insert_one(doc)
    doc.pop("_id", None)
    return doc


def update_icp(slug: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Update an existing ICP config. Returns the updated doc or None if not found.
    Protected fields (slug, created_at) cannot be overwritten.
    """
    allowed = {
        "name", "description", "designations", "industries", "countries",
        "seniority_levels", "custom_context", "daily_budget", "is_active",
    }
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return get_icp_by_slug(slug)
    updates["updated_at"] = datetime.utcnow()
    result = icp_configs_collection.update_one({"slug": slug}, {"$set": updates})
    if result.matched_count == 0:
        return None
    return get_icp_by_slug(slug)


def soft_delete_icp(slug: str) -> bool:
    """Soft-delete by setting is_active=False. Returns True if found."""
    result = icp_configs_collection.update_one(
        {"slug": slug},
        {"$set": {"is_active": False, "updated_at": datetime.utcnow()}},
    )
    return result.matched_count > 0


# ============================================================
# ICP MATCH SCORING (for filter-based reclassification)
# ============================================================

def _match_list(value: Optional[str], candidates: List[str]) -> bool:
    """Case-insensitive substring match: True if value contains any candidate or candidate contains value."""
    if not value:
        return False
    val_lower = value.lower()
    for c in candidates:
        c_lower = c.lower()
        if c_lower in val_lower or val_lower in c_lower:
            return True
    return False


def score_lead_against_icp(lead: Dict[str, Any], icp: Dict[str, Any]) -> int:
    """
    Score a lead against an ICP using filter-based matching.
    No AI calls — pure string comparison.

    Scoring:
    - Title/designation match  → 3 pts
    - Industry match           → 2 pts
    - Country/region match     → 2 pts
    - Seniority match          → 1 pt

    Returns total score (0–8). Minimum threshold for assignment = 2.
    """
    score = 0

    # Title / designation
    title = lead.get("title") or lead.get("job_title") or ""
    if _match_list(title, icp.get("designations", [])):
        score += 3

    # Industry
    industry = (
        lead.get("company_industry")
        or lead.get("industry")
        or ""
    )
    if _match_list(industry, icp.get("industries", [])):
        score += 2

    # Country / region / location
    location = (
        lead.get("location")
        or lead.get("country")
        or lead.get("inferred_location")
        or lead.get("company_headquarters")
        or ""
    )
    if _match_list(location, icp.get("countries", [])):
        score += 2

    # Seniority
    seniority = lead.get("seniority_level") or ""
    if _match_list(seniority, icp.get("seniority_levels", [])):
        score += 1

    return score


def classify_lead_by_icp(lead: Dict[str, Any], active_icps: Optional[List[Dict[str, Any]]] = None) -> str:
    """
    Assign icp_segment to a lead using filter-based scoring.
    Returns the slug of the best-matching ICP, or 'unknown' if none scores >= 2.
    """
    if active_icps is None:
        active_icps = get_active_icps()

    if not active_icps:
        return "unknown"

    best_slug = "unknown"
    best_score = 1  # minimum threshold = 2; start at 1 so we need at least 2 to win

    for icp in active_icps:
        s = score_lead_against_icp(lead, icp)
        if s > best_score:
            best_score = s
            best_slug = icp["slug"]

    return best_slug
