"""
UNIFIED EMAIL CLASSIFIER (Single GPT-4o-mini Call)
===================================================
Combines summarization + classification + lead extraction in ONE API call.

Categories:
- client: Business inquiries FROM prospects/customers
- vendor: FROM external suppliers/service providers  
- invoice: Bills, payment requests, dues
- banking: Bank statements, transactions, alerts
- internal: Between team members (same company domains)
- newsletter: Marketing newsletters, industry updates
- bounce: Undeliverable, failed delivery notifications
- promotional: Ads, offers, sales pitches
- automated: System notifications, alerts, confirmations
- others: Cannot determine
"""

import os
import json
import logging
import re
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

from .openai_wrapper import chat_completion, DEFAULT_MODEL

load_dotenv()
logger = logging.getLogger(__name__)

# MongoDB connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
torpedo_gmail_db = mongo_client['torpedo_gmail']
email_metadata = torpedo_gmail_db['email_metadata']


# Internal company domains
INTERNAL_DOMAINS = ["surveyfieldwork.com", "cogentixresearch.com"]

# Valid categories
CATEGORIES = [
    "client", "vendor", "invoice", "banking", "internal",
    "newsletter", "bounce", "promotional", "automated", "others"
]

# Unified system prompt for classification + summarization + lead extraction
UNIFIED_SYSTEM_PROMPT = """You are an email analyzer for a B2B survey/market research company (Survey Fieldwork / Cogentix Research).

Analyze the email and return JSON with summary, classification, and sender information.

CATEGORIES (pick ONE most appropriate):
- client: Business inquiry FROM prospects/customers seeking OUR research/survey services (RFQ, project inquiry, meeting request about their needs)
- vendor: FROM external suppliers/service providers contacting US (sales pitch, partnership offer, software vendor, payment followup FROM vendor about THEIR invoice)
- invoice: Invoice/bill attached or referenced, billing statement, payment request WITH specific invoice details/numbers
- banking: FROM bank domains (axisbank, hdfcbank, icici, sbi, kotak, etc) - statements, transactions, OTPs, KYC, alerts
- internal: FROM @surveyfieldwork.com or @cogentixresearch.com to same - team communications between colleagues
- newsletter: Marketing newsletters with "unsubscribe" link AND regular publication pattern, industry news digests, weekly/monthly roundups from companies
- bounce: Delivery failure, "undeliverable", "mailer-daemon", "postmaster", NDR, returned mail, "failed to deliver"
- promotional: One-off marketing/sales email, ads, offers, cold outreach, webinar invites (NOT regular newsletters)
- automated: System notifications, noreply@, auto-replies, calendar invites, password resets, confirmations, OTPs (non-bank), alerts
- others: ONLY if absolutely cannot determine from any context

OUTPUT FORMAT (valid JSON only, no markdown):
{
  "summary": "2-3 sentence summary explaining email purpose, key points, and any required actions",
  "category": "one of the categories above",
  "confidence": 0.0-1.0,
  "urgency": "critical|high|medium|low|none",
  "action_required": true/false,
  "action_items": ["list of specific action items if any"],
  "sender_info": {
    "name": "Full name of sender (extract from signature or From header)",
    "first_name": "First name only",
    "last_name": "Last name only", 
    "email": "sender@email.com",
    "email_status": "valid",
    "title": "Job title/designation if mentioned in email or signature",
    "linkedin": "LinkedIn profile URL if mentioned",
    "location": "City, Country if mentioned",
    "company_name": "Company/organization name",
    "company_domain": "company.com",
    "company_linkedin": "Company LinkedIn URL if mentioned",
    "company_industry": "Industry if determinable",
    "company_size": "Employee count if mentioned",
    "company_type": "Type of company if determinable",
    "phone": "Phone number if in signature"
  }
}

CLASSIFICATION HINTS:
- "mailer-daemon", "postmaster", "Undeliverable", "Delivery Status" = bounce
- @axisbank.com, @hdfcbank.com, @icicibank.com, alerts@*.bank = banking
- @surveyfieldwork.com, @cogentixresearch.com between team = internal
- Has "Unsubscribe" + comes regularly from same sender = newsletter
- Vendor asking about THEIR unpaid invoice = vendor (not invoice category)
- Invoice WITH attachment or specific invoice number for US to pay = invoice
- "noreply@", "no-reply@", system-generated = automated
- Research/survey project inquiry from external company = client

IMPORTANT: Extract as much sender information as possible from the email signature, headers, and content."""


def extract_sender_name(from_header: str) -> tuple:
    """Extract name parts from email From header"""
    if not from_header:
        return "", "", ""
    
    # Handle "John Doe <john@example.com>" format
    match = re.match(r'^"?([^"<]+)"?\s*<?', from_header)
    if match:
        full_name = match.group(1).strip()
        # Remove email if accidentally included
        full_name = re.sub(r'<[^>]+>', '', full_name).strip()
        parts = full_name.split()
        if len(parts) >= 2:
            return parts[0], " ".join(parts[1:]), full_name
        elif len(parts) == 1:
            return parts[0], "", full_name
    return "", "", ""


def classify_and_summarize(
    email_id: str,
    subject: str,
    body: str,
    from_email: str,
    from_name: str = "",
    to_email: str = "",
    source: str = "background"
) -> Dict[str, Any]:
    """
    Unified classification + summarization + lead extraction in ONE API call.
    Uses GPT-4o-mini for cost efficiency.
    """
    # Truncate body to save tokens (keep first 4000 chars)
    body_preview = body[:4000] if body else ""
    
    # Extract sender info from header
    first_name, last_name, full_name = extract_sender_name(from_name or from_email)
    from_domain = from_email.split("@")[-1].lower() if "@" in from_email else ""
    
    # Build user prompt
    user_prompt = f"""From: {from_name} <{from_email}>
To: {to_email}
Subject: {subject}

Body:
{body_preview}

---
Internal company domains: {', '.join(INTERNAL_DOMAINS)}

Analyze this email. Return valid JSON only, no markdown formatting."""

    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": UNIFIED_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            model=DEFAULT_MODEL,  # gpt-4o-mini
            temperature=0.1,
            max_tokens=1200,
            response_format={"type": "json_object"},
            source=source
        )
        
        if not response:
            logger.warning(f"No response from AI for email {email_id}")
            return _default_result(email_id, from_email, first_name, last_name, full_name, from_domain)
        
        # Parse response
        try:
            # Clean response if it has markdown
            clean_response = response.strip()
            if clean_response.startswith("```"):
                clean_response = re.sub(r'^```json?\s*', '', clean_response)
                clean_response = re.sub(r'\s*```$', '', clean_response)
            result = json.loads(clean_response)
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON from AI for email {email_id}: {e}")
            return _default_result(email_id, from_email, first_name, last_name, full_name, from_domain)
        
        # Normalize category
        category = result.get("category", "others").lower().strip()
        if category not in CATEGORIES:
            category = "others"
        
        # Extract sender info with fallbacks
        sender_info = result.get("sender_info", {})
        
        return {
            "email_id": email_id,
            "success": True,
            "summary": result.get("summary", ""),
            "category": category,
            "confidence": float(result.get("confidence", 0.8)),
            "urgency": result.get("urgency", "none"),
            "action_required": result.get("action_required", False),
            "action_items": result.get("action_items", []),
            "sender_info": {
                "name": sender_info.get("name") or full_name,
                "first_name": sender_info.get("first_name") or first_name,
                "last_name": sender_info.get("last_name") or last_name,
                "email": sender_info.get("email") or from_email,
                "email_status": sender_info.get("email_status", "valid"),
                "title": sender_info.get("title", ""),
                "linkedin": sender_info.get("linkedin", ""),
                "location": sender_info.get("location", ""),
                "company_name": sender_info.get("company_name", ""),
                "company_domain": sender_info.get("company_domain") or from_domain,
                "company_linkedin": sender_info.get("company_linkedin", ""),
                "company_industry": sender_info.get("company_industry", ""),
                "company_size": sender_info.get("company_size", ""),
                "company_type": sender_info.get("company_type", ""),
                "phone": sender_info.get("phone", "")
            },
            "classified_at": datetime.utcnow(),
            "model": DEFAULT_MODEL,
            "method": "unified_gpt4o_mini"
        }
        
    except Exception as e:
        logger.error(f"Classification error for {email_id}: {e}")
        return _default_result(email_id, from_email, first_name, last_name, full_name, from_domain)


def _default_result(email_id: str, from_email: str, first_name: str, last_name: str, full_name: str, from_domain: str = "") -> Dict:
    """Return default result when AI fails"""
    return {
        "email_id": email_id,
        "success": False,
        "summary": "",
        "category": "others",
        "confidence": 0.0,
        "urgency": "none",
        "action_required": False,
        "action_items": [],
        "sender_info": {
            "name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "email": from_email,
            "email_status": "unknown",
            "title": "",
            "linkedin": "",
            "location": "",
            "company_name": "",
            "company_domain": from_domain,
            "company_linkedin": "",
            "company_industry": "",
            "company_size": "",
            "company_type": "",
            "phone": ""
        },
        "classified_at": datetime.utcnow(),
        "model": DEFAULT_MODEL,
        "method": "fallback"
    }


def clear_all_classifications():
    """Remove all AI classification data from emails"""
    result = email_metadata.update_many(
        {},
        {
            "$unset": {
                "ai_category": "",
                "ai_tier1_category": "",
                "ai_confidence": "",
                "ai_method": "",
                "ai_classified_at": "",
                "ai_summary": "",
                "ai_urgency": "",
                "ai_action_required": "",
                "ai_action_items": "",
                "ai_intent": "",
                "ai_sentiment": "",
                "ai_tier2_result": "",
                "sender_info": ""
            }
        }
    )
    logger.info(f"Cleared classification from {result.modified_count} emails")
    return result.modified_count


def classify_batch(
    batch_size: int = 50,
    source: str = "background",
    delay_between_emails: float = 0.05
) -> Dict[str, Any]:
    """
    Classify a batch of unclassified emails.
    Returns stats about the batch.
    """
    # Find unclassified emails
    unclassified = list(email_metadata.find(
        {"ai_category": {"$exists": False}},
        {
            "_id": 1,
            "gmail_message_id": 1,
            "subject": 1,
            "body_plain": 1,
            "from_email": 1,
            "from_name": 1,
            "to_emails": 1
        }
    ).limit(batch_size))
    
    if not unclassified:
        return {"processed": 0, "success": 0, "errors": 0, "message": "No unclassified emails"}
    
    stats = {
        "processed": 0,
        "success": 0,
        "errors": 0,
        "categories": {}
    }
    
    for email_doc in unclassified:
        email_id = str(email_doc["_id"])
        
        try:
            result = classify_and_summarize(
                email_id=email_id,
                subject=email_doc.get("subject", ""),
                body=email_doc.get("body_plain", ""),
                from_email=email_doc.get("from_email", ""),
                from_name=email_doc.get("from_name", ""),
                to_email=email_doc.get("to_emails", [""])[0] if email_doc.get("to_emails") else "",
                source=source
            )
            
            # Update email in database
            email_metadata.update_one(
                {"_id": email_doc["_id"]},
                {
                    "$set": {
                        "ai_category": result["category"],
                        "ai_confidence": result["confidence"],
                        "ai_summary": result["summary"],
                        "ai_urgency": result["urgency"],
                        "ai_action_required": result["action_required"],
                        "ai_action_items": result["action_items"],
                        "ai_classified_at": result["classified_at"],
                        "ai_method": result["method"],
                        "sender_info": result["sender_info"]
                    }
                }
            )
            
            stats["processed"] += 1
            if result["success"]:
                stats["success"] += 1
            else:
                stats["errors"] += 1
            
            # Track category distribution
            cat = result["category"]
            stats["categories"][cat] = stats["categories"].get(cat, 0) + 1
            
            # Small delay to avoid rate limits
            if delay_between_emails > 0:
                time.sleep(delay_between_emails)
            
        except Exception as e:
            logger.error(f"Error processing email {email_id}: {e}")
            stats["errors"] += 1
    
    return stats


def classify_all_pending_emails(
    batch_size: int = 50,
    max_batches: Optional[int] = None,
    delay_between_batches: float = 1.0,
    source: str = "background"
) -> Dict[str, Any]:
    """
    Classify ALL unclassified emails in batches.
    Loops until no more unclassified emails remain.
    """
    total_stats = {
        "success": True,
        "total_processed": 0,
        "total_success": 0,
        "total_errors": 0,
        "batches": 0,
        "categories": {},
        "started_at": datetime.utcnow().isoformat()
    }
    
    batch_num = 0
    while True:
        batch_num += 1
        
        # Check max batches
        if max_batches and batch_num > max_batches:
            logger.info(f"Reached max batches limit: {max_batches}")
            break
        
        logger.info(f"Processing batch {batch_num} with {batch_size} emails")
        
        batch_stats = classify_batch(
            batch_size=batch_size,
            source=source
        )
        
        if batch_stats["processed"] == 0:
            logger.info("No more unclassified emails")
            break
        
        # Accumulate stats
        total_stats["total_processed"] += batch_stats["processed"]
        total_stats["total_success"] += batch_stats.get("success", 0)
        total_stats["total_errors"] += batch_stats.get("errors", 0)
        total_stats["batches"] += 1
        
        for cat, count in batch_stats.get("categories", {}).items():
            total_stats["categories"][cat] = total_stats["categories"].get(cat, 0) + count
        
        logger.info(f"Batch {batch_num} complete: {batch_stats['processed']} processed, {batch_stats.get('errors', 0)} errors")
        
        # Delay between batches
        if delay_between_batches > 0:
            time.sleep(delay_between_batches)
    
    total_stats["completed_at"] = datetime.utcnow().isoformat()
    logger.info(f"Classification complete: {total_stats['total_processed']} emails in {total_stats['batches']} batches")
    
    return total_stats


def get_classification_stats() -> Dict[str, Any]:
    """Get current classification statistics"""
    pipeline = [
        {"$group": {"_id": "$ai_category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    
    results = list(email_metadata.aggregate(pipeline))
    
    total = email_metadata.count_documents({})
    classified = email_metadata.count_documents({"ai_category": {"$exists": True, "$ne": None}})
    
    return {
        "total_emails": total,
        "classified": classified,
        "unclassified": total - classified,
        "categories": {r["_id"]: r["count"] for r in results if r["_id"]}
    }


# Legacy function aliases for backwards compatibility
def classify_email_batch(*args, **kwargs):
    """Legacy wrapper for classify_batch"""
    return {"stats": classify_batch(*args, **kwargs), "results": []}


def get_emails_needing_classification(limit: int = 100) -> List[str]:
    """Get email IDs that haven't been classified yet"""
    emails = email_metadata.find(
        {"ai_category": {"$exists": False}},
        {"_id": 1}
    ).limit(limit)
    return [str(e["_id"]) for e in emails]
