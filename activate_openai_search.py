"""
Activate OpenAI Search functionality by resetting search control.
"""
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
settings_db = client['torpedo_settings']
app_settings = settings_db['app_settings']

print("=" * 60)
print("ACTIVATING OPENAI SEARCH")
print("=" * 60)

# 1. Reset search control - clear errors and unpause
print("\n1. Resetting search control...")
result = app_settings.update_one(
    {'_id': 'search_control'},
    {'$set': {
        'paused': False,
        'paused_at': None,
        'paused_reason': '',
        'circuit_breaker_open': False,
        'consecutive_errors': 0,
        'last_error': None,
        'auto_resume_disabled': False
    }},
    upsert=True
)
print(f"   Modified: {result.modified_count}, Upserted: {result.upserted_id}")

# 2. Reset any circuit breakers in email_automation
print("\n2. Resetting circuit breakers...")
email_db = client['email_automation']
breaker_result = email_db['circuit_breakers'].delete_many({})
print(f"   Deleted {breaker_result.deleted_count} circuit breakers")

# 3. Verify the new status
print("\n3. Verifying new status...")
control = app_settings.find_one({'_id': 'search_control'})
print(f"   Paused: {control.get('paused', 'N/A')}")
print(f"   Circuit Breaker Open: {control.get('circuit_breaker_open', 'N/A')}")
print(f"   Consecutive Errors: {control.get('consecutive_errors', 'N/A')}")
print(f"   Auto Resume Disabled: {control.get('auto_resume_disabled', 'N/A')}")

# 4. Check API key status
print("\n4. Checking API keys...")
config = app_settings.find_one({'_id': 'app_config'})
if config:
    openai_key = config.get('openai_api_key', '')
    has_openai = bool(openai_key)
    print(f"   OpenAI API Key: {'SET' if has_openai else 'NOT SET'}")
    if has_openai:
        # Show first and last 4 chars
        if len(openai_key) > 8:
            print(f"   Key preview: {openai_key[:7]}...{openai_key[-4:]}")
    
    print(f"   Google API Key: {'SET' if config.get('google_api_key') else 'NOT SET'}")
    print(f"   Google CSE ID: {'SET' if config.get('google_cse_id') else 'NOT SET'}")
else:
    print("   No app config found!")

# 5. Check for any stalled jobs
print("\n5. Checking web search jobs...")
jobs_db = client['email_automation']
jobs = list(jobs_db['web_search_jobs'].find(
    {'status': {'$in': ['running', 'pending', 'paused', 'quota_exceeded', 'api_error']}}
))
if jobs:
    print(f"   Found {len(jobs)} incomplete jobs:")
    for job in jobs:
        print(f"      - {job['job_id']}: {job['status']} (imported: {job.get('total_imported', 0)})")
else:
    print("   No incomplete jobs found.")

print("\n" + "=" * 60)
print("OPENAI SEARCH ACTIVATED!")
print("=" * 60)
print("\nTo start a new search, use the API endpoint:")
print("  POST /leads/import/web-search")
print("\nOr use the AI Leads page in the frontend.")
print()
