#!/usr/bin/env python3
"""
RESET AND RECLASSIFY ALL EMAILS
================================

This script:
1. Clears all previous AI classifications from emails
2. Syncs any new emails via Google Workspace API
3. Re-classifies all emails using DeepSeek AI (via openai_wrapper)
4. Generates a summary report

Usage:
    python scripts/reset_and_reclassify.py [--sync-only] [--classify-only] [--batch-size N]
"""

import os
import sys
import time
import argparse
import logging
from datetime import datetime
from typing import Dict, Any, List

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from database import get_database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def clear_all_classifications(dry_run: bool = False) -> Dict[str, Any]:
    """
    Clear all AI classification fields from email_metadata collection.
    
    Returns summary of operation.
    """
    db = get_database('torpedo_gmail')
    
    # Fields to clear
    ai_fields = {
        "ai_category": None,
        "ai_confidence": None,
        "ai_priority": None,
        "ai_urgency": None,
        "ai_summary": None,
        "ai_action_items": None,
        "ai_action_required": None,
        "ai_classified_at": None,
        "ai_method": None,
        "ai_tier1_category": None,
        "ai_tier2_category": None,
        "gemini_category": None,
        "gemini_confidence": None,
        "gemini_classified_at": None,
        "gemini_is_sales_lead": None,
        "gemini_lead_id": None,
        "sender_info": None,
    }
    
    # Count emails with classifications
    has_classification = db.email_metadata.count_documents({
        "$or": [
            {"ai_category": {"$exists": True, "$nin": [None, ""]}},
            {"gemini_category": {"$exists": True, "$nin": [None, ""]}},
            {"ai_summary": {"$exists": True, "$nin": [None, ""]}},
        ]
    })
    
    total_emails = db.email_metadata.count_documents({})
    
    logger.info(f"Total emails: {total_emails}")
    logger.info(f"Emails with classification: {has_classification}")
    
    if dry_run:
        logger.info("DRY RUN - No changes made")
        return {
            "success": True,
            "dry_run": True,
            "total_emails": total_emails,
            "would_clear": has_classification
        }
    
    # Clear all AI fields using $unset
    result = db.email_metadata.update_many(
        {},  # All documents
        {"$unset": {field: "" for field in ai_fields.keys()}}
    )
    
    logger.info(f"✅ Cleared classifications from {result.modified_count} emails")
    
    # Also clear the gemini classification logs
    log_count = db.gemini_classification_logs.count_documents({})
    if log_count > 0:
        db.gemini_classification_logs.delete_many({})
        logger.info(f"✅ Cleared {log_count} classification log entries")
    
    return {
        "success": True,
        "total_emails": total_emails,
        "cleared": result.modified_count,
        "logs_cleared": log_count
    }


def sync_google_workspace_emails() -> Dict[str, Any]:
    """
    Trigger a full sync of all workspace mailboxes via Google API.
    
    Returns summary of sync operation.
    """
    db = get_database('torpedo_gmail')
    
    # Get all active workspace mailboxes
    mailboxes = list(db.workspace_mailboxes.find({"is_active": True}))
    
    if not mailboxes:
        logger.warning("No active workspace mailboxes found!")
        return {
            "success": False,
            "error": "No active mailboxes configured"
        }
    
    logger.info(f"Found {len(mailboxes)} active mailboxes to sync")
    
    results = {
        "success": True,
        "mailboxes": [],
        "total_new_emails": 0
    }
    
    try:
        from app.services.gmail_workspace_service import GmailWorkspaceService
        
        service = GmailWorkspaceService()
        
        for mailbox in mailboxes:
            email = mailbox.get("email")
            mailbox_id = str(mailbox.get("_id"))
            logger.info(f"Syncing {email}...")
            
            try:
                # Perform incremental sync using history API
                sync_result = service.sync_mailbox(mailbox_id)
                
                new_emails = sync_result.get("new_emails", 0)
                results["mailboxes"].append({
                    "email": email,
                    "success": True,
                    "new_emails": new_emails,
                    "history_id": sync_result.get("history_id")
                })
                results["total_new_emails"] += new_emails
                
                logger.info(f"  ✅ {email}: {new_emails} new emails")
                
            except Exception as e:
                logger.error(f"  ❌ {email}: {str(e)}")
                results["mailboxes"].append({
                    "email": email,
                    "success": False,
                    "error": str(e)
                })
    
    except ImportError as e:
        logger.error(f"Could not import GmailWorkspaceService: {e}")
        results["success"] = False
        results["error"] = f"Import error: {e}"
    
    return results


def classify_all_emails(
    batch_size: int = 50,
    delay_seconds: float = 5.0,
    max_batches: int = None
) -> Dict[str, Any]:
    """
    Re-classify all emails using Gemini AI.
    
    Args:
        batch_size: Number of emails per batch
        delay_seconds: Delay between API calls (rate limiting)
        max_batches: Maximum batches to process (None = all)
    
    Returns summary of classification.
    """
    db = get_database('torpedo_gmail')
    
    # Import classification function (now uses DeepSeek via openai_wrapper)
    try:
        from leads.email_classifier import (
            classify_and_summarize,
            email_metadata
        )
    except ImportError as e:
        logger.error(f"Could not import classifier: {e}")
        return {
            "success": False,
            "error": f"Import error: {e}"
        }
    
    # Check DeepSeek/OpenAI availability
    try:
        from leads.openai_wrapper import get_deepseek_api_key, get_openai_api_key
        has_deepseek = bool(get_deepseek_api_key())
        has_openai = bool(get_openai_api_key())
        if not has_deepseek and not has_openai:
            return {
                "success": False,
                "error": "No AI API key configured (DeepSeek or OpenAI)",
                "status": {"deepseek": has_deepseek, "openai": has_openai}
            }
        logger.info(f"AI Status: DeepSeek={has_deepseek}, OpenAI={has_openai}")
    except Exception as e:
        logger.warning(f"Could not check AI status: {e}")
    
    # Count unclassified emails
    unclassified_query = {
        "$or": [
            {"ai_category": {"$exists": False}},
            {"ai_category": None},
            {"ai_category": ""}
        ]
    }
    
    total_unclassified = db.email_metadata.count_documents(unclassified_query)
    logger.info(f"Total unclassified emails: {total_unclassified}")
    
    if total_unclassified == 0:
        return {
            "success": True,
            "message": "No emails to classify",
            "processed": 0
        }
    
    results = {
        "success": True,
        "total_unclassified": total_unclassified,
        "processed": 0,
        "classified": 0,
        "leads_extracted": 0,
        "errors": 0,
        "categories": {},
        "start_time": datetime.utcnow().isoformat(),
        "batches_processed": 0
    }
    
    batch_num = 0
    
    while True:
        # Check if we've hit max batches
        if max_batches and batch_num >= max_batches:
            logger.info(f"Reached max batches limit: {max_batches}")
            break
        
        # Get next batch
        emails = list(db.email_metadata.find(unclassified_query).limit(batch_size))
        
        if not emails:
            logger.info("No more unclassified emails")
            break
        
        batch_num += 1
        logger.info(f"Processing batch {batch_num} ({len(emails)} emails)...")
        
        for i, email_doc in enumerate(emails):
            email_id = str(email_doc.get("_id", ""))
            subject = email_doc.get("subject", "")[:100]
            body = email_doc.get("body_plain", "") or email_doc.get("body_html", "")
            from_email = email_doc.get("from_email", "")
            to_emails = email_doc.get("to_emails", [])
            to_email = to_emails[0] if to_emails else ""
            
            try:
                classification = classify_and_summarize(
                    email_id=email_id,
                    subject=subject,
                    body=body[:5000] if body else "",  # Limit body size
                    from_email=from_email,
                    from_name=email_doc.get("from_name", ""),
                    to_email=to_email,
                    source="reset_reclassify"
                )
                
                results["processed"] += 1
                
                if classification.get("success"):
                    results["classified"] += 1
                    category = classification.get("category", "unknown")
                    results["categories"][category] = results["categories"].get(category, 0) + 1
                    
                    if classification.get("lead_extracted"):
                        results["leads_extracted"] += 1
                else:
                    results["errors"] += 1
                    logger.warning(f"Classification failed for {email_id}: {classification.get('error')}")
            
            except Exception as e:
                results["errors"] += 1
                logger.error(f"Error classifying {email_id}: {e}")
            
            # Rate limit delay
            if i < len(emails) - 1:
                time.sleep(delay_seconds)
        
        results["batches_processed"] = batch_num
        
        # Log progress
        progress = (results["processed"] / total_unclassified) * 100
        logger.info(f"Progress: {results['processed']}/{total_unclassified} ({progress:.1f}%)")
        logger.info(f"  Classified: {results['classified']}, Errors: {results['errors']}")
    
    results["end_time"] = datetime.utcnow().isoformat()
    return results


def generate_summary_report() -> Dict[str, Any]:
    """Generate a summary report of all classifications."""
    db = get_database('torpedo_gmail')
    
    # Get category distribution
    pipeline = [
        {"$group": {"_id": "$ai_category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    categories = list(db.email_metadata.aggregate(pipeline))
    
    # Get urgency distribution
    urgency_pipeline = [
        {"$group": {"_id": "$ai_urgency", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    urgencies = list(db.email_metadata.aggregate(urgency_pipeline))
    
    # Get mailbox stats
    mailbox_pipeline = [
        {"$group": {"_id": "$mailbox_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    mailbox_stats = list(db.email_metadata.aggregate(mailbox_pipeline))
    
    # Counts
    total = db.email_metadata.count_documents({})
    classified = db.email_metadata.count_documents({
        "gemini_category": {"$exists": True, "$nin": [None, ""]}
    })
    with_summary = db.email_metadata.count_documents({
        "ai_summary": {"$exists": True, "$nin": [None, ""]}
    })
    
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "total_emails": total,
        "classified": classified,
        "with_summary": with_summary,
        "unclassified": total - classified,
        "categories": {doc["_id"]: doc["count"] for doc in categories if doc["_id"]},
        "urgencies": {doc["_id"]: doc["count"] for doc in urgencies if doc["_id"]},
        "mailbox_counts": {str(doc["_id"]): doc["count"] for doc in mailbox_stats}
    }
    
    return report


def main():
    parser = argparse.ArgumentParser(description="Reset and reclassify all emails")
    parser.add_argument("--sync-only", action="store_true", help="Only sync emails, don't classify")
    parser.add_argument("--classify-only", action="store_true", help="Only classify, don't sync")
    parser.add_argument("--skip-clear", action="store_true", help="Skip clearing existing classifications")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--batch-size", type=int, default=50, help="Emails per batch (default: 50)")
    parser.add_argument("--max-batches", type=int, default=None, help="Max batches to process")
    parser.add_argument("--delay", type=float, default=5.0, help="Delay between API calls in seconds")
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("EMAIL RESET AND RECLASSIFICATION")
    logger.info("=" * 60)
    
    # Step 1: Clear classifications (unless --skip-clear or --sync-only)
    if not args.skip_clear and not args.sync_only:
        logger.info("\n📋 Step 1: Clearing previous classifications...")
        clear_result = clear_all_classifications(dry_run=args.dry_run)
        logger.info(f"Clear result: {clear_result}")
    else:
        logger.info("\n📋 Step 1: Skipping classification clear")
    
    # Step 2: Sync emails (unless --classify-only)
    if not args.classify_only and not args.dry_run:
        logger.info("\n📥 Step 2: Syncing emails via Google Workspace API...")
        sync_result = sync_google_workspace_emails()
        logger.info(f"Sync result: {sync_result}")
    else:
        logger.info("\n📥 Step 2: Skipping email sync")
    
    # Step 3: Classify all emails (unless --sync-only)
    if not args.sync_only and not args.dry_run:
        logger.info("\n🤖 Step 3: Classifying all emails with Gemini AI...")
        logger.info(f"  Batch size: {args.batch_size}")
        logger.info(f"  Delay: {args.delay}s")
        if args.max_batches:
            logger.info(f"  Max batches: {args.max_batches}")
        
        classify_result = classify_all_emails(
            batch_size=args.batch_size,
            delay_seconds=args.delay,
            max_batches=args.max_batches
        )
        logger.info(f"Classification result: {classify_result}")
    else:
        logger.info("\n🤖 Step 3: Skipping classification")
    
    # Step 4: Generate summary report
    logger.info("\n📊 Step 4: Generating summary report...")
    report = generate_summary_report()
    
    logger.info("\n" + "=" * 60)
    logger.info("FINAL REPORT")
    logger.info("=" * 60)
    logger.info(f"Total Emails: {report['total_emails']}")
    logger.info(f"Classified: {report['classified']}")
    logger.info(f"With Summary: {report['with_summary']}")
    logger.info(f"Unclassified: {report['unclassified']}")
    logger.info("\nCategory Distribution:")
    for cat, count in sorted(report['categories'].items(), key=lambda x: x[1], reverse=True):
        logger.info(f"  {cat}: {count}")
    
    logger.info("\n✅ Complete!")
    return report


if __name__ == "__main__":
    main()
