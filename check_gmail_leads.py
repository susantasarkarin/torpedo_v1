#!/usr/bin/env python3
"""Check Gmail leads in database"""
from pymongo import MongoClient

db = MongoClient()['email_automation']

# Check leads by source
print('=== Leads by Source ===')
pipeline = [{'$group': {'_id': '$source', 'count': {'$sum': 1}}}]
for r in db['leads_raw'].aggregate(pipeline):
    print(f"  {r['_id']}: {r['count']}")

# Check gmail specifically
gmail_count = db['leads_raw'].count_documents({'source': 'gmail'})
print(f'\nGmail leads: {gmail_count}')

# Check if there are any with source_detail
gmail_detail = db['leads_raw'].count_documents({'source_detail': 'email_extraction'})
print(f'Email extraction leads: {gmail_detail}')

# Show sample gmail lead if exists
if gmail_count > 0:
    sample = db['leads_raw'].find_one({'source': 'gmail'})
    print('\nSample Gmail lead:')
    for k, v in sample.items():
        if k != '_id':
            print(f'  {k}: {v}')
