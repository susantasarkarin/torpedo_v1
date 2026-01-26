#!/usr/bin/env python3
"""
Check leads generated in the past 24 hours using OpenAI web search
"""
from pymongo import MongoClient
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

# Connect to MongoDB
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

# Check multiple databases where leads might be stored
databases_to_check = [
    ('email_automation', 'leads_raw'),
    ('email_automation', 'leads'),
    ('torpedo', 'leads_raw'),
    ('torpedo', 'leads'),
]

print("=" * 70)
print("OPENAI WEB SEARCH LEADS - PAST 24 HOURS")
print("=" * 70)
print(f"Current time: {datetime.utcnow()}")
print(f"24 hours ago: {datetime.utcnow() - timedelta(hours=24)}")
print()

# Calculate 24 hours ago
cutoff_time = datetime.utcnow() - timedelta(hours=24)

total_leads = 0
leads_found = []

for db_name, collection_name in databases_to_check:
    try:
        db = client[db_name]
        collection = db[collection_name]
        
        # Check if collection exists
        if collection_name not in db.list_collection_names():
            continue
            
        # Count leads from openai_search source in the past 24 hours
        query = {
            'source': 'openai_search',
            'created_at': {'$gte': cutoff_time}
        }
        
        count = collection.count_documents(query)
        
        if count > 0:
            print(f"\n📊 {db_name}.{collection_name}")
            print(f"   Leads from openai_search in past 24h: {count}")
            total_leads += count
            
            # Get sample leads
            samples = list(collection.find(query).sort('created_at', -1).limit(5))
            
            if samples:
                print(f"\n   Recent examples:")
                for lead in samples:
                    email = lead.get('email', 'N/A')
                    created = lead.get('created_at', 'N/A')
                    name = lead.get('name', lead.get('first_name', 'N/A'))
                    company = lead.get('company', 'N/A')
                    print(f"   • {email} ({name} - {company}) @ {created}")
                    
            leads_found.append((db_name, collection_name, count))
                    
    except Exception as e:
        print(f"⚠️ Error checking {db_name}.{collection_name}: {e}")

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

if total_leads > 0:
    print(f"✅ Total leads from OpenAI web search in past 24 hours: {total_leads}")
    print(f"\nBreakdown:")
    for db_name, collection_name, count in leads_found:
        print(f"   • {db_name}.{collection_name}: {count} leads")
else:
    print("⚠️ No leads found from OpenAI web search in the past 24 hours")
    print("\nChecking if there are ANY leads from openai_search (all time)...")
    
    for db_name, collection_name in databases_to_check:
        try:
            db = client[db_name]
            collection = db[collection_name]
            
            if collection_name not in db.list_collection_names():
                continue
                
            all_time_count = collection.count_documents({'source': 'openai_search'})
            
            if all_time_count > 0:
                print(f"\n   {db_name}.{collection_name}: {all_time_count} leads (all time)")
                
                # Get the most recent one
                latest = collection.find_one({'source': 'openai_search'}, sort=[('created_at', -1)])
                if latest:
                    latest_time = latest.get('created_at', 'Unknown')
                    print(f"   Latest lead: {latest_time}")
                    
        except Exception as e:
            pass

print("\n" + "=" * 70)
