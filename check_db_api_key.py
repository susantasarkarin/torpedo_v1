#!/usr/bin/env python3
"""
Check OpenAI API key in database settings (from UI)
"""
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

print("=" * 70)
print("CHECKING OPENAI API KEY IN PROFILE > SETTINGS")
print("=" * 70)
print()

# Check torpedo_settings database - all documents
settings_db = client['torpedo_settings']

print("1. All collections in torpedo_settings:")
collections = settings_db.list_collection_names()
for coll in collections:
    print(f"   - {coll}")

print("\n2. Checking app_settings collection:")
app_settings_docs = list(settings_db['app_settings'].find())
for doc in app_settings_docs:
    doc_id = doc.get('_id')
    print(f"\n   Document: {doc_id}")
    
    # Look for any key-related fields
    for key, value in doc.items():
        if key == '_id':
            continue
        if 'key' in key.lower() or 'openai' in key.lower() or 'api' in key.lower():
            if isinstance(value, str) and len(value) > 10:
                print(f"     {key}: {value[:15]}... (length: {len(value)})")
            else:
                print(f"     {key}: {value}")

print("\n3. Checking for user_settings or profile collections:")
for coll_name in collections:
    if 'user' in coll_name.lower() or 'profile' in coll_name.lower():
        print(f"\n   Collection: {coll_name}")
        docs = list(settings_db[coll_name].find().limit(3))
        for doc in docs:
            print(f"     Document ID: {doc.get('_id')}")
            for key in doc.keys():
                if 'key' in key.lower() or 'openai' in key.lower():
                    value = doc.get(key)
                    if isinstance(value, str) and len(value) > 10:
                        print(f"       {key}: {value[:15]}...")

print("\n4. Searching all app_settings for 'openai' string:")
for doc in app_settings_docs:
    doc_str = str(doc).lower()
    if 'openai' in doc_str or 'sk-proj' in doc_str:
        print(f"\n   Found in document: {doc.get('_id')}")
        print(f"   Keys: {list(doc.keys())}")
        
        # Print all fields
        for key, value in doc.items():
            if key != '_id':
                if isinstance(value, str):
                    if len(value) > 100:
                        print(f"     {key}: {value[:50]}... (length: {len(value)})")
                    else:
                        print(f"     {key}: {value}")
                elif isinstance(value, dict):
                    print(f"     {key}: (dict with {len(value)} keys)")
                    for subkey, subval in value.items():
                        if isinstance(subval, str) and len(subval) > 10:
                            print(f"       {subkey}: {subval[:20]}...")
                        else:
                            print(f"       {subkey}: {subval}")
                else:
                    print(f"     {key}: {value}")

print("\n5. Checking if there's a system_config or global_config:")
for doc_id in ['system_config', 'global_config', 'api_config', 'credentials']:
    doc = settings_db['app_settings'].find_one({'_id': doc_id})
    if doc:
        print(f"\n   Found: {doc_id}")
        for key, value in doc.items():
            if key != '_id':
                print(f"     {key}: {str(value)[:100]}")

print("\n" + "=" * 70)
print("SUMMARY:")
print("=" * 70)

# Final check - look for any API key pattern
found_key = False
for doc in app_settings_docs:
    doc_str = str(doc)
    if 'sk-proj-' in doc_str or 'sk-' in doc_str:
        found_key = True
        print(f"\n✓ Found API key pattern in document: {doc.get('_id')}")
        break

if not found_key:
    print("\n⚠️ No OpenAI API key found in database")
    print("\nPossible locations to check in UI:")
    print("  - Profile > Settings > AI Providers")
    print("  - Settings > API Keys")
    print("  - System > Configuration")

print("\n" + "=" * 70)
