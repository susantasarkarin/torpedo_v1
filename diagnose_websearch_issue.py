#!/usr/bin/env python3
"""
Diagnose OpenAI Web Search Issues
"""
from pymongo import MongoClient
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
import json

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

print("=" * 70)
print("OPENAI WEB SEARCH DIAGNOSTIC REPORT")
print("=" * 70)
print()

# 1. Check the stuck job in detail
print("1. STUCK JOB DETAILS:")
print("-" * 70)
try:
    db = client['email_automation']
    jobs = db['web_search_jobs']
    
    job = jobs.find_one({'job_id': 'f59518ed'})
    if job:
        print("Job found!")
        print(f"  Job ID: {job.get('job_id')}")
        print(f"  Status: {job.get('status')}")
        print(f"  Created: {job.get('created_at')}")
        print(f"  Updated: {job.get('updated_at')}")
        print(f"  Processed: {job.get('processed', 0)}")
        print(f"  Total: {job.get('total', 0)}")
        print(f"  Queries: {job.get('queries', [])}")
        print(f"  Leads found: {job.get('leads_found', 0)}")
        print(f"  Errors: {job.get('errors', [])}")
        print(f"  Paused: {job.get('paused', False)}")
        
        # Check if there are search queries
        queries = job.get('queries', [])
        if not queries:
            print("\n  ⚠️ WARNING: No search queries defined!")
        else:
            print(f"\n  Search queries ({len(queries)}):")
            for i, q in enumerate(queries[:5], 1):
                print(f"    {i}. {q}")
                
        # Check job age
        created = job.get('created_at')
        if created:
            age = datetime.now(timezone.utc) - created
            print(f"\n  Job age: {age.days} days, {age.seconds // 3600} hours")
            if age.days > 7:
                print("  ⚠️ WARNING: Job is very old (>7 days)")
    else:
        print("Job not found!")
        
        # List all jobs
        all_jobs = list(jobs.find().sort('created_at', -1).limit(5))
        print(f"\nAll jobs in system: {jobs.count_documents({})}")
        if all_jobs:
            print("\nRecent jobs:")
            for j in all_jobs:
                print(f"  • {j.get('job_id')} - {j.get('status')} - {j.get('created_at')}")
        
except Exception as e:
    print(f"Error: {e}")

# 2. Check if OpenAI API key is configured
print("\n2. OPENAI API CONFIGURATION:")
print("-" * 70)
openai_key = os.getenv('OPENAI_API_KEY', '')
if openai_key:
    print(f"  ✓ OPENAI_API_KEY is set (length: {len(openai_key)})")
    print(f"    Starts with: {openai_key[:7]}...")
else:
    print("  ✗ OPENAI_API_KEY is NOT set")

# 3. Check backend logs or error tracking
print("\n3. RECENT ERRORS/LOGS:")
print("-" * 70)
try:
    # Check for error logs in database
    error_logs = db.get_collection('error_logs')
    if 'error_logs' in db.list_collection_names():
        recent_errors = list(error_logs.find({'error': {'$regex': 'openai|web.?search', '$options': 'i'}}).sort('timestamp', -1).limit(5))
        if recent_errors:
            print("Recent errors related to OpenAI/web search:")
            for err in recent_errors:
                print(f"  • {err.get('timestamp')}: {err.get('error', 'N/A')[:100]}")
        else:
            print("  No recent errors found")
    else:
        print("  No error_logs collection")
except Exception as e:
    print(f"  Could not check errors: {e}")

# 4. Check search control settings
print("\n4. SEARCH CONTROL SETTINGS:")
print("-" * 70)
try:
    settings_db = client['torpedo_settings']
    control = settings_db['app_settings'].find_one({'_id': 'search_control'})
    
    if control:
        for key in ['paused', 'circuit_breaker_open', 'consecutive_errors', 
                    'auto_resume_disabled', 'paused_reason', 'last_error',
                    'daily_limit', 'daily_count', 'last_reset']:
            val = control.get(key)
            if val:
                print(f"  {key}: {val}")
    else:
        print("  No search control settings")
except Exception as e:
    print(f"  Error: {e}")

# 5. Check if backend is running
print("\n5. BACKEND SERVICE CHECK:")
print("-" * 70)
try:
    # Check for recent activity in leads
    recent_activity = db['leads_raw'].find_one({}, sort=[('created_at', -1)])
    if recent_activity:
        latest = recent_activity.get('created_at')
        if latest:
            age = datetime.now(timezone.utc) - latest
            print(f"  Most recent lead activity: {latest}")
            print(f"  Age: {age.days} days, {age.seconds // 3600} hours ago")
            
            if age.days > 1:
                print("  ⚠️ WARNING: No recent lead activity (>24h)")
                print("     Backend may not be running or processing")
except Exception as e:
    print(f"  Error: {e}")

# 6. Check web search function availability
print("\n6. BACKEND IMPLEMENTATION CHECK:")
print("-" * 70)
print("  Checking if web search routes exist...")

import sys
sys.path.insert(0, 'backend')

try:
    # Try to import the web search modules
    from background_job_scheduler import run_web_search_job, get_incomplete_jobs
    print("  ✓ Web search functions can be imported")
    
    # Check for incomplete jobs
    incomplete = get_incomplete_jobs()
    print(f"  Incomplete jobs: {len(incomplete)}")
    
except ImportError as e:
    print(f"  ✗ Cannot import web search functions: {e}")
except Exception as e:
    print(f"  Error checking implementation: {e}")

print("\n" + "=" * 70)
print("DIAGNOSIS SUMMARY:")
print("=" * 70)

issues = []

# Analyze issues
if job and not job.get('queries'):
    issues.append("Job has no search queries defined")
    
if job and job.get('created_at'):
    age = datetime.now(timezone.utc) - job.get('created_at')
    if age.days > 7:
        issues.append(f"Job is {age.days} days old and stuck")

if not openai_key:
    issues.append("OpenAI API key not configured")

if issues:
    print("\n⚠️ ISSUES FOUND:")
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")
    
    print("\n💡 RECOMMENDATIONS:")
    if "no search queries" in str(issues).lower():
        print("  • Delete the stuck job and create a new one with proper queries")
    if "days old" in str(issues).lower():
        print("  • Remove the old job: db.web_search_jobs.delete_one({'job_id': 'f59518ed'})")
    if "api key" in str(issues).lower():
        print("  • Configure OPENAI_API_KEY in .env file")
else:
    print("\n✓ No obvious configuration issues found")
    print("\n💡 Next steps:")
    print("  • Check backend logs for runtime errors")
    print("  • Verify the backend service is running")
    print("  • Test OpenAI API connection manually")

print("\n" + "=" * 70)
