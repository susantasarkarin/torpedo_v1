#!/usr/bin/env python3
from pymongo import MongoClient
db = MongoClient()["campaign_platform"]
print("Database: campaign_platform")
print("Jobs:", db.web_search_jobs.count_documents({}))
print("Leads:", db.leads.count_documents({}))
print("\nCollections:", db.list_collection_names())

# Show ALL jobs
print("\nAll web search jobs:")
for j in db.web_search_jobs.find().sort("created_at", -1).limit(5):
    print(f"  ID: {j.get('_id')}")
    print(f"  Status: {j.get('status')}")
    print(f"  Designation: {j.get('designation', 'N/A')}")
    print(f"  Countries: {j.get('countries', [])}")
    print(f"  Seniorities: {j.get('seniorities', [])}")
    print(f"  Found: {j.get('total_found', 0)}")
    print(f"  Imported: {j.get('total_imported', 0)}")
    print(f"  Created: {j.get('created_at')}")
    print("---")

# Check if there are leads
print("\nRecent leads (any source):")
for l in db.leads.find().sort("created_at", -1).limit(10):
    print(f"  {l.get('full_name', 'N/A')} | {l.get('title', 'N/A')[:30]} | {l.get('company_name', 'N/A')[:20]} | Source: {l.get('source', 'N/A')}")
