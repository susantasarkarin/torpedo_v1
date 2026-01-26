#!/usr/bin/env python3
"""
Test OpenAI API key from database
"""
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

def get_openai_api_key():
    """Get OpenAI API key from database or environment"""
    try:
        MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        settings_db = client["torpedo_settings"]
        app_settings = settings_db["app_settings"]
        stored = app_settings.find_one({"_id": "app_config"})
        
        if stored and stored.get("openai_api_key"):
            return stored["openai_api_key"]
        
        # Fallback to env var
        return os.getenv("OPENAI_API_KEY")
    except Exception as e:
        print(f"Error fetching OpenAI key: {e}")
        return os.getenv("OPENAI_API_KEY")

print("=" * 70)
print("TESTING OPENAI API KEY")
print("=" * 70)
print()

# Get the key
api_key = get_openai_api_key()

if api_key:
    print(f"✓ API Key retrieved successfully")
    print(f"  Length: {len(api_key)}")
    print(f"  Starts with: {api_key[:15]}...")
    print(f"  Ends with: ...{api_key[-10:]}")
    
    # Test the key with OpenAI
    print("\nTesting API key with OpenAI...")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        # Simple test call
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say 'API key works!'"}],
            max_tokens=10
        )
        
        result = response.choices[0].message.content
        print(f"  ✓ API call successful!")
        print(f"  Response: {result}")
        
    except Exception as e:
        print(f"  ✗ API call failed: {e}")
        
        if "401" in str(e) or "Incorrect API key" in str(e):
            print("\n  ❌ INVALID API KEY")
            print("  The key in the database is incorrect or expired")
            print("\n  Fix in UI:")
            print("    1. Go to Profile > Settings")
            print("    2. Find OpenAI API Key field")
            print("    3. Get a new key from: https://platform.openai.com/account/api-keys")
            print("    4. Paste the new key and save")
        elif "quota" in str(e).lower():
            print("\n  ⚠️ API QUOTA EXCEEDED")
            print("  Your OpenAI account has no credits or quota exceeded")
        else:
            print(f"\n  Unknown error: {e}")
else:
    print("✗ No API key found")
    print("\nPlease configure OpenAI API key:")
    print("  1. Go to: https://platform.openai.com/account/api-keys")
    print("  2. Create a new key")
    print("  3. Add via UI: Profile > Settings > OpenAI API Key")

print("\n" + "=" * 70)
