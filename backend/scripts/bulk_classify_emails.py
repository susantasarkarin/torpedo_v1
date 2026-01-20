#!/usr/bin/env python3
"""
BULK EMAIL CLASSIFICATION
=========================

Classifies emails in TRUE BULK - multiple emails per API call.
This reduces the number of API requests significantly.

- 10 emails per API call = 100x fewer requests
- 1000 emails = 100 API calls instead of 1000

Usage:
    python scripts/bulk_classify_emails.py --batch-size 10 --max-emails 1000
"""

import os
import sys
import time
import argparse
import logging
import json
from datetime import datetime
from typing import Dict, Any, List

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

# MongoDB connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
torpedo_gmail_db = mongo_client['torpedo_gmail']
email_metadata = torpedo_gmail_db['email_metadata']
settings_db = mongo_client['torpedo_settings']

# Email categories
CATEGORIES = [
    "client", "rfq", "vendor", "internal", "promotional",
    "invoice", "banking", "automated", "bounce", "spam", "others"
]


def get_openai_key():
    """Get OpenAI API key from database or environment"""
    config = settings_db.app_settings.find_one({"_id": "app_config"})
    if config and config.get("openai_api_key"):
        return config["openai_api_key"]
    return os.getenv("OPENAI_API_KEY", "")


def get_unclassified_emails(limit: int = 100) -> List[Dict]:
    """Get unclassified emails from database"""
    query = {
        "$or": [
            {"ai_category": {"$exists": False}},
            {"ai_category": None},
            {"ai_category": ""}
        ]
    }
    
    projection = {
        "_id": 1,
        "subject": 1,
        "body_plain": 1,
        "body_html": 1,
        "from_email": 1,
        "from_name": 1
    }
    
    return list(email_metadata.find(query, projection).limit(limit))


def classify_emails_bulk(emails: List[Dict], openai_key: str, emails_per_call: int = 10) -> List[Dict]:
    """
    Classify MULTIPLE emails in a single API call.
    
    This reduces API calls by 10x (or more based on emails_per_call).
    """
    try:
        from openai import OpenAI
    except ImportError:
        logger.error("OpenAI package not installed. Run: pip install openai")
        return []
    
    client = OpenAI(api_key=openai_key)
    all_results = []
    
    # Process in sub-batches
    for i in range(0, len(emails), emails_per_call):
        batch = emails[i:i + emails_per_call]
        
        # Build combined prompt for all emails in batch
        email_entries = []
        for idx, email_doc in enumerate(batch):
            email_id = str(email_doc.get("_id", ""))
            subject = email_doc.get("subject", "")[:150]
            raw_body = email_doc.get("body_plain", "") or email_doc.get("body_html", "")
            from_email = email_doc.get("from_email", "")
            from_name = email_doc.get("from_name", "")
            
            # Truncate body to fit multiple in one request (max ~500 chars each)
            body = raw_body[:500] if raw_body else ""
            
            email_entries.append(f"""
EMAIL_{idx + 1}:
ID: {email_id}
FROM: {from_name} <{from_email}>
SUBJECT: {subject}
BODY: {body}
---""")
        
        combined_emails = "\n".join(email_entries)
        
        prompt = f"""Classify these {len(batch)} emails. For EACH email, determine:
- category: client/rfq/vendor/internal/promotional/invoice/banking/automated/bounce/spam/others
- urgency: high/medium/low/none
- is_sales_lead: true/false
- summary: 1 sentence max

{combined_emails}

Respond with a JSON array, one object per email in the SAME order:
[
  {{"id": "email_id", "category": "...", "urgency": "...", "is_sales_lead": true/false, "summary": "...", "confidence": 0.8}},
  ...
]"""

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an email classifier. Respond with valid JSON array only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=150 * len(batch),  # ~150 tokens per email
                response_format={"type": "json_object"}
            )
            
            result_text = response.choices[0].message.content
            
            try:
                parsed = json.loads(result_text)
                
                # Handle both array and object with results key
                if isinstance(parsed, list):
                    results = parsed
                elif isinstance(parsed, dict) and "results" in parsed:
                    results = parsed["results"]
                elif isinstance(parsed, dict) and "emails" in parsed:
                    results = parsed["emails"]
                else:
                    # Single object, wrap in array
                    results = [parsed]
                
                # Map results back to email IDs
                for idx, email_doc in enumerate(batch):
                    email_id = str(email_doc.get("_id", ""))
                    
                    # Try to find matching result
                    result = None
                    if idx < len(results):
                        result = results[idx]
                    else:
                        # Look for matching ID
                        for r in results:
                            if r.get("id") == email_id:
                                result = r
                                break
                    
                    if result:
                        all_results.append({
                            "email_id": email_id,
                            "success": True,
                            "category": result.get("category", "others"),
                            "urgency": result.get("urgency", "none"),
                            "is_sales_lead": result.get("is_sales_lead", False),
                            "summary": result.get("summary", ""),
                            "confidence": result.get("confidence", 0.7),
                            "method": "bulk_openai"
                        })
                    else:
                        all_results.append({
                            "email_id": email_id,
                            "success": True,
                            "category": "others",
                            "urgency": "none",
                            "summary": "Classification pending",
                            "confidence": 0.5,
                            "method": "bulk_fallback"
                        })
                
                logger.info(f"  Bulk classified {len(batch)} emails in 1 API call")
                
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error: {e}")
                # Mark all as failed
                for email_doc in batch:
                    all_results.append({
                        "email_id": str(email_doc.get("_id", "")),
                        "success": False,
                        "error": f"JSON parse error: {str(e)[:50]}"
                    })
                    
        except Exception as e:
            logger.error(f"OpenAI bulk error: {e}")
            # Mark all in batch as failed
            for email_doc in batch:
                all_results.append({
                    "email_id": str(email_doc.get("_id", "")),
                    "success": False,
                    "error": str(e)[:100]
                })
            
            # If rate limited, wait and continue
            if "429" in str(e) or "rate_limit" in str(e).lower():
                logger.warning("Rate limited, waiting 10 seconds...")
                time.sleep(10)
        
        # Small delay between bulk calls
        time.sleep(0.3)
    
    return all_results


def update_email_classifications(results: List[Dict]) -> int:
    """Bulk update email classifications in database"""
    if not results:
        return 0
    
    operations = []
    for result in results:
        if not result.get("success"):
            continue
        
        email_id = result.get("email_id")
        if not email_id:
            continue
        
        from bson import ObjectId
        try:
            oid = ObjectId(email_id)
        except:
            continue
        
        update_doc = {
            "$set": {
                "ai_category": result.get("category", "others"),
                "ai_urgency": result.get("urgency", "none"),
                "ai_summary": result.get("summary", ""),
                "ai_is_sales_lead": result.get("is_sales_lead", False),
                "ai_confidence": result.get("confidence", 0.5),
                "ai_classified_at": datetime.utcnow(),
                "ai_method": result.get("method", "bulk_openai")
            }
        }
        
        operations.append(UpdateOne({"_id": oid}, update_doc))
    
    if operations:
        result = email_metadata.bulk_write(operations, ordered=False)
        return result.modified_count
    
    return 0


def main():
    parser = argparse.ArgumentParser(description="Bulk classify emails using OpenAI")
    parser.add_argument("--emails-per-call", type=int, default=10, 
                        help="Emails to classify per API call (default: 10)")
    parser.add_argument("--max-emails", type=int, default=1000, 
                        help="Max emails to process (default: 1000)")
    parser.add_argument("--delay", type=float, default=0.5, 
                        help="Delay between API calls (seconds)")
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("BULK EMAIL CLASSIFICATION")
    logger.info("=" * 60)
    
    # Check for OpenAI key
    openai_key = get_openai_key()
    if not openai_key:
        logger.error("❌ No OpenAI API key found!")
        return
    
    logger.info(f"✅ OpenAI API key found")
    logger.info(f"📧 Emails per API call: {args.emails_per_call}")
    logger.info(f"📋 Max emails to process: {args.max_emails}")
    logger.info(f"⏱️  API calls needed: ~{args.max_emails // args.emails_per_call}")
    
    # Get unclassified count
    total_unclassified = email_metadata.count_documents({
        "$or": [
            {"ai_category": {"$exists": False}},
            {"ai_category": None},
            {"ai_category": ""}
        ]
    })
    
    logger.info(f"\n📧 Total unclassified: {total_unclassified}")
    
    if total_unclassified == 0:
        logger.info("✅ All emails are already classified!")
        return
    
    max_to_process = min(args.max_emails, total_unclassified)
    api_calls_estimate = max_to_process // args.emails_per_call
    
    logger.info(f"🚀 Starting bulk classification...")
    logger.info(f"   Processing: {max_to_process} emails")
    logger.info(f"   Estimated API calls: {api_calls_estimate}")
    
    start_time = datetime.utcnow()
    
    # Get all emails to process
    emails = get_unclassified_emails(limit=max_to_process)
    logger.info(f"   Fetched {len(emails)} emails from database")
    
    # Classify in bulk
    results = classify_emails_bulk(emails, openai_key, args.emails_per_call)
    
    # Update database
    updated = update_email_classifications(results)
    
    # Stats
    successful = sum(1 for r in results if r.get("success"))
    failed = sum(1 for r in results if not r.get("success"))
    
    elapsed = (datetime.utcnow() - start_time).total_seconds()
    
    logger.info("\n" + "=" * 60)
    logger.info("BULK CLASSIFICATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"⏱️  Time: {elapsed:.1f} seconds")
    logger.info(f"📧 Processed: {len(emails)}")
    logger.info(f"✅ Successful: {successful}")
    logger.info(f"❌ Failed: {failed}")
    logger.info(f"💾 Updated in DB: {updated}")
    logger.info(f"🚀 Speed: {len(emails) / elapsed:.1f} emails/second")


if __name__ == "__main__":
    main()
