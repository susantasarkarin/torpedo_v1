#!/usr/bin/env python3
"""
Fix OpenAI Web Search Issues
==============================
1. Remove the stuck old job
2. Configure OpenAI API key
3. Create a fresh working job
"""
from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client['email_automation']
jobs = db['web_search_jobs']

print("=" * 70)
print("FIXING OPENAI WEB SEARCH")
print("=" * 70)
print()

# Step 1: Remove the stuck job
print("1. Removing stuck job...")
stuck_job = jobs.find_one({'job_id': 'f59518ed'})
if stuck_job:
    print(f"   Found stuck job: {stuck_job.get('job_id')}")
    print(f"   Status: {stuck_job.get('status')}")
    print(f"   Created: {stuck_job.get('created_at')}")
    print(f"   Errors: {len(stuck_job.get('errors', []))}")
    
    # Archive it
    db['web_search_jobs_archive'].insert_one(stuck_job)
    jobs.delete_one({'job_id': 'f59518ed'})
    print("   ✓ Stuck job removed and archived")
else:
    print("   No stuck job found")

# Step 2: Check OpenAI API Key
print("\n2. Checking OpenAI API Key...")
openai_key = os.getenv('OPENAI_API_KEY', '')
if openai_key:
    print(f"   ✓ API key is set (length: {len(openai_key)})")
else:
    print("   ✗ API key NOT set in .env file")
    print("\n   ACTION REQUIRED:")
    print("   1. Get your OpenAI API key from: https://platform.openai.com/account/api-keys")
    print("   2. Add to backend/.env file:")
    print("      OPENAI_API_KEY=sk-proj-your-key-here")
    print("   3. Restart the backend server")
    print("\n   ⚠️ Web search will NOT work without a valid API key!")

# Step 3: Clean up any other stuck/failed jobs
print("\n3. Checking for other stuck jobs...")
all_jobs = list(jobs.find())
print(f"   Total jobs in database: {len(all_jobs)}")

if all_jobs:
    for job in all_jobs:
        job_id = job.get('job_id')
        status = job.get('status')
        created = job.get('created_at')
        queries = job.get('queries', [])
        query_combinations = job.get('query_combinations', [])
        
        print(f"\n   Job: {job_id}")
        print(f"     Status: {status}")
        print(f"     Created: {created}")
        print(f"     Queries: {len(queries)}")
        print(f"     Query Combinations: {len(query_combinations)}")
        
        # Check if job is stuck (old, no queries, or many errors)
        if not queries and not query_combinations:
            print(f"     ⚠️ WARNING: No queries defined!")
        
        errors = job.get('errors', [])
        if len(errors) > 10:
            print(f"     ⚠️ WARNING: {len(errors)} errors accumulated")

# Step 4: Reset search control
print("\n4. Resetting search control...")
settings_db = client['torpedo_settings']
control_result = settings_db['app_settings'].update_one(
    {'_id': 'search_control'},
    {'$set': {
        'paused': False,
        'paused_reason': '',
        'circuit_breaker_open': False,
        'consecutive_errors': 0,
        'last_error': None,
        'auto_resume_disabled': False
    }},
    upsert=True
)
print(f"   ✓ Search control reset (modified: {control_result.modified_count})")

print("\n" + "=" * 70)
print("NEXT STEPS:")
print("=" * 70)
print()

if not openai_key:
    print("❌ CRITICAL: Configure OpenAI API key first!")
    print()
    print("1. Edit backend/.env file")
    print("2. Add line: OPENAI_API_KEY=sk-proj-your-actual-key")
    print("3. Save the file")
    print("4. Restart backend: cd backend && uvicorn main:app --reload")
    print()
else:
    print("✓ API key is configured")
    print()
    print("Ready to create a new web search job!")
    print()
    print("To create a new job:")
    print("  1. Go to the UI: Leads > Import > Web Search")
    print("  2. Configure your search:")
    print("     - Select designations (e.g., 'market research manager')")
    print("     - Select countries")
    print("     - Set continuous mode (no target count limit)")
    print("  3. Click 'Start Web Search'")
    print()
    print("Or use the API:")
    print("  POST http://localhost:9944/leads/import/web-search")
    print("  Body: {")
    print('    "config": {')
    print('      "designations": ["market research manager", "insights director"],')
    print('      "countries": ["United States", "United Kingdom"],')
    print('      "seniorities": ["Manager", "Director"]')
    print("    }")
    print("  }")

print()
print("=" * 70)
