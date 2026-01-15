#!/usr/bin/env python3
import os
from dotenv import load_dotenv
load_dotenv("/var/www/campaign_platform/backend/.env")

from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
settings = client["torpedo_settings"]["app_settings"].find_one({"_id": "app_config"})
keys = settings.get("gemini_api_keys", "") if settings else ""
api_key = keys.split(",")[0].strip()

from google import genai
gclient = genai.Client(api_key=api_key)

# Try different models
models_to_try = [
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash-lite", 
    "gemini-flash-lite-latest",
]

for model in models_to_try:
    try:
        print(f"Trying {model}...")
        response = gclient.models.generate_content(model=model, contents="Say hi")
        print(f"  Success: {response.text}")
        break
    except Exception as e:
        print(f"  Error: {str(e)[:100]}")
