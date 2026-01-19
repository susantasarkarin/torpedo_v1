#!/usr/bin/env python3
"""Check recent leads"""
from pymongo import MongoClient
from datetime import datetime, timedelta

db = MongoClient()['email_automation']

# Find leads created today
today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
recent = db['leads_raw'].count_documents({'created_at': {'$gte': today}})
print('Leads created today:', recent)

# Show them
print('\nRecent leads:')
for l in db['leads_raw'].find({'created_at': {'$gte': today}}).limit(10):
    print(f"  {l.get('email')} - source: {l.get('source')} - {l.get('created_at')}")

# Check if there are any leads with source containing 'gmail' or 'email'
print('\nLeads by source pattern:')
for pattern in ['gmail', 'email', 'extraction']:
    count = db['leads_raw'].count_documents({'source': {'$regex': pattern, '$options': 'i'}})
    print(f"  source containing '{pattern}': {count}")
