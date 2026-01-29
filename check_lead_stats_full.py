"""Comprehensive lead stats from all databases"""
from pymongo import MongoClient
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017/'))
two_days_ago = datetime.utcnow() - timedelta(days=2)

print("=" * 70)
print("COMPREHENSIVE LEAD GENERATION STATS - OpenAI Web Search")
print("=" * 70)

# Check email_automation database (main leads storage)
db = client['email_automation']

# Collections to check
collections = ['leads', 'email_leads', 'leads_raw', 'leads_enriched', 'vendor_leads', 'ai_discovered_companies']

for coll_name in collections:
    coll = db[coll_name]
    total = coll.count_documents({})
    
    # Check for openai_search source
    openai_src = coll.count_documents({'source': 'openai_search'})
    openai_websearch = coll.count_documents({'enrichment_source': 'openai_websearch'})
    
    # Recent (2 days)
    recent_total = coll.count_documents({'created_at': {'$gte': two_days_ago}})
    recent_openai = coll.count_documents({'source': 'openai_search', 'created_at': {'$gte': two_days_ago}})
    
    print(f"\n📂 {coll_name}:")
    print(f"   Total: {total}")
    print(f"   OpenAI Search source: {openai_src}")
    print(f"   OpenAI WebSearch enriched: {openai_websearch}")
    print(f"   Last 2 days: {recent_total} (OpenAI: {recent_openai})")

# Check web_search_jobs for job history
print("\n" + "=" * 70)
print("WEB SEARCH JOBS STATUS")
print("=" * 70)

jobs = db['web_search_jobs']
total_jobs = jobs.count_documents({})
recent_jobs = jobs.count_documents({'created_at': {'$gte': two_days_ago}})
completed_jobs = jobs.count_documents({'status': 'completed'})
active_jobs = jobs.count_documents({'status': {'$in': ['running', 'pending', 'in_progress']}})

print(f"\n📊 Web Search Jobs:")
print(f"   Total jobs: {total_jobs}")
print(f"   Jobs in last 2 days: {recent_jobs}")
print(f"   Completed: {completed_jobs}")
print(f"   Active/Pending: {active_jobs}")

# Show recent jobs
print("\n📝 Recent Web Search Jobs:")
recent = list(jobs.find({}).sort('created_at', -1).limit(5))
for j in recent:
    created = j.get('created_at', 'N/A')
    if hasattr(created, 'strftime'):
        created = created.strftime('%Y-%m-%d %H:%M')
    print(f"   {created} | {j.get('status', 'N/A')} | {j.get('query', j.get('search_query', 'N/A'))[:50]}")

if not recent:
    print("   (No jobs found)")

# Check ai_usage_logs for OpenAI web search usage
print("\n" + "=" * 70)
print("AI USAGE LOGS (web search related)")
print("=" * 70)

usage_logs = db['ai_usage_logs']
total_logs = usage_logs.count_documents({})
web_search_logs = usage_logs.count_documents({'endpoint': {'$regex': 'web', '$options': 'i'}})
recent_logs = usage_logs.count_documents({'timestamp': {'$gte': two_days_ago}})

print(f"\n📊 AI Usage:")
print(f"   Total logs: {total_logs}")
print(f"   Web search related: {web_search_logs}")
print(f"   Logs in last 2 days: {recent_logs}")

# Recent usage
print("\n📝 Recent AI Usage (last 5):")
recent_usage = list(usage_logs.find({}).sort('timestamp', -1).limit(5))
for u in recent_usage:
    ts = u.get('timestamp', u.get('created_at', 'N/A'))
    if hasattr(ts, 'strftime'):
        ts = ts.strftime('%Y-%m-%d %H:%M')
    print(f"   {ts} | {u.get('endpoint', 'N/A')} | {u.get('model', 'N/A')} | {u.get('source', 'N/A')}")

if not recent_usage:
    print("   (No usage logs)")

print("\n" + "=" * 70)
