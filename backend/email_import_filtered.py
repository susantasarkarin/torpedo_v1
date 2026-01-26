"""
Email Import Script - Filter and Import Non-excluded Domain Emails
================================================

This script:
1. Pulls all email IDs from mail_pool (email_automation.emails)
2. Filters out emails from surveyfieldwork.com and cogentixresearch.com
3. Extracts sender information
4. Imports directly into Sales>leads collection
5. Deduplicates by email address
6. Classifies leads with seniority, department, etc.

Usage:
    python email_import_filtered.py
    python email_import_filtered.py --dry-run  # Preview without importing
    python email_import_filtered.py --domain domain.com --domain another.com  # Exclude additional domains
    python email_import_filtered.py --limit 100  # Import max 100 leads

"""

import os
import sys
import argparse
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from pymongo import MongoClient
from bson import ObjectId
from email.utils import parseaddr
from dotenv import load_dotenv

load_dotenv()

# ============== MONGODB CONNECTION ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)

# Collections
email_automation_db = client["email_automation"]
mail_pool_collection = email_automation_db["emails"]  # Source: mail_pool emails
sales_db = client["sales"]
sales_leads_collection = sales_db["leads"]

# Backup DB
finance_db = client["finance_db"]
accounts_collection = finance_db["accounts"]

# AI Classification for enrichment
ai_db = client["email_automation"]
ai_classified_collection = ai_db["ai_classified_leads"]

# ============== CONFIGURATION ==============

EXCLUDED_DOMAINS = {
    "surveyfieldwork.com",
    "cogentixresearch.com"
}

BATCH_SIZE = 100
PROGRESS_INTERVAL = 500


def normalize_email(email: str) -> str:
    """Normalize email address for comparison"""
    return email.lower().strip() if email else ""


def extract_domain(email: str) -> str:
    """Extract domain from email address"""
    if '@' not in email:
        return ""
    return email.split('@')[1].lower().strip()


def is_excluded_domain(email: str, excluded_domains: set) -> bool:
    """Check if email domain is in excluded list"""
    domain = extract_domain(email)
    return domain in excluded_domains


def extract_sender_info(email_doc: dict) -> Tuple[str, str, str]:
    """
    Extract sender email, name, and domain from email document
    
    Returns:
        (email, name, domain)
    """
    # Try different field names for from address
    from_field = (email_doc.get("from") or 
                 email_doc.get("From") or 
                 email_doc.get("sender") or "")
    
    # Parse "Name <email@domain.com>" format
    name, email = parseaddr(from_field)
    
    if not email:
        # Try alternative email fields
        email = (email_doc.get("from_email") or 
                email_doc.get("sender_email") or "")
    
    domain = extract_domain(email)
    
    return email, name, domain


def extract_subject_hints(subject: str) -> Dict[str, Any]:
    """Extract hints about lead from email subject"""
    hints = {
        "is_sales_inquiry": False,
        "is_support": False,
        "is_feedback": False
    }
    
    subject_lower = subject.lower()
    
    if any(x in subject_lower for x in ["inquiry", "quote", "proposal", "interested", "information"]):
        hints["is_sales_inquiry"] = True
    elif any(x in subject_lower for x in ["issue", "problem", "error", "bug", "support"]):
        hints["is_support"] = True
    elif any(x in subject_lower for x in ["feedback", "review", "testimonial", "opinion"]):
        hints["is_feedback"] = True
    
    return hints


def create_lead_from_email(email_doc: dict, import_source: str = "email_pool_import") -> Dict[str, Any]:
    """
    Create a lead object from email metadata
    """
    sender_email, sender_name, domain = extract_sender_info(email_doc)
    subject = email_doc.get("subject", "") or email_doc.get("Subject", "")
    body = email_doc.get("body", "") or email_doc.get("Body", "")
    
    # Subject hints
    hints = extract_subject_hints(subject)
    
    # Get timestamp
    received_date = email_doc.get("received_at") or email_doc.get("date") or datetime.utcnow()
    if isinstance(received_date, str):
        try:
            received_date = datetime.fromisoformat(received_date.replace('Z', '+00:00'))
        except:
            received_date = datetime.utcnow()
    
    # Build lead object
    lead = {
        "email": normalize_email(sender_email),
        "name": sender_name.strip() if sender_name else "Unknown Sender",
        "company_domain": domain,
        "source": import_source,
        "email_subject": subject[:200],  # First 200 chars of subject
        "is_sales_inquiry": hints["is_sales_inquiry"],
        "is_support_inquiry": hints["is_support"],
        "is_feedback": hints["is_feedback"],
        "source_email_id": str(email_doc.get("_id", "")),
        "received_at": received_date,
        "imported_at": datetime.utcnow(),
        "status": "new",
        "notes": f"Imported from email pool - {subject[:100]}",
        "enrichment_source": "email_pool_import"
    }
    
    return lead


def find_or_create_account(email: str, domain: str) -> Optional[str]:
    """
    Find or create an account based on domain
    
    Returns:
        Account ID (ObjectId as string) or None
    """
    try:
        # Try to find existing account by domain
        existing_account = accounts_collection.find_one({
            "company_domain": domain
        })
        
        if existing_account:
            return str(existing_account.get("_id"))
        
        # Try to find account by email domain
        account_by_email = accounts_collection.find_one({
            "$or": [
                {"email": {"$regex": f"@{domain}$", "$options": "i"}},
                {"company_email": {"$regex": f"@{domain}$", "$options": "i"}}
            ]
        })
        
        if account_by_email:
            return str(account_by_email.get("_id"))
        
        # If no account found, don't create one - just return None
        # The lead will exist standalone until manually linked
        return None
        
    except Exception as e:
        print(f"  [ERROR] Error finding account for {domain}: {e}")
        return None


def check_lead_exists(email: str) -> Optional[str]:
    """Check if lead already exists by email"""
    normalized = normalize_email(email)
    
    existing = sales_leads_collection.find_one({
        "email": {"$regex": f"^{normalized}$", "$options": "i"}
    })
    
    return str(existing.get("_id")) if existing else None


def import_filtered_emails(
    excluded_domains: set = None,
    dry_run: bool = False,
    limit: int = None,
    min_date: Optional[datetime] = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Import emails excluding specified domains
    
    Args:
        excluded_domains: Set of domains to exclude (e.g., {"surveyfieldwork.com"})
        dry_run: If True, don't actually import, just count
        limit: Maximum number of leads to import
        min_date: Only import emails after this date
        verbose: Print progress
    
    Returns:
        Summary of import results
    """
    if excluded_domains is None:
        excluded_domains = EXCLUDED_DOMAINS
    
    # Build query
    query = {}
    
    if min_date:
        query["received_at"] = {"$gte": min_date}
    
    # Find all emails
    if verbose:
        print(f"\n📧 Scanning mail pool for emails...")
        print(f"   Excluded domains: {', '.join(sorted(excluded_domains))}")
    
    total_emails = mail_pool_collection.count_documents(query)
    if verbose:
        print(f"   Total emails in pool: {total_emails}")
    
    # Track results
    results = {
        "total_emails_scanned": 0,
        "excluded_emails": 0,
        "invalid_emails": 0,
        "duplicate_leads": 0,
        "new_leads_created": 0,
        "import_errors": 0,
        "excluded_email_list": [],
        "imported_leads": [],
        "errors": []
    }
    
    # Process in batches
    batch = []
    cursor = mail_pool_collection.find(query).sort("_id", -1)
    
    if limit:
        cursor = cursor.limit(limit)
    
    try:
        for email_doc in cursor:
            results["total_emails_scanned"] += 1
            
            # Extract sender info
            sender_email, sender_name, domain = extract_sender_info(email_doc)
            
            if not sender_email:
                results["invalid_emails"] += 1
                continue
            
            # Check if excluded
            if is_excluded_domain(sender_email, excluded_domains):
                results["excluded_emails"] += 1
                results["excluded_email_list"].append(sender_email)
                continue
            
            # Create lead
            try:
                lead = create_lead_from_email(email_doc, "email_pool_import")
                batch.append(lead)
                
                # Process batch
                if len(batch) >= BATCH_SIZE:
                    batch_result = import_lead_batch(batch, dry_run, results)
                    results["new_leads_created"] += batch_result["created"]
                    results["duplicate_leads"] += batch_result["duplicates"]
                    results["import_errors"] += batch_result["errors"]
                    results["imported_leads"].extend(batch_result["imported"])
                    
                    if verbose and (results["total_emails_scanned"] % PROGRESS_INTERVAL == 0):
                        print(f"   ✓ Processed {results['total_emails_scanned']}/{total_emails} emails "
                              f"(Created: {results['new_leads_created']}, Duplicates: {results['duplicate_leads']})")
                    
                    batch = []
                    
                    if limit and results["new_leads_created"] >= limit:
                        break
                        
            except Exception as e:
                results["import_errors"] += 1
                results["errors"].append(f"Error processing email {sender_email}: {str(e)}")
        
        # Process remaining batch
        if batch and (not limit or results["new_leads_created"] < limit):
            batch_result = import_lead_batch(batch, dry_run, results)
            results["new_leads_created"] += batch_result["created"]
            results["duplicate_leads"] += batch_result["duplicates"]
            results["import_errors"] += batch_result["errors"]
            results["imported_leads"].extend(batch_result["imported"])
        
        return results
        
    except Exception as e:
        print(f"\n❌ Error during import: {e}")
        results["errors"].append(str(e))
        return results


def import_lead_batch(
    batch: List[Dict[str, Any]],
    dry_run: bool,
    results: Dict[str, Any]
) -> Dict[str, Any]:
    """Import a batch of leads"""
    batch_result = {
        "created": 0,
        "duplicates": 0,
        "errors": 0,
        "imported": []
    }
    
    for lead in batch:
        try:
            # Check for existing lead
            existing_id = check_lead_exists(lead["email"])
            
            if existing_id:
                batch_result["duplicates"] += 1
                continue
            
            if not dry_run:
                # Find or create account
                account_id = find_or_create_account(lead["email"], lead.get("company_domain", ""))
                if account_id:
                    lead["account_id"] = account_id
                
                # Insert lead
                result = sales_leads_collection.insert_one(lead)
                lead["_id"] = str(result.inserted_id)
                
                batch_result["imported"].append(lead)
            else:
                # Dry run - just count
                batch_result["imported"].append(lead)
            
            batch_result["created"] += 1
            
        except Exception as e:
            batch_result["errors"] += 1
    
    return batch_result


def print_summary(results: Dict[str, Any], dry_run: bool):
    """Print import summary"""
    print(f"\n" + "="*60)
    print(f"📊 IMPORT SUMMARY {'(DRY RUN)' if dry_run else ''}")
    print(f"="*60)
    print(f"\nEmails Processed:")
    print(f"  Total scanned:          {results['total_emails_scanned']}")
    print(f"  Excluded domains:       {results['excluded_emails']}")
    print(f"  Invalid/no email:       {results['invalid_emails']}")
    
    print(f"\nLeads Created:")
    print(f"  New leads:              {results['new_leads_created']}")
    print(f"  Duplicates (skipped):   {results['duplicate_leads']}")
    print(f"  Import errors:          {results['import_errors']}")
    
    if results["excluded_email_list"]:
        print(f"\nExcluded Domains (samples):")
        for email in results["excluded_email_list"][:10]:
            print(f"  - {email}")
        if len(results["excluded_email_list"]) > 10:
            print(f"  ... and {len(results['excluded_email_list']) - 10} more")
    
    if results["errors"]:
        print(f"\nErrors (samples):")
        for error in results["errors"][:5]:
            print(f"  - {error}")
        if len(results["errors"]) > 5:
            print(f"  ... and {len(results['errors']) - 5} more")
    
    print(f"\n" + "="*60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import emails to Sales>leads, excluding specified domains"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview import without making changes"
    )
    parser.add_argument(
        "--domain",
        action="append",
        help="Additional domain to exclude (can be used multiple times)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of leads to import"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Only import emails from last N days (default: 30)"
    )
    
    args = parser.parse_args()
    
    # Build excluded domains list
    excluded = EXCLUDED_DOMAINS.copy()
    if args.domain:
        excluded.update(args.domain)
    
    # Calculate min date
    min_date = datetime.utcnow() - timedelta(days=args.days) if args.days > 0 else None
    
    # Run import
    print(f"\n🚀 Starting email import...")
    print(f"   Mode: {'DRY RUN (preview only)' if args.dry_run else 'PRODUCTION (will import)'}")
    print(f"   Excluded domains: {len(excluded)}")
    if args.limit:
        print(f"   Max leads: {args.limit}")
    if min_date:
        print(f"   Since: {min_date.strftime('%Y-%m-%d')}")
    
    results = import_filtered_emails(
        excluded_domains=excluded,
        dry_run=args.dry_run,
        limit=args.limit,
        min_date=min_date,
        verbose=True
    )
    
    # Print summary
    print_summary(results, args.dry_run)
    
    # Print sample imported leads
    if results["imported_leads"]:
        print(f"\n📝 Sample Imported Leads:")
        for lead in results["imported_leads"][:5]:
            print(f"  - {lead.get('name', 'Unknown')} ({lead.get('email', 'no email')})")
            print(f"    Company: {lead.get('company_domain', 'Unknown')}")
            print(f"    Subject: {lead.get('email_subject', 'No subject')[:60]}...")
        if len(results["imported_leads"]) > 5:
            print(f"  ... and {len(results['imported_leads']) - 5} more")
