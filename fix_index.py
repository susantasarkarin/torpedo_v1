#!/usr/bin/env python3
"""Fix the linkedin_url unique index issue"""
from pymongo import MongoClient, ASCENDING

db = MongoClient()['email_automation']

# Drop the problematic unique index
try:
    db['leads_raw'].drop_index('linkedin_url_1')
    print('Dropped linkedin_url_1 index')
except Exception as e:
    print(f'Error dropping index: {e}')

# Recreate as sparse index (only indexes documents that have the field)
try:
    db['leads_raw'].create_index('linkedin_url', unique=True, sparse=True)
    print('Created sparse unique index on linkedin_url')
except Exception as e:
    print(f'Error creating sparse index: {e}')

# List current indexes
print('\nCurrent indexes:')
for idx in db['leads_raw'].list_indexes():
    print(f"  {idx['name']}: {idx.get('key')} unique={idx.get('unique', False)} sparse={idx.get('sparse', False)}")
