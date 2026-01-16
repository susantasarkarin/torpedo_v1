#!/usr/bin/env python3
"""Check email count and sync status"""
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['torpedo_gmail']

print("Email count:", db.email_metadata.count_documents({}))
mailbox = db.workspace_mailboxes.find_one()
if mailbox:
    print("Last sync:", mailbox.get('last_sync_at'))
    print("Email count in mailbox:", mailbox.get('email_count'))
