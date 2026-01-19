#!/usr/bin/env python3
"""Check email accounts and emails in MongoDB"""

from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')

# Check torpedo_gmail database (Gmail OAuth)
torpedo_db = client['torpedo_gmail']
print('=== torpedo_gmail database ===')
print('mailboxes:', torpedo_db['mailboxes'].count_documents({}))
print('email_metadata:', torpedo_db['email_metadata'].count_documents({}))

# Check email_automation database
email_db = client['email_automation']
print('\n=== email_automation database ===')
print('imap_accounts:', email_db['imap_accounts'].count_documents({}))
print('emails:', email_db['emails'].count_documents({}))

# List all collections with counts
print('\nAll collections in email_automation:')
for c in sorted(email_db.list_collection_names()):
    count = email_db[c].count_documents({})
    if count > 0:
        print(f'  {c}: {count}')

# Check if there's a emails collection with contact data
if email_db['emails'].count_documents({}) > 0:
    sample = email_db['emails'].find_one()
    print('\nSample email structure:')
    print(list(sample.keys())[:10])
