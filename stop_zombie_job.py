#!/usr/bin/env python3
"""Stop zombie job and start new OpenAI web search"""
from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId

db = MongoClient()["email_automation"]

# 1. Stop/remove the zombie job
print("=== STOPPING ZOMBIE JOB ===")
old_job = db.web_search_jobs.find_one({"_id": ObjectId("696bbb7b87549d9a1c9c0e2e")})
if old_job:
    print(f"Found job: {old_job.get('status')} from {old_job.get('created_at')}")
    result = db.web_search_jobs.update_one(
        {"_id": ObjectId("696bbb7b87549d9a1c9c0e2e")},
        {"$set": {"status": "stopped", "stopped_at": datetime.utcnow()}}
    )
    print(f"Stopped: {result.modified_count} job(s)")
else:
    print("Job not found")

# 2. Also stop any other running jobs
result = db.web_search_jobs.update_many(
    {"status": {"$in": ["running", "pending", "paused"]}},
    {"$set": {"status": "stopped", "stopped_at": datetime.utcnow()}}
)
print(f"Stopped {result.modified_count} additional job(s)")

# 3. Verify no running jobs
running = db.web_search_jobs.count_documents({"status": {"$in": ["running", "pending", "paused"]}})
print(f"\nRunning jobs remaining: {running}")

print("\n✅ All jobs stopped. You can now start a new search from the frontend.")
