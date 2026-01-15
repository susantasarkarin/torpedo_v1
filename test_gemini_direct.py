#!/usr/bin/env python3
import os
from dotenv import load_dotenv
load_dotenv("/var/www/campaign_platform/backend/.env")

from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
print(f"MONGO_URI: {MONGO_URI[:30]}...")
client = MongoClient(MONGO_URI)
settings = client["torpedo_settings"]["app_settings"].find_one({"_id": "app_config"})
keys = settings.get("gemini_api_keys", "") if settings else ""
print(f"Keys from DB: {keys[:20]}..." if keys else "No keys in DB")

# Test the API directly
from google import genai

if keys:
    api_key = keys.split(",")[0].strip()
    print(f"Testing key: {api_key[:10]}...")
    
    try:
        gclient = genai.Client(api_key=api_key)
        response = gclient.models.generate_content(
            model="gemini-2.0-flash",
            contents="Say hello in one word"
        )
        print(f"Success! Response: {response.text}")
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
else:
    print("No API keys found")
