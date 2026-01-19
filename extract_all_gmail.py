#!/usr/bin/env python3
"""Extract leads from all Gmail accounts"""
import requests

# Extract from all three mailboxes with high limit
response = requests.post(
    'http://localhost:8000/leads/emails/extract',
    json={
        'account_emails': None,  # All accounts
        'max_emails': 5000
    }
)

print(f"Status: {response.status_code}")
result = response.json()
print(f"Emails processed: {result.get('emails_processed', 0)}")
print(f"Leads extracted: {result.get('leads_extracted', 0)}")
print(f"Leads enriched: {result.get('leads_enriched', 0)}")
print(f"Duplicates: {result.get('duplicates', 0)}")

# Now check count
from pymongo import MongoClient
db = MongoClient()['email_automation']
gmail_count = db['leads_raw'].count_documents({'source': 'gmail'})
print(f"\nTotal Gmail leads in DB: {gmail_count}")
