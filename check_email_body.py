#!/usr/bin/env python3
"""Check if emails have body_plain field"""
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['torpedo_gmail']

# Check email_metadata collection
count = db.email_metadata.count_documents({})
print('email_metadata count:', count)

sample = db.email_metadata.find_one()
if sample:
    print('Keys:', list(sample.keys()))
    print('Has body_plain:', 'body_plain' in sample)
    if 'body_plain' in sample and sample['body_plain']:
        print('Body preview:', sample['body_plain'][:200])
    else:
        print('No body_plain field - need to re-sync')
else:
    print('No emails found')
