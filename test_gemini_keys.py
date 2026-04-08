"""Test each Gemini key with a minimal call to see which ones work."""
import sys, os, time
sys.path.insert(0, '/var/www/campaign_platform/backend')

from pymongo import MongoClient
import google.generativeai as genai

db = MongoClient('mongodb://localhost:27017/')

settings = db['torpedo_settings']['app_settings'].find_one()
if not settings:
    print("No app_settings found!")
    sys.exit(1)

# Try each key
MODELS = ["gemini-1.5-flash", "gemini-2.0-flash-lite", "gemini-2.0-flash"]

for i in range(1, 11):
    key_name = f"gemini_api_key_{i}"
    api_key = settings.get(key_name)
    if not api_key:
        print(f"Key {i}: NOT FOUND")
        continue

    print(f"\nKey {i}: {api_key[:20]}...")
    for model_name in MODELS:
        try:
            genai.configure(api_key=api_key)
            m = genai.GenerativeModel(model_name)
            resp = m.generate_content("Say OK")
            print(f"  [{model_name}] ✅ SUCCESS: {resp.text[:40]}")
            break  # found a working model, move to next key
        except Exception as e:
            err = str(e)[:120]
            print(f"  [{model_name}] ❌ {err}")
        time.sleep(0.5)
