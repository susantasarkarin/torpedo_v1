from database import get_database
import json

db = get_database("email_automation")

# Check mailboxes collection
print("Mailboxes Collection:")
for m in db.mailboxes.find():
    print(f"  - {m}")

# Check accounts collection
print()
print("Accounts Collection:")
for a in db.accounts.find():
    print(f"  - {a}")

# Get gmail settings
settings = db.settings.find_one({"type": "gmail_settings"})
if settings:
    accounts = settings.get("accounts", [])
    print("Gmail Accounts Configured:")
    for acc in accounts:
        email = acc.get("email", "unknown")
        print(f"  - {email}")
else:
    print("No gmail settings found")

# Check for old IMAP/SMTP emails vs Gmail API emails
print()
print("Email sources:")
imap_count = db.emails.count_documents({"source": "imap"})
smtp_count = db.emails.count_documents({"source": "smtp"})
gmail_count = db.emails.count_documents({"source": "gmail_api"})
no_source = db.emails.count_documents({"source": {"$exists": False}})
print(f"  IMAP emails: {imap_count}")
print(f"  SMTP emails: {smtp_count}")
print(f"  Gmail API emails: {gmail_count}")
print(f"  No source field: {no_source}")

# Count by account
print()
print("Emails by account:")
pipeline = [{"$group": {"_id": "$account_email", "count": {"$sum": 1}}}]
for doc in db.emails.aggregate(pipeline):
    print(f"  {doc['_id']}: {doc['count']}")
