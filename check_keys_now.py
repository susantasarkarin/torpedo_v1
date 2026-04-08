"""Quick test — check which Gemini keys work right now."""
import sys
import urllib.request
import json

sys.path.insert(0, '/var/www/campaign_platform/backend')
from pymongo import MongoClient

db = MongoClient()['torpedo_settings']
docs = list(db.app_settings.find(
    {'key': {'$regex': 'gemini_api_key'}},
    {'key': 1, 'value': 1}
))
print(f"Found {len(docs)} keys in DB")

MODEL = "gemini-2.0-flash"
PROMPT = '{"contents":[{"role":"user","parts":[{"text":"Say ok"}]}]}'

working = []
for doc in docs:
    key_name = doc['key']
    api_key = doc['value']
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={api_key}"
    req = urllib.request.Request(
        url, data=PROMPT.encode(), 
        headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"  {key_name}: OK (HTTP 200)")
            working.append(key_name)
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:100]
        print(f"  {key_name}: FAIL {e.code} — {body[:80]}")
    except Exception as e:
        print(f"  {key_name}: ERROR {e}")

print(f"\nWorking keys: {len(working)}/{len(docs)}")
if working:
    print("Ready to run enrichment!")
else:
    print("All keys quota-exhausted. Wait until midnight UTC for daily reset.")
