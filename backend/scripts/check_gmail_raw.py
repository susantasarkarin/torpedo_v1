#!/usr/bin/env python3
"""Check Gmail leads in raw vs enriched"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
from pymongo import MongoClient
load_dotenv()

client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017/'))
db = client['email_automation']

# Check raw gmail leads with missing fields
missing = db.leads_raw.count_documents({
    'source': 'gmail',
    '$or': [
        {'seniority_level': {'$exists': False}},
        {'seniority_level': None},
        {'seniority_level': ''}
    ]
})
print(f"Gmail leads_raw missing seniority: {missing}")

# Sample raw gmail lead
sample = db.leads_raw.find_one({'source': 'gmail'})
if sample:
    print("\nSample gmail lead from leads_raw:")
    for k in ['email', 'name', 'source', 'classification_status', 'seniority_level', 'department', 'persona', 'title', 'company']:
        print(f"  {k}: {sample.get(k)}")

# Check leads without enriched_lead_id
no_enriched = db.leads_raw.count_documents({
    'source': 'gmail',
    '$or': [
        {'enriched_lead_id': {'$exists': False}},
        {'enriched_lead_id': None}
    ]
})
print(f"\nGmail leads_raw without enriched_lead_id: {no_enriched}")
