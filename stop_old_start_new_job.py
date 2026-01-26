#!/usr/bin/env python3
"""Stop old job and start new one with correct schema"""
from pymongo import MongoClient
from datetime import datetime
import uuid

db = MongoClient()["email_automation"]

# Check existing job structure
print("=== CHECKING EXISTING JOB ===")
old_job = db.web_search_jobs.find_one({})
if old_job:
    print("Existing job fields:")
    for k, v in old_job.items():
        if k != "_id":
            print(f"  {k}: {type(v).__name__}")

# 1. Stop the old zombie job
old_job_id = "696bbb7b87549d9a1c9c0e2e"
print(f"\n⏹️  Stopping old job: {old_job_id}")
result = db.web_search_jobs.update_one(
    {"_id": old_job_id},
    {
        "$set": {
            "status": "stopped",
            "stopped_at": datetime.utcnow(),
            "stop_reason": "Zombie job - stale since Jan 17"
        }
    }
)
print(f"   Matched: {result.matched_count}, Modified: {result.modified_count}")

# 2. Create new web search job - use same schema as existing
new_job_id = str(uuid.uuid4()).replace("-", "")[:24]
new_job = {
    "_id": new_job_id,
    "job_id": new_job_id,  # Add job_id field for index
    "status": "running",
    "designation": "Director Consumer Insights, VP Market Research, Head of Insights",
    "countries": [
        "United States", "Canada", "Germany", "United Kingdom",
        "Australia", "France", "India", "Singapore"
    ],
    "seniorities": ["Manager", "Senior", "Director"],
    "created_at": datetime.utcnow(),
    "updated_at": datetime.utcnow(),
    "total_found": 0,
    "total_imported": 0,
    "emails_found": 0,
    "total_duplicates": 0,
    "total_classified": 0,
    "current_query": None,
    "errors": [],
    "daily_limit": 10000,
    "leads_today": 0,
    "progress_percent": 0
}

print(f"\n✅ Starting new job: {new_job_id}")
db.web_search_jobs.insert_one(new_job)
print(f"   Designation: Director Consumer Insights, VP Market Research, Head of Insights")
print(f"   Countries: {len(new_job['countries'])} selected")
print(f"   Seniorities: Manager, Senior, Director")

# Show both jobs
print(f"\n=== JOB STATUS ===")
for job in db.web_search_jobs.find().sort("created_at", -1).limit(2):
    status_icon = "🚀" if job['status'] == 'running' else "⏹️"
    print(f"{status_icon} {job['status'].upper()} | {job.get('designation', 'N/A')[:40]} | {job.get('created_at')}")

print(f"\n✅ New job created and backend will pick it up!")
print(f"   Monitor at: AI Database → Web Search tab")
