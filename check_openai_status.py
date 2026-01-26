#!/usr/bin/env python3
"""
Check OpenAI web search status and historical data
"""
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv

load_dotenv()

# Connect to MongoDB
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

print("=" * 70)
print("OPENAI WEB SEARCH STATUS CHECK")
print("=" * 70)
print()

# Check web search jobs
print("📋 WEB SEARCH JOBS:")
print("-" * 70)
try:
    db = client['email_automation']
    jobs_collection = db['web_search_jobs']
    
    # Check active jobs
    active_jobs = list(jobs_collection.find({'status': {'$in': ['running', 'pending']}}).sort('created_at', -1))
    print(f"Active jobs (running/pending): {len(active_jobs)}")
    
    if active_jobs:
        for job in active_jobs[:3]:
            print(f"  • Job ID: {job.get('job_id', 'N/A')}")
            print(f"    Status: {job.get('status', 'N/A')}")
            print(f"    Progress: {job.get('processed', 0)}/{job.get('total', 0)}")
            print(f"    Created: {job.get('created_at', 'N/A')}")
            print()
    
    # Check completed jobs
    completed_jobs = jobs_collection.count_documents({'status': 'completed'})
    print(f"Completed jobs: {completed_jobs}")
    
    # Check most recent job
    latest_job = jobs_collection.find_one({}, sort=[('created_at', -1)])
    if latest_job:
        print(f"\nMost recent job:")
        print(f"  • Job ID: {latest_job.get('job_id', 'N/A')}")
        print(f"    Status: {latest_job.get('status', 'N/A')}")
        print(f"    Created: {latest_job.get('created_at', 'N/A')}")
        print(f"    Updated: {latest_job.get('updated_at', 'N/A')}")
        
except Exception as e:
    print(f"⚠️ Error checking jobs: {e}")

print()
print("=" * 70)
print("📊 LEADS DATA:")
print("-" * 70)

# Check leads in all databases
databases = [
    ('email_automation', 'leads_raw'),
    ('email_automation', 'leads'),
    ('torpedo', 'leads_raw'),
    ('torpedo', 'leads'),
]

cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)

for db_name, coll_name in databases:
    try:
        db = client[db_name]
        collection = db[coll_name]
        
        if coll_name not in db.list_collection_names():
            continue
        
        # All time leads from openai_search
        all_time = collection.count_documents({'source': 'openai_search'})
        
        if all_time == 0:
            continue
            
        print(f"\n{db_name}.{coll_name}:")
        print(f"  Total openai_search leads: {all_time}")
        
        # Time-based counts
        past_24h = collection.count_documents({'source': 'openai_search', 'created_at': {'$gte': cutoff_24h}})
        past_7d = collection.count_documents({'source': 'openai_search', 'created_at': {'$gte': cutoff_7d}})
        past_30d = collection.count_documents({'source': 'openai_search', 'created_at': {'$gte': cutoff_30d}})
        
        print(f"  Past 24 hours: {past_24h}")
        print(f"  Past 7 days: {past_7d}")
        print(f"  Past 30 days: {past_30d}")
        
        # Get most recent lead
        latest_lead = collection.find_one({'source': 'openai_search'}, sort=[('created_at', -1)])
        if latest_lead:
            print(f"  Latest lead: {latest_lead.get('created_at', 'N/A')}")
            print(f"    Email: {latest_lead.get('email', 'N/A')}")
            print(f"    Name: {latest_lead.get('name', latest_lead.get('first_name', 'N/A'))}")
            print(f"    Company: {latest_lead.get('company', 'N/A')}")
            
    except Exception as e:
        print(f"⚠️ Error checking {db_name}.{coll_name}: {e}")

print()
print("=" * 70)
print("⚙️ SEARCH CONTROL STATUS:")
print("-" * 70)

try:
    settings_db = client['torpedo_settings']
    control = settings_db['app_settings'].find_one({'_id': 'search_control'})
    
    if control:
        print(f"Paused: {control.get('paused', False)}")
        print(f"Circuit breaker open: {control.get('circuit_breaker_open', False)}")
        print(f"Consecutive errors: {control.get('consecutive_errors', 0)}")
        print(f"Auto resume disabled: {control.get('auto_resume_disabled', False)}")
        if control.get('paused_reason'):
            print(f"Paused reason: {control.get('paused_reason')}")
    else:
        print("No search control settings found")
        
except Exception as e:
    print(f"⚠️ Error checking control: {e}")

print()
print("=" * 70)
