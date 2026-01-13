#!/usr/bin/env python3
"""Sync Gmail mailboxes"""
import sys
import os

sys.path.insert(0, "/var/www/campaign_platform/backend")
os.chdir("/var/www/campaign_platform/backend")

from app.services.gmail_workspace_service import GmailWorkspaceService

MONGO_URI = "mongodb://susanta:StrongPassDogfish!@127.0.0.1:27017/admin"

service = GmailWorkspaceService(mongo_uri=MONGO_URI)
service.load_service_account()

mailboxes = service.list_mailboxes()
print(f"Found {len(mailboxes)} mailboxes")

for mb in mailboxes:
    print(f"Syncing: {mb['email']}")
    try:
        result = service.sync_mailbox(mb["id"], max_results=1000000, full_sync=True)
        print(f"  Result: {result}")
    except Exception as e:
        print(f"  Error: {e}")
