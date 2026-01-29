"""Check where the OpenAI API calls are coming from"""
from pymongo import MongoClient
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv('MONGO_URI'))

print("=" * 70)
print("TRACKING OPENAI API USAGE SOURCE")
print("=" * 70)

# Check torpedo_settings
settings_db = client['torpedo_settings']
print("\n📂 TORPEDO SETTINGS DATABASE:")
for coll in settings_db.list_collection_names():
    print(f"   {coll}: {settings_db[coll].count_documents({})} docs")

# Check gmail_archive
gmail_db = client['gmail_archive']
print("\n📂 GMAIL ARCHIVE DATABASE:")
for coll in gmail_db.list_collection_names():
    count = gmail_db[coll].count_documents({})
    print(f"   {coll}: {count}")

# Check torpedo_gmail
tg_db = client['torpedo_gmail']
print("\n📂 TORPEDO GMAIL DATABASE:")
for coll in tg_db.list_collection_names():
    count = tg_db[coll].count_documents({})
    print(f"   {coll}: {count}")

# Check for recent email metadata (might indicate sync activity)
email_meta = tg_db.get_collection('email_metadata')
if email_meta:
    total = email_meta.count_documents({})
    print(f"\n📧 Email metadata total: {total}")
    
    # Get most recent
    recent = list(email_meta.find({}).sort('received_at', -1).limit(3))
    print("   Recent emails:")
    for e in recent:
        date = e.get('received_at', e.get('date', 'N/A'))
        if hasattr(date, 'strftime'):
            date = date.strftime('%Y-%m-%d %H:%M')
        print(f"      {date} | {e.get('subject', 'N/A')[:50]}")

# Check AI enrichment database
ai_db = client.get_database('ai_enrichment') if 'ai_enrichment' in client.list_database_names() else None
if ai_db:
    print("\n📂 AI ENRICHMENT DATABASE:")
    for coll in ai_db.list_collection_names():
        count = ai_db[coll].count_documents({})
        print(f"   {coll}: {count}")

# Check cpx_research (might be using AI)
cpx_db = client['cpx_research']
print("\n📂 CPX RESEARCH DATABASE:")
for coll in cpx_db.list_collection_names():
    count = cpx_db[coll].count_documents({})
    print(f"   {coll}: {count}")

# Check marketing_db
mkt_db = client['marketing_db']
print("\n📂 MARKETING DATABASE:")
for coll in mkt_db.list_collection_names():
    count = mkt_db[coll].count_documents({})
    print(f"   {coll}: {count}")

print("\n" + "=" * 70)
print("NOTE: 61K API requests in January but local logs only show ~2K entries")
print("This suggests API calls are coming from:")
print("  1. A VM/server running the campaign platform")
print("  2. Direct API calls not logged to MongoDB")
print("  3. A different project using the same API key")
print("=" * 70)
