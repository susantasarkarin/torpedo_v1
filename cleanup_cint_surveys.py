#!/usr/bin/env python3
"""
Clean up all CINT surveys and entry links.
After running this, the webhook subscription will repopulate with fresh data.
"""
from pymongo import MongoClient
from datetime import datetime

c = MongoClient()
db = c.cint_research

# Count before
surveys_before = db.cint_surveys.count_documents({})
entry_links_before = db.cint_entry_links.count_documents({})

print(f"Before cleanup:")
print(f"  cint_surveys: {surveys_before}")
print(f"  cint_entry_links: {entry_links_before}")

# Delete all surveys
result1 = db.cint_surveys.delete_many({})
print(f"\nDeleted {result1.deleted_count} surveys")

# Delete all entry links
result2 = db.cint_entry_links.delete_many({})
print(f"Deleted {result2.deleted_count} entry links")

# Verify
print(f"\nAfter cleanup:")
print(f"  cint_surveys: {db.cint_surveys.count_documents({})}")
print(f"  cint_entry_links: {db.cint_entry_links.count_documents({})}")

print(f"\nCleanup completed at {datetime.utcnow().isoformat()}")
print("The webhook subscription will repopulate surveys automatically.")
