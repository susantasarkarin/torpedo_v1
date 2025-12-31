"""Quick script to check IMAP accounts and import progress"""
import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)

# Check IMAP accounts
gmail_db = client['torpedo_gmail']
email_db = client['email_automation']

print("=== IMAP Accounts ===")
accounts = list(gmail_db['imap_accounts'].find({}))
for a in accounts:
    has_pw = "YES" if a.get('password') else "NO PASSWORD"
    print(f"Email: {a.get('email')}")
    print(f"  - Active: {a.get('is_active')}")
    print(f"  - Has Password: {has_pw}")
    print(f"  - IMAP Server: {a.get('imap_server', 'imap.gmail.com')}")
    print(f"  - Last Sync: {a.get('last_sync')}")
    print()

print("\n=== Import Progress ===")
progress = list(gmail_db['import_progress'].find({}))
if not progress:
    print("No import progress records found")
for p in progress:
    print(f"Email: {p.get('email')}")
    print(f"  - Status: {p.get('status')}")
    print(f"  - Phase: {p.get('phase')}")
    print(f"  - Processed: {p.get('processed_count')}/{p.get('total_count')}")
    print(f"  - Error: {p.get('error')}")
    print()

print("\n=== Email Leads Count ===")
leads_count = email_db['email_leads'].count_documents({})
print(f"Total leads in database: {leads_count}")

print("\n=== Recent Email Sync Logs ===")
sync_logs = list(gmail_db['email_sync_log'].find({}).sort('_id', -1).limit(5))
if not sync_logs:
    print("No sync logs found")
for log in sync_logs:
    print(f"Message ID: {log.get('message_id', 'N/A')[:50]}...")
    print(f"  - Inbox: {log.get('inbox')}")
    print()
