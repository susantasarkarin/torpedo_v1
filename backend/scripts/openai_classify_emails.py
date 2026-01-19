#!/usr/bin/env python3
"""
OPENAI EMAIL CLASSIFICATION
============================

Classifies all emails using OpenAI GPT-4o-mini for:
- Fast, cost-effective classification
- Category assignment
- Summary generation
- Urgency detection

Usage:
    python scripts/openai_classify_emails.py [--batch-size N] [--max-emails N] [--reset]
"""

import os
import sys
import time
import argparse
import logging
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient, UpdateOne

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MongoDB connection with optimized settings for background processing
# - maxPoolSize: Limit connections to not starve the main app
# - w: 1 for faster writes (don't wait for all replicas)
# - journal: False for faster writes (data is still persisted)
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
mongo_client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=5000,
    maxPoolSize=5,  # Limit connections for background task
    minPoolSize=1,
    maxIdleTimeMS=30000,
    socketTimeoutMS=30000,
    connectTimeoutMS=5000,
    retryWrites=True
)
torpedo_gmail_db = mongo_client['torpedo_gmail']
email_metadata = torpedo_gmail_db['email_metadata']
settings_db = mongo_client['torpedo_settings']

# Email categories
CATEGORIES = [
    "client",       # Potential clients/customers
    "rfq",          # Request for Quote/Proposal
    "vendor",       # From vendors/suppliers
    "internal",     # Internal communications
    "promotional",  # Marketing emails
    "invoice",      # Billing related
    "banking",      # Bank communications
    "automated",    # Auto-replies, notifications
    "bounce",       # Delivery failures
    "spam",         # Junk mail
    "others"        # Uncategorized
]

URGENCY_LEVELS = ["high", "medium", "low", "none"]


def extract_latest_reply(body: str) -> Tuple[str, bool]:
    """
    Extract only the latest reply from an email body, removing quoted content.
    
    Returns:
        Tuple of (extracted_content, has_quoted_content)
    """
    if not body:
        return "", False
    
    # Common patterns that indicate start of quoted content
    quote_patterns = [
        r'\n\s*On\s+.+wrote:',  # "On Mon, Jan 1, 2026, John wrote:"
        r'\n\s*-{3,}\s*Original Message\s*-{3,}',  # "--- Original Message ---"
        r'\n\s*_{3,}\s*\n',  # "___" separator line
        r'\n\s*From:\s+.+\n\s*Sent:\s+',  # Outlook style "From: ... Sent: ..."
        r'\n\s*>+\s*',  # Lines starting with ">"
        r'\n\s*\*From:\*',  # "*From:*" bold style
        r'\n\s*Get Outlook for',  # Outlook mobile signature before quotes
        r'\n\s*Sent from my iPhone',  # iPhone signature before quotes
        r'\n\s*Sent from my Samsung',  # Samsung signature
    ]
    
    # Find the earliest match position
    earliest_pos = len(body)
    has_quoted = False
    
    for pattern in quote_patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match and match.start() < earliest_pos:
            earliest_pos = match.start()
            has_quoted = True
    
    # Extract the latest reply (content before quoted section)
    latest_reply = body[:earliest_pos].strip()
    
    # Also remove common signature patterns at the end
    signature_patterns = [
        r'\n\s*--\s*\n.*$',  # Standard email signature delimiter
        r'\n\s*Best regards?,?\s*\n.*$',
        r'\n\s*Thanks?,?\s*\n.*$',
        r'\n\s*Regards?,?\s*\n.*$',
        r'\n\s*Sincerely,?\s*\n.*$',
    ]
    
    # Keep signature for context but mark it
    # (We don't strip signatures as they may contain useful contact info)
    
    return latest_reply, has_quoted


def get_openai_key() -> str:
    """Get OpenAI API key from database or environment"""
    # Try database first
    config = settings_db.app_settings.find_one({"_id": "app_config"})
    if config and config.get("openai_api_key"):
        return config["openai_api_key"]
    
    # Fallback to environment
    return os.getenv("OPENAI_API_KEY", "")


def classify_emails_batch(emails: List[Dict], openai_key: str) -> List[Dict]:
    """
    Classify a batch of emails using OpenAI GPT-4o-mini.
    Uses the full email body for comprehensive context.
    """
    try:
        from openai import OpenAI
    except ImportError:
        logger.error("OpenAI package not installed. Run: pip install openai")
        return []
    
    client = OpenAI(api_key=openai_key)
    results = []
    
    for email_doc in emails:
        email_id = str(email_doc.get("_id", ""))
        subject = email_doc.get("subject", "")[:200]
        raw_body = email_doc.get("body_plain", "") or email_doc.get("body_html", "")
        from_email = email_doc.get("from_email", "")
        from_name = email_doc.get("from_name", "")
        
        # Use full email body for comprehensive context (limit to 4000 chars for API)
        body = raw_body[:4000] if raw_body else ""
        
        # Skip if no content
        if not subject and not body:
            results.append({
                "email_id": email_id,
                "success": True,
                "category": "others",
                "urgency": "none",
                "summary": "Empty email",
                "confidence": 1.0,
                "method": "skip_empty"
            })
            continue
        
        # Build the prompt with full email body
        prompt = f"""Analyze this email conversation and provide classification.

FROM: {from_name} <{from_email}>
SUBJECT: {subject}

FULL EMAIL BODY:
{body[:3500]}

Classify this email into ONE of these categories:
- client: From potential clients/customers inquiring about services
- rfq: Request for Quote/Proposal  
- vendor: From vendors/suppliers/service providers
- internal: Internal company communications
- promotional: Marketing, newsletters, promotions
- invoice: Billing, invoices, payments
- banking: Bank statements, transactions
- automated: Auto-replies, system notifications, delivery confirmations
- bounce: Email delivery failures, undeliverable
- spam: Junk mail, scams
- others: Doesn't fit any category

Respond in JSON format:
{{
    "category": "one of the categories above",
    "urgency": "high/medium/low/none",
    "summary": "1-2 sentence summary of the entire email conversation/thread",
    "is_sales_lead": true/false,
    "confidence": 0.0-1.0
}}"""

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an email classification assistant. Analyze the FULL email conversation including any quoted replies to understand the complete context. Respond only with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=200,
                response_format={"type": "json_object"}
            )
            
            result_text = response.choices[0].message.content
            result = json.loads(result_text)
            
            # Validate category
            category = result.get("category", "others").lower()
            if category not in CATEGORIES:
                category = "others"
            
            # Validate urgency
            urgency = result.get("urgency", "none").lower()
            if urgency not in URGENCY_LEVELS:
                urgency = "none"
            
            results.append({
                "email_id": email_id,
                "success": True,
                "category": category,
                "urgency": urgency,
                "summary": result.get("summary", "")[:500],
                "is_sales_lead": result.get("is_sales_lead", False),
                "confidence": float(result.get("confidence", 0.8)),
                "method": "openai_gpt4o_mini",
                "tokens_used": response.usage.total_tokens if response.usage else 0
            })
            
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error for {email_id}: {e}")
            results.append({
                "email_id": email_id,
                "success": False,
                "error": f"JSON parse error: {e}"
            })
        except Exception as e:
            logger.warning(f"OpenAI error for {email_id}: {e}")
            results.append({
                "email_id": email_id,
                "success": False,
                "error": str(e)
            })
    
    return results


def update_email_classifications(results: List[Dict]):
    """Update email documents with classification results"""
    operations = []
    
    for result in results:
        if not result.get("success"):
            continue
        
        email_id = result["email_id"]
        
        update_doc = {
            "ai_category": result["category"],
            "ai_urgency": result["urgency"],
            "ai_summary": result.get("summary", ""),
            "ai_confidence": result.get("confidence", 0.8),
            "ai_method": result.get("method", "openai"),
            "ai_classified_at": datetime.utcnow(),
            "ai_is_sales_lead": result.get("is_sales_lead", False),
        }
        
        operations.append(UpdateOne(
            {"_id": __import__("bson").ObjectId(email_id)},
            {"$set": update_doc}
        ))
    
    if operations:
        # Use ordered=False for parallel execution, less blocking
        result = email_metadata.bulk_write(operations, ordered=False)
        return result.modified_count
    return 0


def clear_all_classifications():
    """Clear all AI classification fields"""
    ai_fields = {
        "ai_category": "",
        "ai_confidence": "",
        "ai_priority": "",
        "ai_urgency": "",
        "ai_summary": "",
        "ai_action_items": "",
        "ai_action_required": "",
        "ai_classified_at": "",
        "ai_method": "",
        "ai_is_sales_lead": "",
        "ai_tier1_category": "",
        "ai_tier2_category": "",
        "gemini_category": "",
        "gemini_confidence": "",
        "gemini_classified_at": "",
        "gemini_is_sales_lead": "",
        "sender_info": "",
    }
    
    result = email_metadata.update_many(
        {},
        {"$unset": {field: "" for field in ai_fields.keys()}}
    )
    
    return result.modified_count


def get_unclassified_emails(limit: int = 100) -> List[Dict]:
    """Get emails that haven't been classified yet"""
    query = {
        "$or": [
            {"ai_category": {"$exists": False}},
            {"ai_category": None},
            {"ai_category": ""}
        ]
    }
    
    return list(email_metadata.find(query).limit(limit))


def generate_report() -> Dict:
    """Generate classification report"""
    total = email_metadata.count_documents({})
    
    # Category distribution
    pipeline = [
        {"$group": {"_id": "$ai_category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    categories = {doc["_id"]: doc["count"] for doc in email_metadata.aggregate(pipeline) if doc["_id"]}
    
    # Urgency distribution
    urgency_pipeline = [
        {"$group": {"_id": "$ai_urgency", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    urgencies = {doc["_id"]: doc["count"] for doc in email_metadata.aggregate(urgency_pipeline) if doc["_id"]}
    
    classified = sum(categories.values())
    
    return {
        "total_emails": total,
        "classified": classified,
        "unclassified": total - classified,
        "categories": categories,
        "urgencies": urgencies
    }


def main():
    parser = argparse.ArgumentParser(description="Classify emails using OpenAI")
    parser.add_argument("--batch-size", type=int, default=20, help="Emails per batch")
    parser.add_argument("--max-emails", type=int, default=None, help="Max emails to process")
    parser.add_argument("--reset", action="store_true", help="Clear all classifications first")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between API calls (seconds)")
    parser.add_argument("--report-only", action="store_true", help="Only show report, don't classify")
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("OPENAI EMAIL CLASSIFICATION")
    logger.info("=" * 60)
    
    # Check for OpenAI key
    openai_key = get_openai_key()
    if not openai_key:
        logger.error("❌ No OpenAI API key found!")
        logger.error("Set OPENAI_API_KEY in environment or database")
        return
    
    logger.info(f"✅ OpenAI API key found: {openai_key[:15]}...{openai_key[-5:]}")
    
    # Report only mode
    if args.report_only:
        report = generate_report()
        logger.info("\n📊 Current Classification Status:")
        logger.info(f"  Total emails: {report['total_emails']}")
        logger.info(f"  Classified: {report['classified']}")
        logger.info(f"  Unclassified: {report['unclassified']}")
        logger.info("\n  Categories:")
        for cat, count in sorted(report['categories'].items(), key=lambda x: x[1], reverse=True):
            logger.info(f"    {cat}: {count}")
        return
    
    # Reset if requested
    if args.reset:
        logger.info("\n🗑️  Clearing all previous classifications...")
        cleared = clear_all_classifications()
        logger.info(f"  Cleared {cleared} emails")
    
    # Get unclassified count
    total_unclassified = email_metadata.count_documents({
        "$or": [
            {"ai_category": {"$exists": False}},
            {"ai_category": None},
            {"ai_category": ""}
        ]
    })
    
    logger.info(f"\n📧 Unclassified emails: {total_unclassified}")
    
    if total_unclassified == 0:
        logger.info("✅ All emails are already classified!")
        return
    
    # Limit if specified
    max_to_process = args.max_emails if args.max_emails else total_unclassified
    logger.info(f"📋 Will process up to {max_to_process} emails")
    logger.info(f"⚙️  Batch size: {args.batch_size}, Delay: {args.delay}s")
    
    # Process in batches
    processed = 0
    classified = 0
    errors = 0
    total_tokens = 0
    categories_count = {}
    
    start_time = datetime.utcnow()
    
    while processed < max_to_process:
        # Get next batch
        batch_size = min(args.batch_size, max_to_process - processed)
        emails = get_unclassified_emails(limit=batch_size)
        
        if not emails:
            break
        
        logger.info(f"\n🔄 Processing batch: {processed + 1} to {processed + len(emails)}")
        
        # Classify batch
        results = classify_emails_batch(emails, openai_key)
        
        # Update database
        updated = update_email_classifications(results)
        
        # Track stats
        for result in results:
            if result.get("success"):
                classified += 1
                cat = result.get("category", "others")
                categories_count[cat] = categories_count.get(cat, 0) + 1
                total_tokens += result.get("tokens_used", 0)
            else:
                errors += 1
        
        processed += len(emails)
        
        # Progress update
        progress = (processed / max_to_process) * 100
        logger.info(f"  ✅ Batch complete: {updated} updated, {errors} errors")
        logger.info(f"  📊 Progress: {processed}/{max_to_process} ({progress:.1f}%)")
        
        # Rate limit delay - give other queries a chance
        # This reduces contention with the Mail Pool frontend
        if processed < max_to_process:
            time.sleep(max(args.delay, 0.5))  # Minimum 0.5s between batches
            
            # Extra pause every 10 batches to let frontend catch up
            if (processed // args.batch_size) % 10 == 0:
                logger.info("  ⏸️  Brief pause for database breathing room...")
                time.sleep(2)
    
    # Final report
    elapsed = (datetime.utcnow() - start_time).total_seconds()
    
    logger.info("\n" + "=" * 60)
    logger.info("CLASSIFICATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"⏱️  Time elapsed: {elapsed:.1f} seconds")
    logger.info(f"📧 Emails processed: {processed}")
    logger.info(f"✅ Successfully classified: {classified}")
    logger.info(f"❌ Errors: {errors}")
    logger.info(f"🎟️  Total tokens used: {total_tokens}")
    
    # Estimate cost (GPT-4o-mini: $0.15/1M input, $0.60/1M output)
    estimated_cost = (total_tokens / 1_000_000) * 0.30  # Rough average
    logger.info(f"💰 Estimated cost: ${estimated_cost:.4f}")
    
    logger.info("\n📊 Categories classified:")
    for cat, count in sorted(categories_count.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"  {cat}: {count}")
    
    # Final report
    report = generate_report()
    logger.info(f"\n📈 Final Status:")
    logger.info(f"  Classified: {report['classified']}/{report['total_emails']}")
    logger.info(f"  Remaining: {report['unclassified']}")


if __name__ == "__main__":
    main()
