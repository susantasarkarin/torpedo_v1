#!/usr/bin/env python3
"""Detailed check for CINT and Gmail sync status"""
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone

c = MongoClient('mongodb://localhost:27017/')

# Check torpedo_gmail for recent sync activity
print('=== TORPEDO GMAIL SYNC LOGS (Last 5) ===')
db = c['torpedo_gmail']
logs = list(db['email_sync_log'].find().sort('timestamp', -1).limit(5))
for log in logs:
    ts = log.get('timestamp', 'N/A')
    status = log.get('status', 'N/A')
    msg = log.get('message', log.get('account', 'N/A'))
    print(f"  {ts}: {status} - {msg}")

# Check accounts
print('\n=== GMAIL ACCOUNTS ===')
for acc in db['accounts'].find():
    print(f"  Email: {acc.get('email', 'N/A')}")
    print(f"  Last Sync: {acc.get('last_sync', acc.get('lastSync', 'Never'))}")
    print(f"  Status: {acc.get('status', acc.get('sync_status', 'Unknown'))}")

# Check cint_research collections
print('\n=== CINT RESEARCH DATABASE ===')
db = c['cint_research']
for coll_name in db.list_collection_names():
    count = db[coll_name].count_documents({})
    print(f'  {coll_name}: {count} docs')
    if count > 0 and count < 20:
        sample = db[coll_name].find_one()
        keys = list(sample.keys())[:8]
        print(f'    Keys: {keys}')

# Check gmail_archive
print('\n=== GMAIL ARCHIVE ===')
db = c['gmail_archive']
count = db['emails'].count_documents({})
print(f'  emails: {count} docs')
sample = db['emails'].find_one(sort=[('date', -1)])
if sample:
    print(f"  Latest email date: {sample.get('date', sample.get('internal_date', 'N/A'))}")
    keys = list(sample.keys())[:10]
    print(f'  Keys: {keys}')

# Check email_automation emails
print('\n=== EMAIL AUTOMATION DATABASE ===')
db = c['email_automation']
for coll in ['emails', 'email_metadata', 'unified_inbox']:
    if coll in db.list_collection_names():
        count = db[coll].count_documents({})
        print(f'  {coll}: {count} docs')
        if count > 0:
            sample = db[coll].find_one(sort=[('created_at', -1)])
            if sample:
                for field in ['created_at', 'synced_at', 'received_at', 'date']:
                    if sample.get(field):
                        print(f'    Latest {field}: {sample.get(field)}')
                        break

# Check CPX survey inventory
print('\n=== CPX RESEARCH DATABASE ===')
db = c['cpx_research']
count = db['cpx_surveys'].count_documents({})
print(f'  cpx_surveys: {count} docs')
if count > 0:
    sample = db['cpx_surveys'].find_one(sort=[('last_updated', -1)])
    if sample:
        print(f"  Latest update: {sample.get('last_updated', 'N/A')}")
        print(f"  Sample survey: {sample.get('category', 'N/A')} - Country: {sample.get('country', 'N/A')}")

print('\n=== DONE ===')
