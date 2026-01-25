#!/usr/bin/env python3
from pymongo import MongoClient
db = MongoClient()["email_automation"]
print("Database: email_automation")
print("Jobs:", db.web_search_jobs.count_documents({}))
print("Leads raw:", db.leads_raw.count_documents({}))
print("Leads:", db.leads.count_documents({}))
print("\nCollections:", db.list_collection_names())

# Show ALL jobs
print("\n=== ACTIVE WEB SEARCH JOBS ===")
for j in db.web_search_jobs.find({"status": {"$in": ["running", "pending", "paused"]}}).sort("created_at", -1).limit(5):
    print(f"  ID: {j.get('_id')}")
    print(f"  Status: {j.get('status')}")
    print(f"  Designation: {j.get('designation', 'N/A')}")
    print(f"  Countries: {j.get('countries', [])}")
    print(f"  Seniorities: {j.get('seniorities', [])}")
    print(f"  Found: {j.get('total_found', 0)}")
    print(f"  Imported: {j.get('total_imported', 0)}")
    print(f"  Created: {j.get('created_at')}")
    print("---")

# Show recent jobs (any status)
print("\n=== ALL JOBS (recent) ===")
for j in db.web_search_jobs.find().sort("created_at", -1).limit(5):
    print(f"  {j.get('status')} | {j.get('designation', 'N/A')[:40]} | Created: {j.get('created_at')}")

# Check leads
print("\n=== RECENT LEADS ===")
for l in db.leads_raw.find().sort("created_at", -1).limit(10):
    print(f"  {l.get('full_name', 'N/A')} | {l.get('title', 'N/A')[:30] if l.get('title') else 'N/A'} | Source: {l.get('source', 'N/A')}")

# Count by source
print("\n=== LEADS BY SOURCE ===")
for r in db.leads_raw.aggregate([{"$group": {"_id": "$source", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]):
    print(f"  {r['_id']}: {r['count']}")
