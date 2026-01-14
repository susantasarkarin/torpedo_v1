#!/usr/bin/env python3
"""
Mail Pool Deployment Diagnostic Script
=======================================
This script performs comprehensive checks for the Mail Pool system:
1. Signature integrity (orphaned signatures)
2. Thread ID coverage (legacy emails)
3. Database field consistency
4. Case sensitivity issues

Run: python debug_mailpool.py
"""

import os
import sys
from pymongo import MongoClient
from datetime import datetime
from collections import Counter
from dotenv import load_dotenv

# Load environment
load_dotenv()

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)

# Databases
settings_db = client["torpedo_settings"]
email_automation_db = client["email_automation"]
gmail_db = client["torpedo_gmail"]

# Collections
email_signatures = settings_db["email_signatures"]
workspace_mailboxes = settings_db["workspace_mailboxes"]
emails = email_automation_db["emails"]
accounts = gmail_db["accounts"]


def separator(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def check_signature_orphans():
    """Step 2: Check for orphaned signatures - signatures without matching mailbox"""
    separator("SIGNATURE INTEGRITY CHECK")
    
    # Get all signature emails
    sig_emails = set()
    for sig in email_signatures.find({}, {"email": 1}):
        email = sig.get("email", "").strip().lower()
        if email:
            sig_emails.add(email)
    
    # Get all mailbox emails
    mailbox_emails = set()
    for mb in workspace_mailboxes.find({}, {"email": 1}):
        email = mb.get("email", "").strip().lower()
        if email:
            mailbox_emails.add(email)
    
    # Get all gmail account emails
    account_emails = set()
    for acc in accounts.find({}, {"email": 1, "aliases": 1}):
        email = acc.get("email", "").strip().lower()
        if email:
            account_emails.add(email)
        # Check aliases
        for alias in acc.get("aliases", []):
            if isinstance(alias, str):
                account_emails.add(alias.strip().lower())
            elif isinstance(alias, dict):
                alias_email = alias.get("email", "").strip().lower()
                if alias_email:
                    account_emails.add(alias_email)
    
    # Find orphaned signatures (in email_signatures but not in mailboxes or accounts)
    all_mailbox_emails = mailbox_emails | account_emails
    orphaned = sig_emails - all_mailbox_emails
    
    print(f"Total signatures in email_signatures: {len(sig_emails)}")
    print(f"Total emails in workspace_mailboxes: {len(mailbox_emails)}")
    print(f"Total emails in gmail accounts: {len(account_emails)}")
    print()
    
    if orphaned:
        print(f"⚠️  ORPHANED SIGNATURES FOUND: {len(orphaned)}")
        for email in sorted(orphaned):
            print(f"   - {email}")
    else:
        print("✅ No orphaned signatures found")
    
    # Check for case sensitivity issues
    print("\n--- Case Sensitivity Check ---")
    sig_emails_raw = [sig.get("email", "") for sig in email_signatures.find({}, {"email": 1})]
    sig_emails_lower = [e.lower() for e in sig_emails_raw]
    
    case_issues = []
    for i, email in enumerate(sig_emails_raw):
        if email != email.lower():
            case_issues.append(email)
    
    if case_issues:
        print(f"⚠️  CASE SENSITIVITY ISSUES in email_signatures:")
        for email in case_issues:
            print(f"   - '{email}' (should be '{email.lower()}')")
    else:
        print("✅ No case sensitivity issues in signatures")
    
    # Check for trailing spaces
    print("\n--- Trailing Space Check ---")
    space_issues = [e for e in sig_emails_raw if e != e.strip()]
    if space_issues:
        print(f"⚠️  TRAILING SPACES FOUND:")
        for email in space_issues:
            print(f"   - '{email}' -> '{email.strip()}'")
    else:
        print("✅ No trailing space issues")


def check_thread_id_coverage():
    """Step 3: Check for legacy emails missing provider_thread_id"""
    separator("THREAD ID COVERAGE CHECK")
    
    # Count emails with and without thread_id
    total = emails.count_documents({})
    with_thread_id = emails.count_documents({
        "$or": [
            {"provider_thread_id": {"$exists": True, "$ne": None, "$ne": ""}},
            {"gmail_thread_id": {"$exists": True, "$ne": None, "$ne": ""}}
        ]
    })
    without_thread_id = total - with_thread_id
    
    print(f"Total emails: {total}")
    print(f"With thread ID: {with_thread_id} ({100*with_thread_id/total:.1f}%)" if total else "")
    print(f"Without thread ID: {without_thread_id} ({100*without_thread_id/total:.1f}%)" if total else "")
    
    if without_thread_id > 0:
        print(f"\n⚠️  {without_thread_id} 'legacy' emails may not display threads correctly")
        # Sample some without thread ID
        sample = list(emails.find({
            "provider_thread_id": {"$exists": False}
        }).limit(5))
        if sample:
            print("\nSample emails without thread_id:")
            for e in sample:
                print(f"   - {e.get('subject', '(no subject)')[:50]} | {e.get('timestamp', 'N/A')}")
    else:
        print("✅ All emails have thread IDs")


def check_inbox_count_fields():
    """Step 1 related: Verify inbox count logic"""
    separator("INBOX COUNT FIELDS CHECK")
    
    # Check mailbox_id field distribution
    with_mailbox_id = emails.count_documents({"mailbox_id": {"$exists": True, "$ne": None}})
    total = emails.count_documents({})
    
    print(f"Total emails: {total}")
    print(f"With mailbox_id: {with_mailbox_id}")
    
    if with_mailbox_id < total:
        print(f"⚠️  {total - with_mailbox_id} emails missing mailbox_id - counts may be inaccurate")
    else:
        print("✅ All emails have mailbox_id")
    
    # Check direction field
    direction_stats = list(emails.aggregate([
        {"$group": {"_id": "$direction", "count": {"$sum": 1}}}
    ]))
    print("\nDirection breakdown:")
    for d in direction_stats:
        print(f"   {d['_id'] or '(null)'}: {d['count']}")
    
    # Per-account counts
    print("\nPer-account inbox counts:")
    for acc in workspace_mailboxes.find({}, {"email": 1, "_id": 1}):
        acc_id = str(acc["_id"])
        acc_email = acc.get("email", "unknown")
        count = emails.count_documents({
            "mailbox_id": acc_id,
            "direction": "inbound"
        })
        print(f"   {acc_email}: {count} inbound emails")


def check_api_response_structure():
    """Check sample email structure matches frontend expectations"""
    separator("API RESPONSE STRUCTURE CHECK")
    
    # Get a sample email
    sample = emails.find_one({"provider_thread_id": {"$exists": True, "$ne": None}})
    
    if not sample:
        sample = emails.find_one({})
    
    if not sample:
        print("❌ No emails found in database")
        return
    
    required_fields = [
        "provider_thread_id", "gmail_thread_id",  # Threading
        "from_address", "to_addresses",            # Addresses
        "subject", "body_plain", "body_html",     # Content
        "timestamp", "direction",                  # Metadata
        "mailbox_id"                               # Account linking
    ]
    
    print("Sample email structure check:")
    for field in required_fields:
        exists = field in sample and sample[field] not in [None, "", []]
        status = "✅" if exists else "⚠️ "
        value = sample.get(field, "N/A")
        if isinstance(value, str) and len(value) > 50:
            value = value[:50] + "..."
        print(f"   {status} {field}: {type(value).__name__} = {value}")


def run_all_checks():
    """Run all diagnostic checks"""
    print("\n" + "="*60)
    print("  MAIL POOL DEPLOYMENT DIAGNOSTICS")
    print(f"  Run Time: {datetime.now().isoformat()}")
    print("="*60)
    
    try:
        check_signature_orphans()
        check_thread_id_coverage()
        check_inbox_count_fields()
        check_api_response_structure()
        
        separator("SUMMARY")
        print("All diagnostics complete. Review warnings above.")
        print("\nNext steps:")
        print("1. Fix any orphaned signatures or case issues")
        print("2. Backfill provider_thread_id for legacy emails if needed")
        print("3. Ensure mailbox_id is set for accurate counts")
        
    except Exception as e:
        print(f"\n❌ Error running diagnostics: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.close()


if __name__ == "__main__":
    run_all_checks()
