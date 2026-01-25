#!/usr/bin/env python3
from pymongo import MongoClient
db = MongoClient()["torpedo_campaign"]
print("Total jobs:", db.web_search_jobs.count_documents({}))
print("Total leads:", db.leads.count_documents({}))

# Show ALL jobs
print("\nAll web search jobs:")
for j in db.web_search_jobs.find().sort("created_at", -1).limit(5):
    print(f"  {j.get('_id')} - {j.get('status')} - {j.get('designation', 'N/A')[:50]}")

# Check if there are leads
print("\nRecent leads (any source):")
for l in db.leads.find().sort("created_at", -1).limit(5):
    print(f"  {l.get('full_name', 'N/A')} - {l.get('source', 'N/A')}")
