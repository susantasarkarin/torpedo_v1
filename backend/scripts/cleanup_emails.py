"""
Script to clean up old emails and reconfigure mailboxes for Gmail sync
"""
import sys
import os
sys.path.insert(0, "/var/www/campaign_platform/backend")
os.chdir("/var/www/campaign_platform/backend")

from database import get_database
from bson import ObjectId
from datetime import datetime

db = get_database("email_automation")

print("=" * 60)
print("EMAIL CLEANUP AND MAILBOX RECONFIGURATION")
print("=" * 60)

# 1. Check current state
print("\n1. Current State Analysis:")
print("-" * 40)

total_emails = db.emails.count_documents({})
emails_no_source = db.emails.count_documents({"source": {"$exists": False}})
emails_no_account = db.emails.count_documents({"account_email": None})
emails_with_mailbox = db.emails.count_documents({"mailbox_id": {"$exists": True, "$ne": None}})

print(f"   Total emails: {total_emails}")
print(f"   Emails without source field: {emails_no_source}")
print(f"   Emails with account_email=None: {emails_no_account}")
print(f"   Emails with mailbox_id: {emails_with_mailbox}")

# 2. Show mailboxes
print("\n2. Current Mailboxes:")
print("-" * 40)
mailboxes = list(db.mailboxes.find())
for mb in mailboxes:
    print(f"   - {mb.get('email')} ({mb.get('provider', 'unknown')}) - ID: {mb['_id']}")

# 3. Check for emails that have proper gmail metadata
print("\n3. Checking for Gmail-synced emails:")
print("-" * 40)
gmail_emails = db.emails.count_documents({"source": "gmail_api"})
print(f"   Gmail API emails: {gmail_emails}")

# Check for emails with message_id (likely properly synced)
with_message_id = db.emails.count_documents({"message_id": {"$exists": True, "$ne": None}})
print(f"   Emails with message_id: {with_message_id}")

# 4. Decision point
print("\n4. Cleanup Recommendation:")
print("-" * 40)

if emails_no_source > 0 or emails_no_account > 0:
    print(f"   Found {max(emails_no_source, emails_no_account)} old emails without proper metadata")
    print("   These are from old IMAP sync and should be deleted")
    print("")
    
    # Auto-confirm deletion
    print("   Auto-confirming deletion...")
    
    # Delete emails without source or account_email
    result = db.emails.delete_many({
        "$or": [
            {"source": {"$exists": False}},
            {"account_email": None, "mailbox_id": {"$exists": False}}
        ]
    })
    print(f"\n   ✅ Deleted {result.deleted_count} old emails")
    
    # Update remaining count
    remaining = db.emails.count_documents({})
    print(f"   Remaining emails: {remaining}")

# 5. Check if mailbox needs updating
print("\n5. Mailbox Status:")
print("-" * 40)

# The IMAP mailbox should be marked as inactive if we're using Gmail now
imap_mailboxes = list(db.mailboxes.find({"provider": "imap"}))
if imap_mailboxes:
    print(f"   Found {len(imap_mailboxes)} IMAP mailbox(es)")
    for mb in imap_mailboxes:
        print(f"   - {mb.get('email')}")
    
    print("   Auto-confirming deactivation...")
    result = db.mailboxes.update_many(
        {"provider": "imap"},
        {"$set": {"is_active": False, "sync_enabled": False}}
    )
    print(f"   ✅ Deactivated {result.modified_count} IMAP mailbox(es)")

print("\n" + "=" * 60)
print("CLEANUP COMPLETE")
print("=" * 60)
print("\nNext steps:")
print("1. Go to Gmail Settings in the app to configure Gmail accounts")
print("2. Add mailboxes using the Gmail Workspace integration")
print("3. Sync emails from the configured mailboxes")
