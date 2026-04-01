"""
Email Construction Router
Step 7: Domain pattern cache lookup → email construction.
Step 8 (verification) removed — Gemini predicts email during enrichment.
"""

import os
import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Query
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

from .models import LeadStage, EmailStatus

load_dotenv()
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email", tags=["Email Construction"])

# ── MongoDB ──
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
_client = MongoClient(MONGO_URI)
_db = _client["email_automation"]
leads_col = _db["leads"]
domains_col = _db["company_domains"]




# ══════════════════════════════════════════════
#  EMAIL PATTERN HELPERS
# ══════════════════════════════════════════════

EMAIL_PATTERNS = [
    "{first}.{last}",
    "{first}{last}",
    "{first}{last_initial}",
    "{first_initial}{last}",
    "{first}",
    "{last}.{first}",
    "{first}_{last}",
]


def _split_name(name: str):
    """Split full name into first and last."""
    parts = name.strip().split(None, 1)
    first = parts[0].lower() if parts else ""
    last = parts[1].lower() if len(parts) > 1 else ""
    # Clean non-alpha chars
    first = re.sub(r"[^a-z]", "", first)
    last = re.sub(r"[^a-z]", "", last)
    return first, last


def _apply_pattern(pattern: str, first: str, last: str) -> str:
    """Apply email pattern template to name parts."""
    result = pattern
    result = result.replace("{first}", first)
    result = result.replace("{last}", last)
    result = result.replace("{first_initial}", first[0] if first else "")
    result = result.replace("{last_initial}", last[0] if last else "")
    return result


def _construct_email(pattern: str, name: str, domain: str) -> Optional[str]:
    """Construct email from pattern, name, and domain."""
    first, last = _split_name(name)
    if not first:
        return None
    local = _apply_pattern(pattern, first, last)
    if not local:
        return None
    return f"{local}@{domain}"


# ══════════════════════════════════════════════
#  COMPANY DOMAIN LOOKUP
# ══════════════════════════════════════════════

@router.get("/company-domains/{domain}")
async def get_domain_pattern(domain: str):
    """Get cached email pattern for a domain."""
    doc = domains_col.find_one({"domain": domain.lower()})
    if not doc:
        raise HTTPException(404, "Domain pattern not found")
    doc["_id"] = str(doc["_id"])
    return doc


# ══════════════════════════════════════════════
#  EMAIL CONSTRUCTION  (Step 7)
# ══════════════════════════════════════════════

@router.post("/construct/{lead_id}")
async def construct_email(lead_id: str):
    """
    Apply a known domain email pattern from cache if available,
    then hand off to enrich_lead where Gemini predicts the email.
    """
    lead = leads_col.find_one({"_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(404, "Lead not found")
    if not lead.get("domain"):
        raise HTTPException(400, "Lead has no domain — cannot construct email")
    if not lead.get("name"):
        raise HTTPException(400, "Lead has no name — cannot construct email")

    domain = lead["domain"].lower()
    name = lead["name"]
    cache_hit = False

    # Apply cached domain pattern if available (fast path)
    cached = domains_col.find_one({"domain": domain})
    if cached:
        email = _construct_email(cached["pattern"], name, domain)
        if email:
            domains_col.update_one({"domain": domain}, {"$inc": {"hit_count": 1}})
            leads_col.update_one(
                {"_id": ObjectId(lead_id)},
                {"$set": {"email": email, "email_status": "pattern_match", "updated_at": datetime.utcnow()}},
            )
            cache_hit = True

    # Always forward to enrichment — Gemini will predict email if still missing
    _enqueue_enrichment(lead_id)
    return {"status": "queued_for_enrichment", "cache_hit": cache_hit}


# ══════════════════════════════════════════════
#  EMAIL VERIFICATION  (Step 8)
# ══════════════════════════════════════════════

@router.post("/verify/{lead_id}")
async def verify_email(lead_id: str):
    """
    Legacy endpoint — Skrapp.io verification removed.
    Forwards directly to enrichment where Gemini predicts the email.
    Kept for API backward compatibility.
    """
    lead = leads_col.find_one({"_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(404, "Lead not found")
    _enqueue_enrichment(lead_id)
    return {"status": "forwarded_to_enrichment"}


def _try_alternate_pattern(name: str, domain: str, current_email: str) -> Optional[str]:
    """Try the next most common pattern variant."""
    first, last = _split_name(name)
    for pattern in EMAIL_PATTERNS:
        candidate = _construct_email(pattern, name, domain)
        if candidate and candidate != current_email:
            return candidate
    return None


def _enqueue_enrichment(lead_id: str):
    """Enqueue lead for AI enrichment via Celery."""
    try:
        from tasks.sales_tasks import enrich_lead
        enrich_lead.delay(lead_id)
    except Exception as e:
        logger.warning(f"Could not enqueue enrichment for {lead_id}: {e}")
