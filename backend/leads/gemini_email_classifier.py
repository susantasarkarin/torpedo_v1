"""
GEMINI EMAIL CLASSIFICATION SERVICE
Uses Google Gemini 1.5 Flash for email segregation with automatic lead extraction.

Features:
- Tiered classification (keyword-first, then AI)
- Lead extraction for sales-qualified emails
- Automatic creation of leads in Sales > Leads section
- Multi-key rotation for staying within free limits
- Background processing with rate limiting
"""

import os
import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
from bson import ObjectId
from pymongo import MongoClient, UpdateOne
from dotenv import load_dotenv

from .gemini_wrapper import (
    gemini_generate,
    gemini_classify_email,
    gemini_extract_lead,
    get_gemini_status,
    GEMINI_FLASH_MODEL,
    GEMINI_AVAILABLE
)
from .models import (
    LeadRaw, LeadEnriched, ClassificationStatus,
    SeniorityLevel, Department, Persona, CompanySize, Region,
    BuyingRole, Gender, EmailStatus
)

load_dotenv()
logger = logging.getLogger(__name__)

# ============== DATABASE CONNECTION ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

# Email database
torpedo_gmail_db = mongo_client['torpedo_gmail']
email_metadata = torpedo_gmail_db['email_metadata']
gemini_classification_logs = torpedo_gmail_db['gemini_classification_logs']

# Leads database
email_automation_db = mongo_client['email_automation']
leads_raw_collection = email_automation_db['leads_raw']
leads_enriched_collection = email_automation_db['leads_enriched']
email_leads_collection = email_automation_db['email_extracted_leads']

# Create indexes
try:
    email_leads_collection.create_index("email", unique=True)
    email_leads_collection.create_index("source_email_id")
    email_leads_collection.create_index("created_at")
    email_leads_collection.create_index("status")
    gemini_classification_logs.create_index("email_id")
    gemini_classification_logs.create_index("created_at")
except Exception as e:
    logger.warning(f"Could not create indexes: {e}")


# ============== EMAIL CATEGORIES ==============

class GeminiEmailCategory(str, Enum):
    """Email categories from Gemini classification"""
    CLIENT = "client"           # Potential sales lead
    RFQ = "rfq"                 # Request for Quote/Proposal
    VENDOR = "vendor"           # From vendors/suppliers
    INTERNAL = "internal"       # Internal communications
    PROMOTIONAL = "promotional" # Marketing emails
    INVOICE = "invoice"         # Billing related
    BANKING = "banking"         # Bank communications
    AUTOMATED = "automated"     # Auto-replies, notifications
    SPAM = "spam"               # Junk mail
    OTHERS = "others"           # Uncategorized


# Categories that should trigger lead extraction
LEAD_ELIGIBLE_CATEGORIES = {
    GeminiEmailCategory.CLIENT,
    GeminiEmailCategory.RFQ,     # RFQ emails are high-value leads
    GeminiEmailCategory.VENDOR,  # Vendors can also be leads
}


# ============== KEYWORD-BASED PRE-CLASSIFICATION ==============

CATEGORY_KEYWORDS = {
    GeminiEmailCategory.PROMOTIONAL: [
        "unsubscribe", "newsletter", "marketing", "promotion", "sale", "discount",
        "limited time", "act now", "exclusive offer", "free trial", "webinar invite",
        "subscription", "click here", "view in browser", "email preferences"
    ],
    GeminiEmailCategory.AUTOMATED: [
        "auto-reply", "automatic reply", "out of office", "noreply", "no-reply",
        "donotreply", "do not reply", "automated message", "this is an automated",
        "delivery notification", "read receipt", "calendar invitation", "meeting accepted"
    ],
    GeminiEmailCategory.INVOICE: [
        "invoice", "payment due", "billing statement", "receipt", "remittance",
        "amount due", "pay now", "payment confirmation", "outstanding balance"
    ],
    GeminiEmailCategory.BANKING: [
        "bank statement", "account summary", "wire transfer", "ach transfer",
        "bank of", "bank notification", "transaction alert", "account balance"
    ],
    GeminiEmailCategory.SPAM: [
        "winner", "lottery", "inheritance", "nigerian prince", "urgent transfer",
        "congratulations you won", "claim your prize", "wire money", "bitcoin giveaway"
    ],
}

# Known vendor/service domains
VENDOR_DOMAINS = {
    "zoho.com", "quickbooks.com", "xero.com", "freshbooks.com",
    "aws.amazon.com", "cloud.google.com", "azure.microsoft.com",
    "slack.com", "zoom.us", "hubspot.com", "salesforce.com",
    "mailchimp.com", "sendgrid.com", "twilio.com", "stripe.com",
    "github.com", "atlassian.com", "notion.so", "figma.com"
}


def classify_by_keywords(
    subject: str,
    body: str,
    from_email: str,
    internal_domains: List[str] = None
) -> Tuple[Optional[GeminiEmailCategory], float]:
    """
    Fast keyword-based pre-classification (FREE - no API calls).
    Returns (category, confidence) or (None, 0) if uncertain.
    """
    content = f"{subject} {body}".lower()
    from_domain = from_email.split("@")[-1].lower() if "@" in from_email else ""
    
    # Check internal domains first
    if internal_domains:
        for domain in internal_domains:
            if from_domain.endswith(domain.lower()):
                return GeminiEmailCategory.INTERNAL, 0.95
    
    # Check vendor domains
    for vendor_domain in VENDOR_DOMAINS:
        if vendor_domain in from_domain:
            return GeminiEmailCategory.VENDOR, 0.85
    
    # Check keywords
    for category, keywords in CATEGORY_KEYWORDS.items():
        matches = sum(1 for kw in keywords if kw in content)
        if matches >= 2:
            confidence = min(0.9, 0.5 + (matches * 0.1))
            return category, confidence
    
    # No confident match
    return None, 0.0


# ============== LEAD EXTRACTION ==============

def extract_domain_from_email(email: str) -> str:
    """Extract domain from email address"""
    if not email or "@" not in email:
        return ""
    return email.split("@")[-1].lower()


def extract_name_parts(full_name: str) -> Tuple[str, str]:
    """Split full name into first and last name"""
    if not full_name:
        return "", ""
    
    parts = full_name.strip().split()
    if len(parts) == 0:
        return "", ""
    elif len(parts) == 1:
        return parts[0], ""
    else:
        return parts[0], " ".join(parts[1:])


def extract_website_from_signature(text: str) -> str:
    """Extract website URL from email signature"""
    # Pattern for URLs
    url_pattern = r'https?://[^\s<>"\']+|www\.[^\s<>"\']+\.[a-z]{2,}'
    
    matches = re.findall(url_pattern, text, re.IGNORECASE)
    
    # Filter out common non-company URLs
    exclude_patterns = [
        "linkedin.com", "facebook.com", "twitter.com", "instagram.com",
        "youtube.com", "google.com", "mailto:", "tel:", "unsubscribe"
    ]
    
    for match in matches:
        is_excluded = any(exc in match.lower() for exc in exclude_patterns)
        if not is_excluded:
            # Clean up the URL
            url = match.strip(".,;:!?\"'<>()[]{}")
            if not url.startswith("http"):
                url = "https://" + url
            return url
    
    return ""


def create_lead_from_email(
    full_name: str,
    first_name: str,
    last_name: str,
    email: str,
    website: str,
    domain: str,
    source_email_id: str,
    title: str = "",
    company_name: str = "",
    phone: str = "",
    linkedin_url: str = "",
    confidence: float = 0.7
) -> Dict[str, Any]:
    """
    Create a lead from extracted email data and save to database.
    Returns the created lead or existing lead if duplicate.
    """
    if not email:
        return {"success": False, "error": "No email provided"}
    
    email = email.lower().strip()
    
    # Check for existing lead
    existing = email_leads_collection.find_one({"email": email})
    if existing:
        # Update with new source email
        email_leads_collection.update_one(
            {"email": email},
            {
                "$addToSet": {"source_email_ids": source_email_id},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        return {
            "success": True,
            "action": "updated",
            "lead_id": str(existing["_id"]),
            "message": "Lead already exists, added source email reference"
        }
    
    # Create new lead
    lead_data = {
        "full_name": full_name or "",
        "first_name": first_name or "",
        "last_name": last_name or "",
        "email": email,
        "email_status": EmailStatus.VALID.value if email else EmailStatus.UNKNOWN.value,
        "title": title or "",
        "company_name": company_name or "",
        "website": website or "",
        "domain": domain or extract_domain_from_email(email),
        "phone": phone or "",
        "linkedin_url": linkedin_url or "",
        "source": "email_extraction",
        "source_email_ids": [source_email_id],
        "confidence_score": confidence,
        "status": "new",  # new, contacted, qualified, converted
        "lead_stage": "leads",  # For Sales > Leads section
        "stage": "lead_generation",  # Pipeline stage
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "extracted_by": "gemini",
        "classification_status": ClassificationStatus.CLASSIFIED.value
    }
    
    try:
        result = email_leads_collection.insert_one(lead_data)
        lead_id = str(result.inserted_id)
        
        # Also create in leads_enriched for Sales > Leads section
        enriched_lead = {
            "raw_lead_id": "",  # No raw lead for email extractions
            "name": full_name or f"{first_name} {last_name}".strip() or email.split("@")[0],
            "first_name": first_name or "",
            "last_name": last_name or "",
            "email": email,
            "email_status": EmailStatus.VALID.value,
            "title": title or "",
            "linkedin_url": linkedin_url or f"https://www.linkedin.com/search/results/all/?keywords={email.split('@')[0]}",
            "location": "",
            "phone": phone or "",
            "added_on": datetime.utcnow(),
            "source": "email_extraction",
            "snippet": f"Lead extracted from email by Gemini AI",
            "seniority_level": SeniorityLevel.UNKNOWN.value,
            "buying_role": BuyingRole.UNKNOWN.value,
            "department": Department.OTHER.value,
            "persona": Persona.PRACTITIONER.value,
            "gender": Gender.UNKNOWN.value,
            "company_size": CompanySize.SMB.value,
            "region": Region.OTHER.value,
            "confidence_score": confidence,
            "company_name": company_name or "",
            "company_domain": domain or extract_domain_from_email(email),
            "company_website": website or "",
            "stage": "lead_generation",
            "lead_stage": "leads",
            "campaign_ids": [],
            "email_extracted_lead_id": lead_id,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        # Insert to leads_enriched (skip duplicates)
        try:
            leads_enriched_collection.insert_one(enriched_lead)
        except Exception as e:
            if "duplicate" not in str(e).lower():
                logger.warning(f"Could not create enriched lead: {e}")
        
        logger.info(f"✅ Created lead from email: {email} (ID: {lead_id})")
        
        return {
            "success": True,
            "action": "created",
            "lead_id": lead_id,
            "lead_data": lead_data
        }
    
    except Exception as e:
        logger.error(f"Failed to create lead: {e}")
        return {"success": False, "error": str(e)}


# ============== MAIN CLASSIFICATION FUNCTION ==============

def classify_email_with_gemini(
    email_id: str,
    subject: str,
    body: str,
    from_email: str,
    to_email: str = "",
    internal_domains: List[str] = None,
    extract_leads: bool = True,
    source: str = "background",
    use_keywords_first: bool = False  # Disabled by default - use Gemini for all classification
) -> Dict[str, Any]:
    """
    Classify an email using Gemini 2.5 Flash for accurate classification.
    
    Keyword-based classification is now DISABLED by default because it causes
    misclassification issues:
    - RFQ emails marked as "Others"
    - Vendor payment follow-ups marked as "Invoice"
    - Some promotional emails marked as "Others"
    
    Args:
        email_id: MongoDB email ID
        subject: Email subject
        body: Email body (plain text preferred)
        from_email: Sender email address
        to_email: Recipient email address
        internal_domains: List of internal domain patterns
        extract_leads: Whether to extract and create leads
        source: Request source for logging
        use_keywords_first: Legacy mode - use keywords first (disabled by default)
    
    Returns:
        Classification result with optional lead info
    """
    result = {
        "email_id": email_id,
        "success": False,
        "category": GeminiEmailCategory.OTHERS.value,
        "confidence": 0.0,
        "method": "none",
        "is_sales_lead": False,
        "lead_extracted": False,
        "lead_info": None,
        "lead_id": None,
        "error": None,
        "reasoning": None
    }
    
    # LEGACY MODE: Try keyword-based classification first (only if explicitly enabled)
    # This is disabled by default because it causes misclassification
    if use_keywords_first:
        keyword_category, keyword_confidence = classify_by_keywords(
            subject, body, from_email, internal_domains
        )
        
        # Only use keywords for VERY high confidence on spam/promotional/automated
        # These are the only categories where keywords are reliable
        if keyword_category and keyword_confidence >= 0.95:
            if keyword_category in [GeminiEmailCategory.SPAM, GeminiEmailCategory.AUTOMATED]:
                result["category"] = keyword_category.value
                result["confidence"] = keyword_confidence
                result["method"] = "keywords"
                result["success"] = True
                
                _log_classification(
                    email_id=email_id,
                    category=keyword_category.value,
                    confidence=keyword_confidence,
                    method="keywords",
                    model=None
                )
                return result
    
    # PRIMARY: Use Gemini 2.5 Flash for accurate classification
    if not GEMINI_AVAILABLE:
        result["error"] = "Gemini not available"
        return result
    
    gemini_result = gemini_classify_email(
        subject=subject,
        body=body,
        from_email=from_email,
        to_email=to_email,
        source=source
    )
    
    if not gemini_result["success"]:
        result["error"] = gemini_result.get("error", "Gemini classification failed")
        return result
    
    # Parse Gemini response
    parsed = gemini_result.get("parsed", {})
    if not parsed:
        try:
            import json
            parsed = json.loads(gemini_result.get("content", "{}"))
        except:
            parsed = {}
    
    category = parsed.get("category", "others").lower()
    confidence = float(parsed.get("confidence", 0.7))
    is_sales_lead = parsed.get("is_sales_lead", False)
    lead_info = parsed.get("lead_info", {})
    reasoning = parsed.get("reasoning", "")
    
    # Validate category is one of the known categories
    valid_categories = ["client", "rfq", "vendor", "internal", "promotional", 
                        "invoice", "banking", "automated", "spam", "others"]
    if category not in valid_categories:
        category = "others"
    
    # RFQ emails are high-value leads - ensure is_sales_lead is True
    if category == "rfq":
        is_sales_lead = True
    
    result["category"] = category
    result["confidence"] = confidence
    result["method"] = "gemini"
    result["model"] = gemini_result.get("model", GEMINI_FLASH_MODEL)
    result["tokens"] = gemini_result.get("tokens", {})
    result["success"] = True
    result["is_sales_lead"] = is_sales_lead
    result["reasoning"] = reasoning
    
    # Log classification
    _log_classification(
        email_id=email_id,
        category=category,
        confidence=confidence,
        method="gemini",
        model=gemini_result.get("model"),
        tokens=gemini_result.get("tokens", {}),
        is_sales_lead=is_sales_lead,
        raw_response=gemini_result.get("content")
    )
    
    # Step 3: Extract and create lead if applicable
    if is_sales_lead and extract_leads and lead_info:
        # Extract name parts
        full_name = lead_info.get("full_name", "")
        first_name = lead_info.get("first_name", "")
        last_name = lead_info.get("last_name", "")
        
        if not first_name and not last_name and full_name:
            first_name, last_name = extract_name_parts(full_name)
        
        email_addr = lead_info.get("email", "") or from_email
        website = lead_info.get("website", "") or extract_website_from_signature(body)
        domain = lead_info.get("domain", "") or extract_domain_from_email(email_addr)
        
        lead_result = create_lead_from_email(
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            email=email_addr,
            website=website,
            domain=domain,
            source_email_id=email_id,
            title=lead_info.get("title", ""),
            company_name=lead_info.get("company_name", ""),
            phone=lead_info.get("phone", ""),
            linkedin_url=lead_info.get("linkedin_url", ""),
            confidence=confidence
        )
        
        result["lead_extracted"] = lead_result.get("success", False)
        result["lead_id"] = lead_result.get("lead_id")
        result["lead_info"] = {
            "full_name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "email": email_addr,
            "website": website,
            "domain": domain
        }
    
    # Update email metadata with classification
    try:
        email_metadata.update_one(
            {"_id": ObjectId(email_id)},
            {
                "$set": {
                    "gemini_category": category,
                    "gemini_confidence": confidence,
                    "gemini_classified_at": datetime.utcnow(),
                    "is_sales_lead": is_sales_lead,
                    "extracted_lead_id": result.get("lead_id")
                }
            }
        )
    except Exception as e:
        logger.warning(f"Could not update email metadata: {e}")
    
    return result


def _log_classification(
    email_id: str,
    category: str,
    confidence: float,
    method: str,
    model: Optional[str] = None,
    tokens: Dict[str, int] = None,
    is_sales_lead: bool = False,
    raw_response: Optional[str] = None
):
    """Log classification result to MongoDB"""
    try:
        gemini_classification_logs.insert_one({
            "email_id": email_id,
            "category": category,
            "confidence": confidence,
            "method": method,
            "model": model,
            "tokens": tokens or {},
            "is_sales_lead": is_sales_lead,
            "raw_response": raw_response[:1000] if raw_response else None,
            "created_at": datetime.utcnow()
        })
    except Exception as e:
        logger.warning(f"Failed to log classification: {e}")


# ============== BATCH PROCESSING ==============

def classify_pending_emails(
    limit: int = 100,
    internal_domains: List[str] = None,
    source: str = "background"
) -> Dict[str, Any]:
    """
    Classify pending emails in batches with rate limiting.
    
    Args:
        limit: Maximum number of emails to process
        internal_domains: List of internal domain patterns
        source: Request source for logging
    
    Returns:
        Summary of classification results
    """
    # Find unclassified emails
    query = {
        "$or": [
            {"gemini_category": {"$exists": False}},
            {"gemini_category": None},
            {"gemini_category": ""}
        ]
    }
    
    emails = list(email_metadata.find(query).limit(limit))
    
    if not emails:
        return {
            "success": True,
            "processed": 0,
            "message": "No pending emails to classify"
        }
    
    results = {
        "success": True,
        "processed": 0,
        "classified": 0,
        "leads_extracted": 0,
        "errors": 0,
        "categories": {},
        "details": []
    }
    
    # Get Gemini status
    gemini_status = get_gemini_status()
    available_keys = gemini_status.get("available_keys", 0)
    
    if available_keys == 0:
        return {
            "success": False,
            "error": "No Gemini API keys available",
            "gemini_status": gemini_status
        }
    
    # Process emails with rate limiting (15 RPM max, use 12 for safety)
    import time
    delay_between_requests = 5.0  # 12 requests per minute
    
    for i, email in enumerate(emails):
        email_id = str(email.get("_id", ""))
        subject = email.get("subject", "")
        body = email.get("body_plain", "") or email.get("body_html", "")
        from_email = email.get("from_email", "") or email.get("sender", "")
        to_email = email.get("to_email", "") or ""
        
        try:
            classification = classify_email_with_gemini(
                email_id=email_id,
                subject=subject,
                body=body,
                from_email=from_email,
                to_email=to_email,
                internal_domains=internal_domains,
                extract_leads=True,
                source=source
            )
            
            results["processed"] += 1
            
            if classification["success"]:
                results["classified"] += 1
                category = classification["category"]
                results["categories"][category] = results["categories"].get(category, 0) + 1
                
                if classification.get("lead_extracted"):
                    results["leads_extracted"] += 1
            else:
                results["errors"] += 1
            
            results["details"].append({
                "email_id": email_id,
                "subject": subject[:50] if subject else "",
                "category": classification.get("category"),
                "confidence": classification.get("confidence"),
                "is_lead": classification.get("is_sales_lead"),
                "lead_id": classification.get("lead_id"),
                "error": classification.get("error")
            })
        
        except Exception as e:
            results["errors"] += 1
            results["details"].append({
                "email_id": email_id,
                "error": str(e)
            })
        
        # Rate limit delay (except for last request)
        if i < len(emails) - 1:
            time.sleep(delay_between_requests)
    
    return results


# ============== STATISTICS ==============

def get_classification_stats() -> Dict[str, Any]:
    """Get email classification statistics"""
    pipeline = [
        {
            "$match": {
                "gemini_category": {"$exists": True, "$ne": None}
            }
        },
        {
            "$group": {
                "_id": "$gemini_category",
                "count": {"$sum": 1},
                "avg_confidence": {"$avg": "$gemini_confidence"},
                "leads_count": {
                    "$sum": {"$cond": [{"$eq": ["$is_sales_lead", True]}, 1, 0]}
                }
            }
        }
    ]
    
    category_stats = list(email_metadata.aggregate(pipeline))
    
    total_classified = sum(s["count"] for s in category_stats)
    total_leads = sum(s["leads_count"] for s in category_stats)
    
    # Get lead extraction stats
    leads_count = email_leads_collection.count_documents({})
    
    return {
        "total_classified": total_classified,
        "total_leads_extracted": leads_count,
        "categories": {
            s["_id"]: {
                "count": s["count"],
                "avg_confidence": round(s["avg_confidence"], 2) if s["avg_confidence"] else 0,
                "leads_count": s["leads_count"]
            }
            for s in category_stats
        },
        "gemini_status": get_gemini_status()
    }


def get_extracted_leads(
    page: int = 1,
    limit: int = 50,
    status: Optional[str] = None
) -> Dict[str, Any]:
    """Get leads extracted from emails"""
    query = {}
    if status:
        query["status"] = status
    
    skip = (page - 1) * limit
    
    leads = list(
        email_leads_collection.find(query)
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    
    total = email_leads_collection.count_documents(query)
    
    # Convert ObjectId to string
    for lead in leads:
        lead["_id"] = str(lead["_id"])
    
    return {
        "leads": leads,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit
    }
