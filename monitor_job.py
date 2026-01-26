#!/usr/bin/env python3
import time
from pymongo import MongoClient
from bson.objectid import ObjectId

db = MongoClient()["email_automation"]
job_id = "6976502fb57c65b9b487d166"

print("Monitoring job:", job_id)
print("-" * 60)

for i in range(30):  # Check for 30 seconds
    job = db.web_search_jobs.find_one({"_id": ObjectId(job_id)})
    
    if job:
        print(f"\r[{i+1}s] Status: {job.get('status', 'N/A'):10} | Found: {job.get('total_found', 0):4} | Imported: {job.get('total_imported', 0):4} | Query: {job.get('current_query', 'N/A')[:40]:40}", end='', flush=True)
        
        if job.get('status') == 'running':
            if i >= 10:  # Give it 10 seconds to start
                print(f"\n✅ Job is running! Query: {job.get('current_query', 'N/A')}")
                break
    else:
        print(f"\r[{i+1}s] Job not found", end='', flush=True)
    
    time.sleep(1)

print("\n\nFinal status:")
job = db.web_search_jobs.find_one({"_id": ObjectId(job_id)})
if job:
    print(f"  Status: {job.get('status')}")
    print(f"  Total Found: {job.get('total_found', 0)}")
    print(f"  Total Imported: {job.get('total_imported', 0)}")
    print(f"  Current Query: {job.get('current_query', 'N/A')}")
    print(f"  Errors: {len(job.get('errors', []))}")
