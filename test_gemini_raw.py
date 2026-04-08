"""Test one key via raw requests to confirm quota issue."""
import sys, json, requests

sys.path.insert(0, '/var/www/campaign_platform/backend')
from pymongo import MongoClient

settings = MongoClient('mongodb://localhost:27017/')['torpedo_settings']['app_settings'].find_one()
key1 = settings.get('gemini_api_key_1')
print(f"Key 1 (first 20): {key1[:20]}...")

# Test v1beta (old SDK uses this)
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key1}"
body = {"contents": [{"parts": [{"text": "Reply with OK only"}]}]}
r = requests.post(url, json=body)
print(f"\nStatus: {r.status_code}")
resp = r.json()
if 'error' in resp:
    print(f"Error code: {resp['error'].get('code')}")
    print(f"Error msg: {resp['error'].get('message', '')[:200]}")
    details = resp['error'].get('details', [])
    for d in details:
        if d.get('@type') and 'QuotaFailure' in d['@type']:
            for v in d.get('violations', []):
                print(f"  violation: {v.get('quotaId')} limit={v.get('quotaValue')}")
else:
    print("SUCCESS:", json.dumps(resp, indent=2)[:300])

# Test v1 (newer)
url_v1 = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={key1}"
r2 = requests.post(url_v1, json=body)
print(f"\nv1 API Status: {r2.status_code}")
resp2 = r2.json()
if 'error' in resp2:
    print(f"v1 Error: {resp2['error'].get('message', '')[:200]}")
else:
    print("v1 SUCCESS:", json.dumps(resp2, indent=2)[:300])
