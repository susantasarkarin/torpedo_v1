#!/usr/bin/env python3
"""Quick script to check Gmail lead data status"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017/'))
db = client['email_automation']

GMAIL_SOURCES = ['gmail', 'gmail_workspace', 'email_sync', 'email_import', 'email_classification', 'gmail_api', 'gmail_archive']

# Check Gmail leads
print("=" * 60)
print("GMAIL LEADS STATUS CHECK")
print("=" * 60)

total_raw = db.leads_raw.count_documents({'source': {'$in': GMAIL_SOURCES}})
total_enriched = db.leads_enriched.count_documents({'source': {'$in': GMAIL_SOURCES}})

print(f"\nTotal Gmail leads in leads_raw: {total_raw}")
print(f"Gmail leads in leads_enriched: {total_enriched}")

# Check for leads with missing fields
missing_fields = db.leads_raw.count_documents({
    'source': {'$in': GMAIL_SOURCES},
    '$or': [
        {'seniority_level': {'$exists': False}},
        {'seniority_level': None},
        {'seniority_level': ''}
    ]
})
print(f"\nGmail leads missing seniority_level: {missing_fields}")

# Show sample lead
gmail_leads = list(db.leads_raw.find({'source': {'$in': GMAIL_SOURCES}}).limit(3))
if gmail_leads:
    print("\n" + "-" * 60)
    print("Sample Gmail leads:")
    for i, lead in enumerate(gmail_leads, 1):
        print(f"\n[Lead {i}]")
        for key in ['email', 'name', 'source', 'classification', 'classification_status', 
                    'seniority_level', 'department', 'persona', 'company', 'company_name', 'title']:
            val = lead.get(key)
            if val:
                print(f"  {key}: {val}")
            else:
                print(f"  {key}: (empty)")
else:
    print("\nNo Gmail leads found in leads_raw")

# Check leads_enriched
enriched_leads = list(db.leads_enriched.find({'source': {'$in': GMAIL_SOURCES}}).limit(3))
if enriched_leads:
    print("\n" + "-" * 60)
    print("Sample Gmail leads in leads_enriched:")
    for i, lead in enumerate(enriched_leads, 1):
        print(f"\n[Enriched Lead {i}]")
        for key in ['email', 'name', 'source', 'seniority_level', 'department', 'persona', 
                    'company_name', 'title', 'confidence_score']:
            val = lead.get(key)
            if val:
                print(f"  {key}: {val}")
            else:
                print(f"  {key}: (empty)")
else:
    print("\nNo Gmail leads found in leads_enriched")
