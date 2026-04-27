"""
Email Patterns Discovery Router
Analyzes mail_pool to discover email patterns by domain
Implements tiered pattern discovery: Database → Website → Hunter.io → Guess
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/email-patterns",
    tags=["email-patterns"]
)

# MongoDB connections
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
mongo_client = MongoClient(MONGO_URI)

# Databases
email_db = mongo_client["email_automation"]

# Collections
email_patterns_collection = email_db["email_patterns"]
mail_pool_collection = email_db["mail_pool"]
company_cache_collection = email_db["company_cache"]
leads_enriched_collection = email_db["leads_enriched"]


# ============== MODELS ==============

class EmailPattern(BaseModel):
    """Email pattern for a domain"""
    domain: str
    pattern: str  # e.g., "firstname.lastname@domain.com"
    confidence: float = Field(ge=0, le=1)
    sample_count: int
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class PatternSource(str):
    """Source of pattern discovery"""
    DATABASE = "database"
    WEBSITE = "website"
    HUNTER = "hunter"
    GUESS = "guess"


# ============== UTILITY FUNCTIONS ==============

def ensure_indexes():
    """Create necessary indexes"""
    try:
        email_patterns_collection.create_index([("domain", 1)], unique=True)
        email_patterns_collection.create_index([("confidence", -1)])
        email_patterns_collection.create_index([("last_updated", -1)])
        logger.info("Indexes ensured for email_patterns")
    except Exception as e:
        logger.warning(f"Failed to create indexes: {e}")


ensure_indexes()


# ============== ENDPOINTS ==============

@router.get("/stats", summary="Get email pattern discovery statistics")
async def get_pattern_stats() -> Dict:
    """
    Get statistics on discovered email patterns
    - Total domains analyzed
    - High confidence patterns
    - Pattern sources breakdown
    """
    try:
        total_domains = email_patterns_collection.count_documents({})
        
        high_confidence = email_patterns_collection.count_documents(
            {"confidence": {"$gte": 0.8}}
        )
        
        medium_confidence = email_patterns_collection.count_documents(
            {"confidence": {"$gte": 0.5, "$lt": 0.8}}
        )
        
        # Get average confidence
        stats = list(email_patterns_collection.aggregate([
            {
                "$group": {
                    "_id": None,
                    "avg_confidence": {"$avg": "$confidence"},
                    "avg_sample_count": {"$avg": "$sample_count"},
                    "total_samples": {"$sum": "$sample_count"}
                }
            }
        ]))
        
        if stats:
            stat = stats[0]
            return {
                "total_domains": total_domains,
                "high_confidence": high_confidence,
                "medium_confidence": medium_confidence,
                "low_confidence": total_domains - high_confidence - medium_confidence,
                "avg_confidence": round(stat.get("avg_confidence", 0), 2),
                "avg_sample_count": round(stat.get("avg_sample_count", 0), 1),
                "total_samples_analyzed": stat.get("total_samples", 0)
            }
        
        return {
            "total_domains": total_domains,
            "high_confidence": high_confidence,
            "medium_confidence": medium_confidence,
            "low_confidence": total_domains - high_confidence - medium_confidence,
            "avg_confidence": 0,
            "avg_sample_count": 0,
            "total_samples_analyzed": 0
        }
    except Exception as e:
        logger.error(f"Error fetching pattern stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-mail-pool", summary="Discover patterns from mail pool")
async def analyze_mail_pool(
    limit: int = Query(1000, ge=100, le=10000),
    min_samples: int = Query(3, ge=1, le=50, description="Minimum emails per domain to establish pattern")
) -> Dict:
    """
    Analyze mail pool to discover email patterns
    One-time batch job that examines all emails and extracts patterns
    
    Process:
    1. Get all unique domains from mail_pool sender emails
    2. For each domain, analyze 3+ email addresses to find pattern
    3. Store patterns with confidence scores
    4. Report on discovery results
    """
    try:
        from backend.leads.email_pattern_system import EmailPatternSystem
        
        system = EmailPatternSystem()
        
        # Get unprocessed emails (up to limit)
        emails = list(mail_pool_collection.find(
            {"processed_for_patterns": {"$ne": True}}
        ).limit(limit))
        
        if not emails:
            return {
                "analyzed": 0,
                "new_patterns": 0,
                "message": "No unprocessed emails found"
            }
        
        # Build domain -> emails map
        domain_emails = {}
        for email in emails:
            sender = email.get("sender", "").lower()
            if "@" in sender:
                domain = sender.split("@")[1]
                if domain not in domain_emails:
                    domain_emails[domain] = []
                domain_emails[domain].append(sender)
        
        # Discover patterns
        new_patterns = 0
        updated_patterns = 0
        
        for domain, senders in domain_emails.items():
            if len(senders) < min_samples:
                continue
            
            # Simple pattern extraction - look for common format
            # Count formats: firstname.lastname, firstnamelastname, first.last, etc.
            pattern_format = discover_pattern_format(senders)
            confidence = len(senders) / 10.0  # Simple confidence based on samples
            confidence = min(confidence, 1.0)
            
            existing = email_patterns_collection.find_one({"domain": domain})
            
            if existing:
                # Update if new confidence is higher
                if confidence > existing.get("confidence", 0):
                    email_patterns_collection.update_one(
                        {"domain": domain},
                        {
                            "$set": {
                                "pattern": pattern_format,
                                "confidence": confidence,
                                "sample_count": len(senders),
                                "last_updated": datetime.utcnow()
                            }
                        }
                    )
                    updated_patterns += 1
            else:
                # Insert new pattern
                email_patterns_collection.insert_one({
                    "domain": domain,
                    "pattern": pattern_format,
                    "confidence": confidence,
                    "sample_count": len(senders),
                    "created_at": datetime.utcnow(),
                    "last_updated": datetime.utcnow()
                })
                new_patterns += 1
        
        # Mark emails as processed
        email_ids = [e["_id"] for e in emails]
        mail_pool_collection.update_many(
            {"_id": {"$in": email_ids}},
            {"$set": {"processed_for_patterns": True}}
        )
        
        return {
            "analyzed": len(emails),
            "unique_domains": len(domain_emails),
            "domains_with_pattern": sum(1 for s in domain_emails.values() if len(s) >= min_samples),
            "new_patterns": new_patterns,
            "updated_patterns": updated_patterns,
            "message": f"Discovered {new_patterns} new patterns and updated {updated_patterns} existing patterns"
        }
    except ImportError:
        # If EmailPatternSystem not available, use fallback
        try:
            emails = list(mail_pool_collection.find(
                {"processed_for_patterns": {"$ne": True}}
            ).limit(limit))
            
            domain_emails = {}
            for email in emails:
                sender = email.get("sender", "").lower()
                if "@" in sender:
                    domain = sender.split("@")[1]
                    if domain not in domain_emails:
                        domain_emails[domain] = []
                    domain_emails[domain].append(sender)
            
            new_patterns = 0
            for domain, senders in domain_emails.items():
                if len(senders) < min_samples:
                    continue
                
                pattern_format = discover_pattern_format(senders)
                confidence = min(len(senders) / 10.0, 1.0)
                
                existing = email_patterns_collection.find_one({"domain": domain})
                if not existing:
                    email_patterns_collection.insert_one({
                        "domain": domain,
                        "pattern": pattern_format,
                        "confidence": confidence,
                        "sample_count": len(senders),
                        "created_at": datetime.utcnow(),
                        "last_updated": datetime.utcnow()
                    })
                    new_patterns += 1
            
            email_ids = [e["_id"] for e in emails]
            mail_pool_collection.update_many(
                {"_id": {"$in": email_ids}},
                {"$set": {"processed_for_patterns": True}}
            )
            
            return {
                "analyzed": len(emails),
                "unique_domains": len(domain_emails),
                "domains_with_pattern": sum(1 for s in domain_emails.values() if len(s) >= min_samples),
                "new_patterns": new_patterns,
                "updated_patterns": 0,
                "message": f"Discovered {new_patterns} new patterns"
            }
        except Exception as e:
            logger.error(f"Error in pattern analysis: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/build-email/{domain}/{name}", summary="Build email address from pattern")
async def build_email(domain: str, name: str) -> Dict:
    """
    Build a likely email address using discovered pattern
    
    For example: domain=google.com, name="John Smith"
    Returns: john.smith@google.com (if that's the pattern)
    """
    try:
        domain = domain.lower().strip()
        name = name.lower().strip()
        
        pattern = email_patterns_collection.find_one({"domain": domain})
        
        if not pattern:
            # Fallback to common pattern
            first = name.split()[0] if name else ""
            last = name.split()[1] if len(name.split()) > 1 else ""
            likely_email = f"{first}.{last}@{domain}" if last else f"{first}@{domain}"
            
            return {
                "domain": domain,
                "name": name,
                "email": likely_email,
                "pattern": "firstname.lastname (fallback)",
                "confidence": 0.5,
                "note": "No pattern found, using common format"
            }
        
        # Build email from pattern
        pattern_str = pattern.get("pattern", "firstname.lastname")
        names = name.split()
        firstname = names[0] if names else ""
        lastname = names[1] if len(names) > 1 else ""
        
        email = generate_email_from_pattern(
            pattern_str, firstname, lastname, domain
        )
        
        return {
            "domain": domain,
            "name": name,
            "email": email,
            "pattern": pattern_str,
            "confidence": pattern.get("confidence", 0.5),
            "sample_count": pattern.get("sample_count", 0)
        }
    except Exception as e:
        logger.error(f"Error building email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list", summary="List discovered email patterns")
async def list_patterns(
    min_confidence: float = Query(0.5, ge=0, le=1),
    limit: int = Query(100, ge=1, le=1000),
    sort_by: str = Query("confidence", enum=["confidence", "sample_count", "domain"])
) -> Dict:
    """
    List discovered email patterns with filters
    """
    try:
        sort_order = -1 if sort_by == "confidence" else 1
        
        patterns = list(email_patterns_collection.find(
            {"confidence": {"$gte": min_confidence}}
        ).sort(sort_by, sort_order).limit(limit))
        
        return {
            "total": len(patterns),
            "min_confidence": min_confidence,
            "patterns": [
                {
                    "domain": p.get("domain"),
                    "pattern": p.get("pattern"),
                    "confidence": p.get("confidence", 0),
                    "sample_count": p.get("sample_count", 0),
                    "last_updated": p.get("last_updated", datetime.utcnow()).isoformat()
                }
                for p in patterns
            ]
        }
    except Exception as e:
        logger.error(f"Error listing patterns: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{domain}", summary="Get email pattern for domain")
async def get_pattern(domain: str) -> Dict:
    """
    Get the discovered email pattern for a domain
    Returns confidence level and sample emails
    """
    try:
        domain = domain.lower().strip()
        
        pattern = email_patterns_collection.find_one({"domain": domain})
        
        if not pattern:
            return {
                "domain": domain,
                "found": False,
                "message": "No pattern discovered yet. Analyze mail pool to discover patterns."
            }
        
        # Get sample emails with this domain
        samples = list(mail_pool_collection.find(
            {"sender": {"$regex": f"@{domain}$", "$options": "i"}},
            {"sender": 1, "sender_name": 1}
        ).limit(5))
        
        return {
            "domain": domain,
            "found": True,
            "pattern": pattern.get("pattern"),
            "confidence": pattern.get("confidence", 0),
            "sample_count": pattern.get("sample_count", 0),
            "last_updated": pattern.get("last_updated", datetime.utcnow()).isoformat(),
            "sample_emails": [
                {
                    "email": s.get("sender"),
                    "name": s.get("sender_name")
                }
                for s in samples
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching pattern: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Scan AI database for email patterns ────────────────────────────────────

@router.post("/scan-ai-database", summary="Discover email patterns from AI-sourced leads")
async def scan_ai_database(limit: int = Query(10000, ge=1, le=50000)) -> Dict:
    """
    Scan leads_enriched for AI-sourced leads that already have emails.
    Group them by domain and run discover_pattern_format() to infer patterns.
    Only upserts a pattern if the new confidence is higher than the stored one.
    """
    try:
        cursor = leads_enriched_collection.find(
            {
                "email": {"$exists": True, "$nin": [None, ""]},
            },
            {"email": 1, "company_domain": 1},
        ).limit(limit)

        # Group emails by domain
        domain_emails: Dict[str, List[str]] = {}
        for doc in cursor:
            email = doc.get("email", "").strip().lower()
            if "@" not in email:
                continue
            domain = email.split("@")[1]
            domain_emails.setdefault(domain, []).append(email)

        patterns_upserted = 0
        patterns_skipped = 0
        processed_domains = []

        for domain, emails in domain_emails.items():
            if len(emails) < 2:
                # Need at least 2 samples for a reliable pattern
                patterns_skipped += 1
                continue

            new_pattern = discover_pattern_format(emails)
            if new_pattern in ("unknown", "multiple.parts"):
                patterns_skipped += 1
                continue

            # Confidence proportional to sample count, capped at 0.9
            new_confidence = min(0.9, 0.4 + len(emails) * 0.05)

            existing = email_patterns_collection.find_one({"domain": domain}, {"confidence": 1})
            if existing and existing.get("confidence", 0) >= new_confidence:
                patterns_skipped += 1
                continue

            email_patterns_collection.update_one(
                {"domain": domain},
                {
                    "$set": {
                        "pattern": new_pattern,
                        "confidence": new_confidence,
                        "sample_count": len(emails),
                        "source": "ai_database_scan",
                        "last_updated": datetime.utcnow(),
                    }
                },
                upsert=True,
            )
            patterns_upserted += 1
            processed_domains.append({"domain": domain, "pattern": new_pattern, "samples": len(emails)})

        return {
            "domains_scanned": len(domain_emails),
            "patterns_upserted": patterns_upserted,
            "patterns_skipped": patterns_skipped,
            "top_domains": processed_domains[:20],
            "message": f"Scanned {len(domain_emails)} domains, upserted {patterns_upserted} patterns",
        }
    except Exception as e:
        logger.error(f"Error scanning AI database: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Apply patterns to bounced + missing-email leads ────────────────────────

@router.post("/apply-to-bounced-and-missing", summary="Retry email patterns for bounced/missing leads")
async def apply_to_bounced_and_missing(limit: int = Query(500, ge=1, le=5000)) -> Dict:
    """
    Two-pass pipeline:

    Pass 1 — Bounced leads:
        Find leads where email_status=Bounced and company_domain is set.
        Call try_alternate_pattern() to get a plausible alternate email.
        Update email, set email_source='pattern_reapplied', clear bounce flags.

    Pass 2 — Missing-email leads:
        Find leads where email is null/missing and company_domain is set.
        Call get_pattern() + build_email() to generate an email.
        Set email_source='pattern_applied'; re-enroll in outreach if ICP A-D.
    """
    try:
        try:
            from leads.email_pattern_system import get_pattern_system
        except ImportError:
            from backend.leads.email_pattern_system import get_pattern_system

        pattern_sys = get_pattern_system()

        bounced_updated = 0
        bounced_skipped = 0
        missing_updated = 0
        missing_skipped = 0

        # ── Pass 1: Bounced emails ────────────────────────────────────────
        bounced_cursor = leads_enriched_collection.find(
            {
                "email_status": "Bounced",
                "company_domain": {"$exists": True, "$ne": None, "$ne": ""},
            }
        ).limit(limit // 2)

        for lead in bounced_cursor:
            current_email = lead.get("email", "")
            domain = lead.get("company_domain", "").strip().lower()
            if not current_email or not domain:
                bounced_skipped += 1
                continue

            alternate = pattern_sys.try_alternate_pattern(domain, current_email)
            if not alternate:
                bounced_skipped += 1
                continue

            leads_enriched_collection.update_one(
                {"_id": lead["_id"]},
                {
                    "$set": {
                        "email": alternate["email"],
                        "email_source": "pattern_reapplied",
                        "email_pattern_used": alternate["pattern"],
                        "email_pattern_confidence": alternate["confidence"],
                        "email_status": None,
                        "bounce_cleared_at": datetime.utcnow(),
                        "previous_bounced_email": current_email,
                    },
                    "$unset": {
                        "high_bounce_risk": "",
                        "pattern_blacklisted": "",
                    },
                },
            )
            bounced_updated += 1

        # ── Pass 2: Missing emails ────────────────────────────────────────
        missing_cursor = leads_enriched_collection.find(
            {
                "$or": [
                    {"email": {"$exists": False}},
                    {"email": None},
                    {"email": ""},
                ],
                "company_domain": {"$exists": True, "$ne": None, "$ne": ""},
                "first_name": {"$exists": True, "$ne": ""},
            }
        ).limit(limit // 2)

        for lead in missing_cursor:
            domain = lead.get("company_domain", "").strip().lower()
            first_name = lead.get("first_name", "").strip().lower()
            last_name = lead.get("last_name", "").strip().lower()
            if not domain or not first_name:
                missing_skipped += 1
                continue

            pattern_doc = pattern_sys.get_pattern(domain)
            if not pattern_doc or pattern_doc.get("confidence", 0) < 0.5:
                missing_skipped += 1
                continue

            built = pattern_sys.build_email(domain, first_name, last_name)
            if not built:
                missing_skipped += 1
                continue

            update: Dict = {
                "email": built,
                "email_source": "pattern_applied",
                "email_pattern_used": pattern_doc.get("pattern"),
                "email_pattern_confidence": pattern_doc.get("confidence"),
                "email_status": None,
            }

            # Re-enroll in outreach if ICP tier A–D
            icp = lead.get("icp_tier") or lead.get("icp") or ""
            if icp.upper() in ("A", "B", "C", "D"):
                update["outreach_eligible"] = True

            leads_enriched_collection.update_one(
                {"_id": lead["_id"]},
                {"$set": update},
            )
            missing_updated += 1

        return {
            "bounced_updated": bounced_updated,
            "bounced_skipped": bounced_skipped,
            "missing_updated": missing_updated,
            "missing_skipped": missing_skipped,
            "total_changes": bounced_updated + missing_updated,
            "message": (
                f"Bounced: {bounced_updated} fixed, {bounced_skipped} skipped. "
                f"Missing: {missing_updated} filled, {missing_skipped} skipped."
            ),
        }
    except Exception as e:
        logger.error(f"Error in apply-to-bounced-and-missing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== HELPER FUNCTIONS ==============

def discover_pattern_format(emails: List[str]) -> str:
    """
    Analyze email list to determine likely pattern format
    Returns pattern string like "firstname.lastname", "firstnamelastname", etc.
    """
    if not emails:
        return "unknown"
    
    # Extract local parts (before @)
    local_parts = [e.split("@")[0] for e in emails if "@" in e]
    
    if not local_parts:
        return "unknown"
    
    # Check for common patterns
    if all("." in part for part in local_parts):
        if all(part.count(".") == 1 for part in local_parts):
            return "firstname.lastname"
        return "multiple.parts"
    
    if all("_" in part for part in local_parts):
        if all(part.count("_") == 1 for part in local_parts):
            return "firstname_lastname"
        return "multiple_parts"
    
    # Check for combined pattern
    if all(len(part) > 5 for part in local_parts):
        return "firstnamelastname"
    
    # Default guess
    return "firstname.lastname"


def generate_email_from_pattern(
    pattern: str, firstname: str, lastname: str, domain: str
) -> str:
    """Generate email address based on pattern"""
    firstname = firstname.lower() if firstname else ""
    lastname = lastname.lower() if lastname else ""
    
    if "firstname.lastname" in pattern:
        return f"{firstname}.{lastname}@{domain}" if lastname else f"{firstname}@{domain}"
    elif "firstname_lastname" in pattern:
        return f"{firstname}_{lastname}@{domain}" if lastname else f"{firstname}@{domain}"
    elif "firstnamelastname" in pattern:
        return f"{firstname}{lastname}@{domain}"
    elif "firstname" in pattern:
        return f"{firstname}@{domain}"
    else:
        return f"{firstname}.{lastname}@{domain}" if lastname else f"{firstname}@{domain}"
