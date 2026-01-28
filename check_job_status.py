"""
Check status of a web search job
Usage: python check_job_status.py <job_id>
"""
import sys
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import json

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
jobs_db = client['email_automation']
web_search_jobs = jobs_db['web_search_jobs']

if len(sys.argv) < 2:
    print("Usage: python check_job_status.py <job_id>")
    print("\nOr to see all jobs:")
    print("python check_job_status.py all")
    sys.exit(1)

job_id = sys.argv[1]

print("=" * 70)
print("WEB SEARCH JOB STATUS")
print("=" * 70)
print()

if job_id.lower() == "all":
    # Show all jobs
    jobs = list(web_search_jobs.find().sort('created_at', -1))
    if not jobs:
        print("No jobs found")
    else:
        print(f"Total jobs: {len(jobs)}\n")
        for job in jobs:
            print(f"Job ID: {job['job_id']}")
            print(f"  Status: {job['status']}")
            print(f"  Created: {job.get('created_at', 'N/A')}")
            print(f"  Imported: {job.get('total_imported', 0)}")
            print(f"  Classified: {job.get('total_classified', 0)}")
            print(f"  Emails: {job.get('emails_found', 0)}")
            print(f"  Today: {job.get('leads_today', 0)}")
            if job.get('current_query'):
                print(f"  Current Query: {job['current_query'][:60]}...")
            if job.get('errors'):
                print(f"  Errors: {len(job['errors'])}")
            print()
else:
    # Show specific job
    job = web_search_jobs.find_one({'job_id': job_id})
    
    if not job:
        print(f"Job not found: {job_id}")
        print("\nAvailable jobs:")
        for j in web_search_jobs.find().limit(10):
            print(f"  - {j['job_id']}: {j['status']}")
    else:
        print(f"Job ID: {job['job_id']}")
        print(f"Status: {job['status']}")
        print()
        print("Progress:")
        print(f"  Total Found: {job.get('total_found', 0)}")
        print(f"  Imported: {job.get('total_imported', 0)}")
        print(f"  Duplicates: {job.get('total_duplicates', 0)}")
        print(f"  Classified: {job.get('total_classified', 0)}")
        print(f"  Emails Found: {job.get('emails_found', 0)}")
        print()
        print("Today's Stats:")
        print(f"  Leads Today: {job.get('leads_today', 0)}")
        print(f"  Day Started: {job.get('day_started', 'N/A')}")
        print()
        print("Timing:")
        print(f"  Created: {job.get('created_at', 'N/A')}")
        print(f"  Started: {job.get('started_at', 'N/A')}")
        print(f"  Last Update: {job.get('last_update', 'N/A')}")
        
        # Calculate runtime
        if job.get('started_at'):
            started = job['started_at']
            last_update = job.get('last_update', datetime.utcnow())
            if isinstance(started, str):
                from dateutil import parser
                started = parser.parse(started)
            if isinstance(last_update, str):
                last_update = parser.parse(last_update)
            runtime = last_update - started
            print(f"  Runtime: {runtime}")
        
        print()
        print("Configuration:")
        config = job.get('config', {})
        print(f"  Designations: {config.get('designations', [])}")
        print(f"  Countries: {config.get('countries', [])}")
        print(f"  Seniorities: {config.get('seniorities', [])}")
        if config.get('custom_query'):
            print(f"  Custom Query: {config['custom_query']}")
        
        print()
        print(f"Query Combinations: {len(job.get('query_combinations', []))}")
        if job.get('current_query'):
            print(f"Current Query: {job['current_query']}")
        
        print()
        print(f"Seen URLs: {len(job.get('seen_urls', []))}")
        
        if job.get('errors'):
            print()
            print(f"Errors ({len(job['errors'])}):")
            for i, err in enumerate(job['errors'][-5:], 1):
                print(f"  {i}. {err}")

print()
print("=" * 70)
