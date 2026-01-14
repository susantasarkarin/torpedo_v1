"""Check and list all configured mailboxes"""
import sys
import os
sys.path.insert(0, "/var/www/campaign_platform/backend")
os.chdir("/var/www/campaign_platform/backend")

from database import get_database
db = get_database("email_automation")

print("Current Mailboxes:")
print("-" * 60)
for mb in db.mailboxes.find():
    print(f"  Email: {mb.get('email')}")
    print(f"  Provider: {mb.get('provider')}")
    print(f"  Active: {mb.get('is_active')}")
    print(f"  ID: {mb['_id']}")
    print("-" * 60)

print(f"\nTotal mailboxes: {db.mailboxes.count_documents({})}")
print(f"Active mailboxes: {db.mailboxes.count_documents({'is_active': True})}")
