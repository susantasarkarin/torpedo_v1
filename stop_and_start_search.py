#!/usr/bin/env python3
"""Stop zombie job and start new search with market research criteria"""
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime

db = MongoClient()["email_automation"]

# 1. Stop the zombie job
print("="*60)
print("STOPPING OLD JOB")
print("="*60)

old_job_id = "696bbb7b87549d9a1c9c0e2e"
result = db.web_search_jobs.update_one(
    {"_id": ObjectId(old_job_id)},
    {"$set": {"status": "stopped", "updated_at": datetime.utcnow()}}
)

if result.modified_count > 0:
    print(f"✅ Stopped job: {old_job_id}")
else:
    print(f"⚠️ Job not found or already stopped: {old_job_id}")

# 2. Create new search job with market research criteria
print("\n" + "="*60)
print("STARTING NEW SEARCH")
print("="*60)

new_job = {
    "status": "pending",
    "designation": "Director Consumer Insights, VP Market Research, Head of Insights",
    "countries": [
        "United States",
        "Canada", 
        "Germany",
        "United Kingdom",
        "Australia",
        "France",
        "India",
        "Singapore"
    ],
    "seniorities": ["Manager"],
    "total_found": 0,
    "total_imported": 0,
    "total_duplicates": 0,
    "total_classified": 0,
    "emails_found": 0,
    "progress_percent": 0,
    "current_query": "",
    "leads_today": 0,
    "daily_limit": 10000,
    "errors": [],
    "created_at": datetime.utcnow(),
    "updated_at": datetime.utcnow()
}

result = db.web_search_jobs.insert_one(new_job)
new_job_id = str(result.inserted_id)

print(f"✅ Created new job: {new_job_id}")
print(f"   Designation: {new_job['designation']}")
print(f"   Countries: {len(new_job['countries'])} selected")
print(f"   Seniorities: {new_job['seniorities']}")
print(f"   Status: {new_job['status']}")

print("\n" + "="*60)
print("NEXT STEPS")
print("="*60)
print("The backend needs to pick up this job and start the search.")
print("The job will automatically start processing on the next poll cycle.")
print(f"\nJob ID: {new_job_id}")
