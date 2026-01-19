#!/usr/bin/env python3
"""Check email metadata structure"""
from pymongo import MongoClient

db = MongoClient()['torpedo_gmail']
sample = db['email_metadata'].find_one()

print('Keys:', list(sample.keys()))
print('From:', sample.get('from_email'))
print('To:', sample.get('to_emails'))
print('Subject:', sample.get('subject')[:80] if sample.get('subject') else None)
print('From Name:', sample.get('from_name'))
print('Mailbox ID:', sample.get('mailbox_id'))

# Get unique mailbox_ids
print('\n=== Unique Mailbox IDs ===')
mailbox_ids = db['email_metadata'].distinct('mailbox_id')
print('Mailbox IDs:', mailbox_ids[:5])

# Count emails per mailbox
print('\n=== Emails per mailbox ===')
for mbid in mailbox_ids[:5]:
    count = db['email_metadata'].count_documents({'mailbox_id': mbid})
    print(f'  {mbid}: {count}')
