#!/usr/bin/env python3
"""Force re-sync to download email bodies"""
import os
import sys
sys.path.insert(0, '/var/www/campaign_platform/backend')

from pymongo import MongoClient
from bson import ObjectId

client = MongoClient('mongodb://localhost:27017/')
db = client['torpedo_gmail']

# Get the mailbox
mailbox_id = ObjectId('696a4b0d3bac0fd584c6c72f')
mailbox = db.workspace_mailboxes.find_one({'_id': mailbox_id})
print(f'Mailbox: {mailbox.get("email")}')
print(f'Current history_id: {mailbox.get("last_history_id")}')

# Clear history to force full sync
result = db.workspace_mailboxes.update_one(
    {'_id': mailbox_id},
    {'$unset': {'last_history_id': ''}}
)
print(f'Cleared history ID: {result.modified_count}')

print('Now trigger sync: curl -X POST http://localhost:8000/gmail-ws/mailboxes/696a4b0d3bac0fd584c6c72f/sync')
