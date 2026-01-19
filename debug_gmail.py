#!/usr/bin/env python3
"""Check why Gmail leads aren't being saved"""
from pymongo import MongoClient

db = MongoClient()['email_automation']

# Check total leads with email
print('Total leads with email:', db['leads_raw'].count_documents({'email': {'$exists': True, '$ne': None}}))

# Check gmail leads
gmail_leads = db['leads_raw'].count_documents({'source': 'gmail'})
print(f'Gmail leads: {gmail_leads}')

# Let's look at recent gmail leads
print('\n=== Recent Gmail Leads ===')
for lead in db['leads_raw'].find({'source': 'gmail'}).sort('created_at', -1).limit(10):
    print(f"  {lead.get('email')} - {lead.get('name')} - {lead.get('created_at')}")

# Also check torpedo_gmail for inbound emails
torpedo_db = MongoClient()['torpedo_gmail']
inbound_count = torpedo_db['email_metadata'].count_documents({'direction': 'inbound'})
print(f'\nTotal inbound emails in torpedo_gmail: {inbound_count}')

# Sample inbound email
sample = torpedo_db['email_metadata'].find_one({'direction': 'inbound'})
if sample:
    print(f"\nSample inbound email:")
    print(f"  from_email: {sample.get('from_email')}")
    print(f"  from_name: {sample.get('from_name')}")
    print(f"  mailbox_id: {sample.get('mailbox_id')}")
