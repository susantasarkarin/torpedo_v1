#!/usr/bin/env python3
"""Check if OpenAI API key is stored in database settings"""
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

print("=" * 70)
print("CHECKING FOR OPENAI API KEY IN DATABASE")
print("=" * 70)
print()

# Check torpedo_settings database
print("1. Checking torpedo_settings.app_settings...")
settings_db = client['torpedo_settings']
app_settings = settings_db['app_settings'].find_one({'_id': 'api_keys'})

if app_settings:
    openai_key = app_settings.get('openai_api_key', '')
    if openai_key:
        print(f"   ✓ Found OpenAI key in database (length: {len(openai_key)})")
        print(f"   Starts with: {openai_key[:10]}...")
    else:
        print("   ✗ No OpenAI key in database")
else:
    print("   No api_keys document found")

# Check for AI provider settings
print("\n2. Checking AI provider settings...")
ai_settings = settings_db['app_settings'].find_one({'_id': 'ai_providers'})
if ai_settings:
    print("   Found AI provider settings:")
    for key, value in ai_settings.items():
        if 'key' in key.lower() or 'token' in key.lower():
            if value and isinstance(value, str):
                print(f"   - {key}: {value[:10]}... (length: {len(value)})")
            else:
                print(f"   - {key}: <not set>")
else:
    print("   No AI provider settings found")

# Check all app_settings documents
print("\n3. Listing all app_settings documents...")
all_settings = list(settings_db['app_settings'].find())
print(f"   Total documents: {len(all_settings)}")
for doc in all_settings:
    print(f"   - {doc.get('_id', 'N/A')}")

print()
print("=" * 70)
print("RECOMMENDATION:")
print("=" * 70)

# Check .env file
env_key = os.getenv('OPENAI_API_KEY', '')
db_key = app_settings.get('openai_api_key', '') if app_settings else ''

if env_key:
    print(f"\n✓ API key found in .env file (length: {len(env_key)})")
elif db_key:
    print(f"\n✓ API key found in database (length: {len(db_key)})")
    print("   The backend should load this automatically")
else:
    print("\n❌ NO API KEY FOUND")
    print("\nYou need to configure the OpenAI API key:")
    print("  1. Get key from: https://platform.openai.com/account/api-keys")
    print("  2. Add to .env file: OPENAI_API_KEY=sk-proj-...")
    print("  OR")
    print("  3. Add via Settings UI: Profile > Settings > AI Providers")

print()
print("=" * 70)
