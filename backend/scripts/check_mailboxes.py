"""Check all mailbox-related collections and sync status"""
import sys
import os
sys.path.insert(0, "/var/www/campaign_platform/backend")
os.chdir("/var/www/campaign_platform/backend")

from database import get_database
db = get_database("email_automation")
torpedo_db = get_database("torpedo_gmail")

print("=" * 70)
print("MAILBOX STATUS CHECK")
print("=" * 70)

# Check mailboxes collection (used by older IMAP system)
print("\n1. 'mailboxes' collection (old IMAP system) - email_automation:")
print("-" * 60)
for mb in db.mailboxes.find():
    print(f"   - {mb.get('email')} | Active: {mb.get('is_active')} | Provider: {mb.get('provider')}")
total1 = db.mailboxes.count_documents({})
print(f"   Total: {total1}")

# Check workspace_mailboxes collection (Gmail Workspace system) in torpedo_gmail
print("\n2. 'workspace_mailboxes' collection (Gmail Workspace) - torpedo_gmail:")
print("-" * 60)
for mb in torpedo_db.workspace_mailboxes.find():
    print(f"   - {mb.get('email')}")
    print(f"     Display: {mb.get('display_name')}")
    print(f"     Active: {mb.get('is_active')}")
    print(f"     ID: {mb.get('_id')}")
    print(f"     Email Count: {mb.get('email_count', 0)}")
    print(f"     Last Sync: {mb.get('last_sync_at')}")
    print()
total2 = torpedo_db.workspace_mailboxes.count_documents({})
print(f"   Total: {total2}")

# Check emails count
print("\n3. Email Statistics:")
print("-" * 60)
total_emails = db.emails.count_documents({})
print(f"   email_automation.emails: {total_emails}")

# Check torpedo_gmail.email_metadata collection
torpedo_emails = torpedo_db.email_metadata.count_documents({})
print(f"   torpedo_gmail.email_metadata: {torpedo_emails}")

print("\n" + "=" * 70)
