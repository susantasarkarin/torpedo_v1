#!/usr/bin/env python3
"""Check active web search jobs on VM"""
from pymongo import MongoClient

db = MongoClient()["torpedo_campaign"]

# Check active web search jobs
print("\n" + "="*50)
print("ACTIVE WEB SEARCH JOBS")
print("="*50)

jobs = list(db.web_search_jobs.find({
    "status": {"$in": ["running", "pending", "paused"]}
}).sort("created_at", -1).limit(5))

if not jobs:
    print("No active jobs found")
else:
    for j in jobs:
        print(f"\nJob ID: {j.get('_id')}")
        print(f"Status: {j.get('status')}")
        print(f"Designation: {j.get('designation')}")
        print(f"Countries: {j.get('countries')}")
        print(f"Seniorities: {j.get('seniorities')}")
        print(f"Total Found: {j.get('total_found', 0)}")
        print(f"Total Imported: {j.get('total_imported', 0)}")
        print(f"Emails Found: {j.get('emails_found', 0)}")
        print(f"Created: {j.get('created_at')}")
        print(f"Current Query: {j.get('current_query', 'N/A')}")
        print("-" * 40)

# Check recent leads from web search
print("\n" + "="*50)
print("RECENT LEADS FROM WEB SEARCH (Last 10)")
print("="*50)

leads = list(db.leads.find({
    "source": {"$in": ["openai_search", "web_search", "google_search"]}
}).sort("created_at", -1).limit(10))

if not leads:
    print("No web search leads found")
else:
    for l in leads:
        print(f"\n{l.get('full_name', 'N/A')}")
        print(f"  Title: {l.get('title', 'N/A')}")
        print(f"  Company: {l.get('company_name', 'N/A')}")
        print(f"  Source: {l.get('source', 'N/A')}")
        print(f"  Email: {l.get('email', 'N/A')}")
        print(f"  Created: {l.get('created_at', 'N/A')}")

# Count leads by source
print("\n" + "="*50)
print("LEADS COUNT BY SOURCE")
print("="*50)
pipeline = [
    {"$group": {"_id": "$source", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}}
]
for r in db.leads.aggregate(pipeline):
    print(f"  {r['_id']}: {r['count']}")
