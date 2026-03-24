"""
Email Construction & Verification Router
Step 7: Pattern lookup + email address construction.
Step 8: Email verification via skrapp.io.
"""

import os
import re
import time
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

# ── Skrapp.io ──
SKRAPP_API_KEY = os.getenv("SKRAPP_API_KEY", "")
SKRAPP_BASE = "https://app.skrapp.io/api/v2"

# ── Rate limiter (simple token bucket) ──
_last_skrapp_call = 0.0
_SKRAPP_MIN_INTERVAL = 0.1  # max 10 req/sec


def _rate_limit_skrapp():
    """Enforce max 10 requests/second to skrapp.io."""
    global _last_skrapp_call
    now = time.time()
    elapsed = now - _last_skrapp_call
    if elapsed < _SKRAPP_MIN_INTERVAL:
        time.sleep(_SKRAPP_MIN_INTERVAL - elapsed)
    _last_skrapp_call = time.time()


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
    Construct email for a lead using domain pattern cache or skrapp.io.
    Lead must be in stage=email_construction.
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
    first, last = _split_name(name)

    # Step 1 — Check company_domains cache
    cached = domains_col.find_one({"domain": domain})

    if cached:
        pattern = cached["pattern"]
        email = _construct_email(pattern, name, domain)
        if email:
            domains_col.update_one({"domain": domain}, {"$inc": {"hit_count": 1}})
            leads_col.update_one(
                {"_id": ObjectId(lead_id)},
                {"$set": {"email": email, "updated_at": datetime.utcnow()}},
            )
            # Enqueue verification
            _enqueue_verification(lead_id)
            return {"email": email, "pattern": pattern, "source": "cache"}

    # Step 2 — Call skrapp.io for pattern
    if not SKRAPP_API_KEY:
        # Fallback: try common patterns without API
        for pattern in EMAIL_PATTERNS:
            email = _construct_email(pattern, name, domain)
            if email:
                leads_col.update_one(
                    {"_id": ObjectId(lead_id)},
                    {"$set": {"email": email, "email_status": "pending", "updated_at": datetime.utcnow()}},
                )
                _enqueue_verification(lead_id)
                return {"email": email, "pattern": pattern, "source": "guess"}
        raise HTTPException(400, "Could not construct email — no name/domain info")

    _rate_limit_skrapp()
    import httpx
    try:
        resp = httpx.post(
            f"{SKRAPP_BASE}/email-finder",
            json={"domain": domain, "firstName": first, "lastName": last},
            headers={"Authorization": f"Bearer {SKRAPP_API_KEY}"},
            timeout=15,
        )
        data = resp.json()
    except Exception as e:
        logger.error(f"Skrapp email-finder failed: {e}")
        leads_col.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {"email_status": "invalid", "stage": "new", "updated_at": datetime.utcnow()}},
        )
        raise HTTPException(502, f"Skrapp API error: {e}")

    if resp.status_code == 200 and data.get("email"):
        email = data["email"].lower().strip()
        pattern = data.get("pattern", "{first}.{last}")

        # Store pattern in cache
        domains_col.update_one(
            {"domain": domain},
            {"$set": {
                "domain": domain,
                "pattern": pattern,
                "source": "skrapp",
                "verified_at": datetime.utcnow(),
            }, "$inc": {"hit_count": 1}},
            upsert=True,
        )

        leads_col.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {"email": email, "updated_at": datetime.utcnow()}},
        )
        _enqueue_verification(lead_id)
        return {"email": email, "pattern": pattern, "source": "skrapp"}
    else:
        leads_col.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {"email_status": "invalid", "stage": "new", "updated_at": datetime.utcnow()}},
        )
        return {"error": "Could not find email", "lead_id": lead_id}


# ══════════════════════════════════════════════
#  EMAIL VERIFICATION  (Step 8)
# ══════════════════════════════════════════════

@router.post("/verify/{lead_id}")
async def verify_email(lead_id: str):
    """
    Verify a lead's email via skrapp.io.
    On valid: stage → verified, enqueue enrichment.
    On invalid: try alternate pattern, then flag for rep.
    """
    lead = leads_col.find_one({"_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(404, "Lead not found")

    email = lead.get("email")
    if not email:
        raise HTTPException(400, "Lead has no email to verify")

    result = _verify_with_skrapp(email)

    if result == "valid":
        leads_col.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {
                "email_status": "verified",
                "stage": "verified",
                "updated_at": datetime.utcnow(),
            }},
        )
        _enqueue_enrichment(lead_id)
        return {"status": "verified", "email": email}

    # Invalid — try alternate pattern (one retry)
    domain = lead.get("domain", "")
    name = lead.get("name", "")
    if domain and name:
        alternate = _try_alternate_pattern(name, domain, email)
        if alternate:
            alt_result = _verify_with_skrapp(alternate)
            if alt_result == "valid":
                leads_col.update_one(
                    {"_id": ObjectId(lead_id)},
                    {"$set": {
                        "email": alternate,
                        "email_status": "verified",
                        "stage": "verified",
                        "updated_at": datetime.utcnow(),
                    }},
                )
                _enqueue_enrichment(lead_id)
                return {"status": "verified", "email": alternate, "note": "alternate pattern"}

    # All attempts failed
    leads_col.update_one(
        {"_id": ObjectId(lead_id)},
        {"$set": {
            "email_status": "invalid",
            "stage": "new",
            "updated_at": datetime.utcnow(),
        }},
    )

    # In-app notification for rep
    _db["notifications"].insert_one({
        "type": "email_verification_failed",
        "title": f"Could not verify email for {lead.get('name', '')} at {lead.get('company', '')}",
        "message": f"Email {email} could not be verified. Please review.",
        "lead_id": lead_id,
        "read": False,
        "created_at": datetime.utcnow(),
    })

    return {"status": "invalid", "email": email}


def _verify_with_skrapp(email: str) -> str:
    """Call skrapp.io verify. Returns 'valid' or 'invalid'."""
    if not SKRAPP_API_KEY:
        # Without API key, accept as-is
        return "valid"

    _rate_limit_skrapp()
    import httpx
    try:
        resp = httpx.post(
            f"{SKRAPP_BASE}/verify",
            json={"email": email},
            headers={"Authorization": f"Bearer {SKRAPP_API_KEY}"},
            timeout=15,
        )
        data = resp.json()
        if data.get("status") == "valid":
            return "valid"
        return "invalid"
    except Exception as e:
        logger.error(f"Skrapp verify error: {e}")
        return "invalid"


def _try_alternate_pattern(name: str, domain: str, current_email: str) -> Optional[str]:
    """Try the next most common pattern variant."""
    first, last = _split_name(name)
    for pattern in EMAIL_PATTERNS:
        candidate = _construct_email(pattern, name, domain)
        if candidate and candidate != current_email:
            return candidate
    return None


def _enqueue_verification(lead_id: str):
    """Enqueue lead for email verification via Celery."""
    try:
        from tasks.sales_tasks import verify_lead_email
        verify_lead_email.delay(lead_id)
    except Exception as e:
        logger.warning(f"Could not enqueue verification for {lead_id}: {e}")


def _enqueue_enrichment(lead_id: str):
    """Enqueue lead for AI enrichment via Celery."""
    try:
        from tasks.sales_tasks import enrich_lead
        enrich_lead.delay(lead_id)
    except Exception as e:
        logger.warning(f"Could not enqueue enrichment for {lead_id}: {e}")
