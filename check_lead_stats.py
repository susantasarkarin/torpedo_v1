"""Quick check for OpenAI web search lead generation stats"""
from pymongo import MongoClient
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017/'))
db = client['torpedo_leads']
leads = db['leads']

# Time ranges
two_days_ago = datetime.utcnow() - timedelta(days=2)
seven_days_ago = datetime.utcnow() - timedelta(days=7)

print("=" * 60)
print("LEAD GENERATION STATS - OpenAI Web Search")
print("=" * 60)

# All time stats
total_all = leads.count_documents({})
openai_all = leads.count_documents({'source': 'openai_search'})
enriched_all = leads.count_documents({'enrichment_source': 'openai_websearch'})

print(f"\n📊 ALL TIME:")
print(f"   Total leads in DB: {total_all}")
print(f"   OpenAI Search source: {openai_all}")
print(f"   OpenAI WebSearch enriched: {enriched_all}")

# Last 2 days
openai_2d = leads.count_documents({'source': 'openai_search', 'created_at': {'$gte': two_days_ago}})
enriched_2d = leads.count_documents({'enrichment_source': 'openai_websearch', 'created_at': {'$gte': two_days_ago}})
total_2d = leads.count_documents({'created_at': {'$gte': two_days_ago}})

print(f"\n📅 LAST 2 DAYS (since {two_days_ago.strftime('%Y-%m-%d %H:%M')}):")
print(f"   OpenAI Search leads: {openai_2d}")
print(f"   OpenAI WebSearch enriched: {enriched_2d}")
print(f"   Total leads created: {total_2d}")

# Last 7 days
openai_7d = leads.count_documents({'source': 'openai_search', 'created_at': {'$gte': seven_days_ago}})
enriched_7d = leads.count_documents({'enrichment_source': 'openai_websearch', 'created_at': {'$gte': seven_days_ago}})
total_7d = leads.count_documents({'created_at': {'$gte': seven_days_ago}})

print(f"\n📅 LAST 7 DAYS (since {seven_days_ago.strftime('%Y-%m-%d %H:%M')}):")
print(f"   OpenAI Search leads: {openai_7d}")
print(f"   OpenAI WebSearch enriched: {enriched_7d}")
print(f"   Total leads created: {total_7d}")

# Recent leads sample
print("\n📝 MOST RECENT LEADS:")
recent = list(leads.find({}).sort('created_at', -1).limit(5))
for l in recent:
    created = l.get('created_at', 'N/A')
    if hasattr(created, 'strftime'):
        created = created.strftime('%Y-%m-%d %H:%M')
    print(f"   {created} | {l.get('source', 'N/A')} | {l.get('name', 'N/A')}")

if not recent:
    print("   (No leads in database)")

# Source breakdown
print("\n📈 SOURCE BREAKDOWN (all time):")
pipeline = [
    {"$group": {"_id": "$source", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
    {"$limit": 10}
]
sources = list(leads.aggregate(pipeline))
for s in sources:
    print(f"   {s['_id'] or 'unknown'}: {s['count']}")

print("\n" + "=" * 60)
