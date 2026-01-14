"""
TIERED EMAIL CLASSIFICATION ENGINE
Two-tier AI approach for cost-effective email classification:

Tier 1 (Fast/Cheap): Basic triage using GPT-4o-mini or keywords
- Classifies ALL emails into: client, vendor, promotional, internal, invoice, banking, spam, others

Tier 2 (Deep/Quality): Rich analysis using better model
- Only for Client/Vendor emails
- Extracts: intent, urgency, action items, summary, sentiment
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
from pymongo import MongoClient
from dotenv import load_dotenv

from .openai_wrapper import (
    chat_completion, 
    DEFAULT_MODEL, 
    PREMIUM_MODEL,
    ANTHROPIC_DEFAULT_MODEL
)

load_dotenv()
logger = logging.getLogger(__name__)

# MongoDB connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
torpedo_gmail_db = mongo_client['torpedo_gmail']
email_metadata = torpedo_gmail_db['email_metadata']


# ============== TIER 1 CATEGORIES (Basic Triage) ==============

class EmailTier1Category(str, Enum):
    """Basic email categories for fast triage"""
    CLIENT = "client"           # Inbound from clients/prospects
    VENDOR = "vendor"           # From vendors/suppliers/partners
    INTERNAL = "internal"       # Internal team communications
    PROMOTIONAL = "promotional" # Marketing, newsletters, spam-like
    INVOICE = "invoice"         # Billing, invoices, payments
    BANKING = "banking"         # Bank statements, transactions
    AUTOMATED = "automated"     # Auto-replies, notifications, system emails
    SPAM = "spam"               # Obvious spam/junk
    OTHERS = "others"           # Uncategorized


# ============== TIER 2 INTENTS (Deep Analysis) ==============

class EmailIntent(str, Enum):
    """Detailed email intents for client/vendor emails"""
    # Client Intents
    NEW_INQUIRY = "new_inquiry"           # New business inquiry
    RFQ_REQUEST = "rfq_request"           # Request for quote
    MEETING_REQUEST = "meeting_request"   # Meeting/call request
    FOLLOW_UP = "follow_up"               # Follow-up on previous conversation
    QUESTION = "question"                 # General question
    COMPLAINT = "complaint"               # Issue/complaint
    FEEDBACK = "feedback"                 # Feedback/review
    NEGOTIATION = "negotiation"           # Price/contract negotiation
    PURCHASE_ORDER = "purchase_order"     # Purchase order
    CANCELLATION = "cancellation"         # Cancel request
    
    # Vendor Intents
    PROPOSAL = "proposal"                 # Vendor proposal/pitch
    QUOTE_RESPONSE = "quote_response"     # Quote/pricing response
    DELIVERY_UPDATE = "delivery_update"   # Delivery/status update
    SUPPORT_RESPONSE = "support_response" # Support ticket response
    INVOICE_PAYMENT = "invoice_payment"   # Invoice or payment related
    CONTRACT = "contract"                 # Contract related
    
    # General
    INFORMATIONAL = "informational"       # FYI, no action needed
    ACTION_REQUIRED = "action_required"   # Needs response/action
    URGENT = "urgent"                     # Time-sensitive
    OTHER = "other"


class EmailUrgency(str, Enum):
    """Email urgency levels"""
    CRITICAL = "critical"   # Needs immediate attention
    HIGH = "high"           # Respond within 24 hours
    MEDIUM = "medium"       # Respond within 48 hours
    LOW = "low"             # Can wait
    NONE = "none"           # No urgency


# ============== TIER 1: FAST CLASSIFICATION ==============

# Keywords for fast rule-based pre-classification (FREE - no API calls)
TIER1_KEYWORDS = {
    EmailTier1Category.PROMOTIONAL: [
        "unsubscribe", "newsletter", "marketing", "promotion", "sale", "discount",
        "limited time", "act now", "exclusive offer", "free trial", "webinar invite",
        "subscription", "click here", "view in browser", "email preferences"
    ],
    EmailTier1Category.AUTOMATED: [
        "auto-reply", "automatic reply", "out of office", "noreply", "no-reply",
        "donotreply", "do not reply", "automated message", "this is an automated",
        "delivery notification", "read receipt", "calendar invitation", "meeting accepted"
    ],
    EmailTier1Category.INVOICE: [
        "invoice", "payment due", "billing statement", "receipt", "remittance",
        "amount due", "pay now", "payment confirmation", "outstanding balance"
    ],
    EmailTier1Category.BANKING: [
        "bank statement", "account summary", "wire transfer", "ach transfer",
        "bank of", "bank notification", "transaction alert", "account balance"
    ],
    EmailTier1Category.SPAM: [
        "winner", "lottery", "inheritance", "nigerian prince", "urgent transfer",
        "congratulations you won", "claim your prize", "limited time offer",
        "act immediately", "wire money"
    ],
}

# Known vendor domains (expand as needed)
VENDOR_DOMAINS = [
    "zoho.com", "quickbooks.com", "xero.com", "freshbooks.com",
    "aws.amazon.com", "cloud.google.com", "azure.microsoft.com",
    "slack.com", "zoom.us", "hubspot.com", "salesforce.com",
    "mailchimp.com", "sendgrid.com", "twilio.com"
]

# Internal domain patterns (will be matched dynamically)
INTERNAL_DOMAIN_PATTERNS = []  # Populated from workspace_mailboxes


def classify_tier1_keywords(
    subject: str, 
    body: str, 
    from_email: str,
    to_email: str = "",
    internal_domains: List[str] = None
) -> Tuple[EmailTier1Category, float]:
    """
    Fast keyword-based classification (Tier 1).
    Returns (category, confidence) - confidence 0.0-1.0
    
    This is FREE - no API calls.
    """
    content = f"{subject} {body}".lower()
    from_domain = from_email.split("@")[-1].lower() if "@" in from_email else ""
    
    # Check internal first
    if internal_domains:
        for domain in internal_domains:
            if from_domain.endswith(domain.lower()):
                return EmailTier1Category.INTERNAL, 0.9
    
    # Check vendor domains
    for vendor_domain in VENDOR_DOMAINS:
        if vendor_domain in from_domain:
            return EmailTier1Category.VENDOR, 0.8
    
    # Score each category by keyword matches
    scores = {}
    for category, keywords in TIER1_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in content)
        if score > 0:
            # Normalize score based on number of keywords matched
            confidence = min(0.9, 0.3 + (score * 0.15))
            scores[category] = confidence
    
    if scores:
        best_category = max(scores, key=scores.get)
        return best_category, scores[best_category]
    
    # No confident match - needs AI classification
    return EmailTier1Category.OTHERS, 0.3


# Tier 1 AI prompt - minimal tokens
TIER1_SYSTEM_PROMPT = """Email classifier. Output JSON only:
{"category":"client|vendor|internal|promotional|invoice|banking|automated|spam|others","confidence":0.0-1.0}

Rules:
- client: Inbound from prospects/customers seeking services
- vendor: From suppliers, service providers, partners
- internal: Same company domain, team communications
- promotional: Marketing, newsletters, sales pitches
- invoice: Billing, payments, invoices
- banking: Bank communications
- automated: Auto-replies, notifications, system emails
- spam: Junk mail
- others: Cannot determine"""

TIER1_USER_PROMPT = """From: {from_email}
To: {to_email}
Subject: {subject}
Body preview: {body}

Classify. JSON only."""


def classify_tier1_ai(
    subject: str,
    body: str,
    from_email: str,
    to_email: str = "",
    source: str = "background"
) -> Tuple[EmailTier1Category, float]:
    """
    AI-based Tier 1 classification using cheap model.
    Use when keyword-based classification is uncertain.
    
    COST: ~0.0001 per email using GPT-4o-mini
    """
    try:
        # Truncate body for cost control
        body_preview = body[:500] if body else ""
        
        result = chat_completion(
            messages=[
                {"role": "system", "content": TIER1_SYSTEM_PROMPT},
                {"role": "user", "content": TIER1_USER_PROMPT.format(
                    from_email=from_email or "-",
                    to_email=to_email or "-",
                    subject=subject or "-",
                    body=body_preview
                )}
            ],
            source=source,
            endpoint="email_tier1",
            model=DEFAULT_MODEL,  # GPT-4o-mini - cheap
            max_output_tokens=50,  # Very small response
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        if not result["success"]:
            logger.warning(f"Tier 1 AI failed: {result.get('error')}")
            return EmailTier1Category.OTHERS, 0.3
        
        parsed = json.loads(result["content"])
        category_str = parsed.get("category", "others").lower()
        confidence = float(parsed.get("confidence", 0.7))
        
        # Map to enum
        try:
            category = EmailTier1Category(category_str)
        except ValueError:
            category = EmailTier1Category.OTHERS
        
        return category, confidence
        
    except Exception as e:
        logger.error(f"Tier 1 classification error: {e}")
        return EmailTier1Category.OTHERS, 0.3


def classify_tier1(
    subject: str,
    body: str,
    from_email: str,
    to_email: str = "",
    internal_domains: List[str] = None,
    use_ai_fallback: bool = True,
    source: str = "background"
) -> Dict[str, Any]:
    """
    Complete Tier 1 classification.
    1. Try keyword-based first (free)
    2. If uncertain (confidence < 0.6), use AI fallback
    
    Returns dict with category, confidence, method used
    """
    # First try keywords (free)
    category, confidence = classify_tier1_keywords(
        subject, body, from_email, to_email, internal_domains
    )
    method = "keywords"
    
    # If uncertain, use AI
    if confidence < 0.6 and use_ai_fallback:
        ai_category, ai_confidence = classify_tier1_ai(
            subject, body, from_email, to_email, source
        )
        if ai_confidence > confidence:
            category = ai_category
            confidence = ai_confidence
            method = "ai_tier1"
    
    return {
        "tier1_category": category.value,
        "tier1_confidence": round(confidence, 2),
        "tier1_method": method,
        "needs_tier2": category in [EmailTier1Category.CLIENT, EmailTier1Category.VENDOR]
    }


# ============== TIER 2: DEEP ANALYSIS ==============

TIER2_SYSTEM_PROMPT = """You are an expert B2B email analyst. Analyze business emails and extract insights.

Output JSON only:
{
    "intent": "new_inquiry|rfq_request|meeting_request|follow_up|question|complaint|feedback|negotiation|purchase_order|cancellation|proposal|quote_response|delivery_update|support_response|invoice_payment|contract|informational|action_required|urgent|other",
    "urgency": "critical|high|medium|low|none",
    "sentiment": "positive|neutral|negative|mixed",
    "summary": "1-2 sentence summary",
    "key_points": ["point 1", "point 2"],
    "action_items": ["action 1", "action 2"],
    "mentioned_amounts": ["$1,000", "€500"],
    "mentioned_dates": ["Jan 15", "next week"],
    "contact_name": "Person name if mentioned",
    "company_mentioned": "Company name if mentioned",
    "is_reply": true/false,
    "reply_expected": true/false,
    "deadline_mentioned": "date or null"
}

Be concise. Focus on actionable insights."""

TIER2_USER_PROMPT = """Analyze this {category} email:

From: {from_email}
To: {to_email}
Subject: {subject}
Date: {date}

Body:
{body}

Extract insights. JSON only."""


def classify_tier2(
    subject: str,
    body: str,
    from_email: str,
    to_email: str = "",
    date: str = "",
    tier1_category: str = "client",
    source: str = "background"
) -> Dict[str, Any]:
    """
    Deep Tier 2 analysis for client/vendor emails.
    Uses better model for quality insights.
    
    COST: ~0.003 per email using Claude Sonnet or GPT-4o
    Only call for emails where tier1_category is 'client' or 'vendor'
    """
    try:
        # Use more of the body for deep analysis
        body_text = body[:2000] if body else ""
        
        result = chat_completion(
            messages=[
                {"role": "system", "content": TIER2_SYSTEM_PROMPT},
                {"role": "user", "content": TIER2_USER_PROMPT.format(
                    category=tier1_category,
                    from_email=from_email or "-",
                    to_email=to_email or "-",
                    subject=subject or "-",
                    date=date or "-",
                    body=body_text
                )}
            ],
            source=source,
            endpoint="email_tier2",
            model=ANTHROPIC_DEFAULT_MODEL,  # Claude 3.5 Sonnet - better quality
            max_output_tokens=400,  # More detailed response
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        
        if not result["success"]:
            logger.warning(f"Tier 2 AI failed: {result.get('error')}")
            return {"tier2_error": result.get("error", "Unknown error")}
        
        parsed = json.loads(result["content"])
        
        # Normalize and validate
        return {
            "tier2_intent": parsed.get("intent", "other"),
            "tier2_urgency": parsed.get("urgency", "medium"),
            "tier2_sentiment": parsed.get("sentiment", "neutral"),
            "tier2_summary": parsed.get("summary", ""),
            "tier2_key_points": parsed.get("key_points", []),
            "tier2_action_items": parsed.get("action_items", []),
            "tier2_amounts": parsed.get("mentioned_amounts", []),
            "tier2_dates": parsed.get("mentioned_dates", []),
            "tier2_contact_name": parsed.get("contact_name", ""),
            "tier2_company": parsed.get("company_mentioned", ""),
            "tier2_is_reply": parsed.get("is_reply", False),
            "tier2_reply_expected": parsed.get("reply_expected", False),
            "tier2_deadline": parsed.get("deadline_mentioned"),
            "tier2_analyzed_at": datetime.utcnow().isoformat(),
            "tier2_model": ANTHROPIC_DEFAULT_MODEL
        }
        
    except json.JSONDecodeError as e:
        logger.error(f"Tier 2 JSON parse error: {e}")
        return {"tier2_error": "JSON parse error"}
    except Exception as e:
        logger.error(f"Tier 2 classification error: {e}")
        return {"tier2_error": str(e)}


# ============== COMBINED CLASSIFICATION ==============

def classify_email_full(
    email_id: str = None,
    subject: str = "",
    body: str = "",
    from_email: str = "",
    to_email: str = "",
    date: str = "",
    internal_domains: List[str] = None,
    run_tier2: bool = True,
    source: str = "background"
) -> Dict[str, Any]:
    """
    Full email classification pipeline.
    
    1. Tier 1: Fast classification (keywords + cheap AI)
    2. Tier 2: Deep analysis (only for client/vendor, using better AI)
    
    Returns combined classification result.
    """
    result = {
        "email_id": email_id,
        "classified_at": datetime.utcnow().isoformat()
    }
    
    # Tier 1: Fast triage
    tier1 = classify_tier1(
        subject=subject,
        body=body,
        from_email=from_email,
        to_email=to_email,
        internal_domains=internal_domains,
        source=source
    )
    result.update(tier1)
    
    # Tier 2: Deep analysis (only for client/vendor)
    if run_tier2 and tier1["needs_tier2"]:
        tier2 = classify_tier2(
            subject=subject,
            body=body,
            from_email=from_email,
            to_email=to_email,
            date=date,
            tier1_category=tier1["tier1_category"],
            source=source
        )
        result.update(tier2)
    
    return result


def classify_email_batch(
    email_ids: List[str],
    run_tier2: bool = True,
    internal_domains: List[str] = None,
    source: str = "background"
) -> Dict[str, Any]:
    """
    Batch classification of emails from database.
    
    Returns summary with counts and individual results.
    """
    from bson import ObjectId
    
    results = []
    stats = {
        "total": len(email_ids),
        "processed": 0,
        "tier1_only": 0,
        "tier2_analyzed": 0,
        "errors": 0,
        "by_category": {}
    }
    
    for email_id in email_ids:
        try:
            # Fetch email from database
            email_doc = email_metadata.find_one({"_id": ObjectId(email_id)})
            if not email_doc:
                stats["errors"] += 1
                continue
            
            # Extract fields
            subject = email_doc.get("subject", "")
            body = email_doc.get("body_plain", "") or email_doc.get("snippet", "")
            from_email = email_doc.get("from_email", "")
            to_emails = email_doc.get("to_emails", [])
            to_email = to_emails[0] if to_emails else ""
            timestamp = email_doc.get("timestamp")
            date_str = timestamp.isoformat() if timestamp else ""
            
            # Classify
            classification = classify_email_full(
                email_id=email_id,
                subject=subject,
                body=body,
                from_email=from_email,
                to_email=to_email,
                date=date_str,
                internal_domains=internal_domains,
                run_tier2=run_tier2,
                source=source
            )
            
            # Update database
            update_fields = {
                "ai_category": classification.get("tier1_category"),
                "ai_confidence": classification.get("tier1_confidence"),
                "ai_method": classification.get("tier1_method"),
                "ai_classified_at": datetime.utcnow()
            }
            
            # Add tier 2 fields if available
            if classification.get("tier2_intent"):
                update_fields.update({
                    "ai_intent": classification.get("tier2_intent"),
                    "ai_urgency": classification.get("tier2_urgency"),
                    "ai_sentiment": classification.get("tier2_sentiment"),
                    "ai_summary": classification.get("tier2_summary"),
                    "ai_key_points": classification.get("tier2_key_points"),
                    "ai_action_items": classification.get("tier2_action_items"),
                    "ai_reply_expected": classification.get("tier2_reply_expected"),
                    "ai_tier2_at": datetime.utcnow()
                })
                stats["tier2_analyzed"] += 1
            else:
                stats["tier1_only"] += 1
            
            email_metadata.update_one(
                {"_id": ObjectId(email_id)},
                {"$set": update_fields}
            )
            
            # Track stats
            cat = classification.get("tier1_category", "others")
            stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1
            stats["processed"] += 1
            
            results.append(classification)
            
        except Exception as e:
            logger.error(f"Error classifying email {email_id}: {e}")
            stats["errors"] += 1
    
    return {
        "stats": stats,
        "results": results
    }


# ============== UTILITY FUNCTIONS ==============

def get_internal_domains() -> List[str]:
    """Get internal domain list from workspace mailboxes"""
    try:
        workspace_mailboxes = torpedo_gmail_db["workspace_mailboxes"]
        mailboxes = workspace_mailboxes.find({"is_active": True}, {"email": 1})
        
        domains = set()
        for mb in mailboxes:
            email = mb.get("email", "")
            if "@" in email:
                domain = email.split("@")[-1].lower()
                domains.add(domain)
        
        return list(domains)
    except Exception as e:
        logger.error(f"Error fetching internal domains: {e}")
        return []


def get_emails_needing_classification(
    limit: int = 100,
    category_filter: str = None
) -> List[str]:
    """Get email IDs that haven't been AI classified yet"""
    query = {"ai_category": {"$exists": False}}
    
    if category_filter:
        query["category"] = category_filter
    
    emails = email_metadata.find(
        query,
        {"_id": 1}
    ).sort("timestamp", -1).limit(limit)
    
    return [str(e["_id"]) for e in emails]


def get_emails_needing_tier2(limit: int = 50) -> List[str]:
    """Get client/vendor emails that need Tier 2 analysis"""
    query = {
        "ai_category": {"$in": ["client", "vendor"]},
        "ai_intent": {"$exists": False}
    }
    
    emails = email_metadata.find(
        query,
        {"_id": 1}
    ).sort("timestamp", -1).limit(limit)
    
    return [str(e["_id"]) for e in emails]
