#!/usr/bin/env python3
"""Check email data in database"""

from pymongo import MongoClient
client = MongoClient('mongodb://localhost:27017/')
db = client['email_automation']

# Check emails collection
emails_count = db['emails'].count_documents({})
print(f'Emails in database: {emails_count}')

# Sample emails
if emails_count > 0:
    print('\nSample emails:')
    samples = list(db['emails'].find().limit(3))
    for s in samples:
        print(f"  From: {s.get('from_email', s.get('sender', 'N/A'))}")
        print(f"  Subject: {s.get('subject', 'N/A')[:50]}")
        print()

# Check imap_accounts collection
imap_accounts = list(db['imap_accounts'].find({}, {'email': 1, 'is_active': 1}))
print(f'IMAP accounts: {len(imap_accounts)}')
for acc in imap_accounts:
    print(f"  - {acc.get('email')} (active: {acc.get('is_active')})")

# Check gmail_accounts collection
gmail_accounts = list(db['gmail_accounts'].find({}, {'email': 1, 'is_active': 1}))
print(f'Gmail OAuth accounts: {len(gmail_accounts)}')
for acc in gmail_accounts:
    print(f"  - {acc.get('email')} (active: {acc.get('is_active')})")

# Check unique senders in emails
if emails_count > 0:
    print('\nUnique sender domains (top 10):')
    pipeline = [
        {"$group": {"_id": "$from_email", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]
    try:
        senders = list(db['emails'].aggregate(pipeline))
        for s in senders:
            print(f"  {s['_id']}: {s['count']}")
    except:
        pass
