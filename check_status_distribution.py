#!/usr/bin/env python3
"""Check classification status distribution"""

from pymongo import MongoClient
client = MongoClient('mongodb://localhost:27017/')
db = client['email_automation']

# Check classification_status field values
print('=== CLASSIFICATION STATUS DISTRIBUTION ===')
statuses = db['leads_raw'].aggregate([
    {'$group': {'_id': '$classification_status', 'count': {'$sum': 1}}}
])
for s in statuses:
    status_val = s['_id'] if s['_id'] else 'null/missing'
    print(f'  {status_val}: {s["count"]}')

# Check leads without classification_status
no_status = db['leads_raw'].count_documents({'classification_status': {'$exists': False}})
null_status = db['leads_raw'].count_documents({'classification_status': None})
print(f'\nNo classification_status field: {no_status}')
print(f'classification_status = null: {null_status}')

# Sample a few records to see their structure
print('\n=== SAMPLE RECORDS ===')
samples = list(db['leads_raw'].find().limit(2))
for s in samples:
    print(f"ID: {s.get('_id')}")
    print(f"  Source: {s.get('source')}")
    print(f"  Status: {s.get('classification_status', 'MISSING')}")
    print(f"  Email: {s.get('email', 'N/A')[:50] if s.get('email') else 'N/A'}")
    print()
