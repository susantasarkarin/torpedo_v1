"""
Stop a web search job
Usage: python stop_job.py <job_id> or python stop_job.py all
"""
import sys
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
jobs_db = client['email_automation']
web_search_jobs = jobs_db['web_search_jobs']

if len(sys.argv) < 2:
    print("Usage: python stop_job.py <job_id>")
    print("   Or: python stop_job.py all    (stops all running jobs)")
    sys.exit(1)

job_id = sys.argv[1]

print("=" * 70)
print("STOP WEB SEARCH JOB")
print("=" * 70)
print()

if job_id.lower() == "all":
    # Stop all running/pending jobs
    result = web_search_jobs.update_many(
        {'status': {'$in': ['running', 'pending', 'paused', 'quota_exceeded']}},
        {'$set': {'status': 'stopped', 'last_update': datetime.utcnow()}}
    )
    print(f"✓ Stopped {result.modified_count} jobs")
else:
    # Stop specific job
    job = web_search_jobs.find_one({'job_id': job_id})
    
    if not job:
        print(f"❌ Job not found: {job_id}")
        print("\nAvailable jobs:")
        for j in web_search_jobs.find().limit(10):
            print(f"  - {j['job_id']}: {j['status']}")
    else:
        if job['status'] in ['stopped', 'completed', 'failed']:
            print(f"ℹ Job is already {job['status']}")
        else:
            web_search_jobs.update_one(
                {'job_id': job_id},
                {'$set': {'status': 'stopped', 'last_update': datetime.utcnow()}}
            )
            print(f"✓ Job {job_id} stopped")
            print(f"  Previous status: {job['status']}")
            print(f"  Leads imported: {job.get('total_imported', 0)}")
            print(f"  Leads classified: {job.get('total_classified', 0)}")

print()
print("=" * 70)
