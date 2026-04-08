"""Check the actual Gemini keys stored in torpedo_settings.app_settings (single-doc schema)."""
import urllib.request, json
from pymongo import MongoClient

c = MongoClient()
settings = c['torpedo_settings']['app_settings'].find_one()
if not settings:
    print("ERROR: No app_settings document found!")
    exit(1)

keys = {}
for i in range(1, 11):
    k = f'gemini_api_key_{i}'
    if k in settings:
        keys[i] = settings[k]
        print(f"  {k}: {settings[k][:20]}...")
    else:
        print(f"  gemini_api_key_{i}: NOT IN DB")

print(f"\nTotal keys found: {len(keys)}")

# Quick live test on each found key
MODEL = "gemini-2.0-flash"
PAYLOAD = json.dumps({"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}).encode()
print("\n--- Testing each key ---")
working = []
for idx, api_key in keys.items():
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={api_key}"
    req = urllib.request.Request(url, data=PAYLOAD, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"  key_{idx}: OK")
            working.append(idx)
    except urllib.error.HTTPError as e:
        code = e.code
        body = e.read().decode()[:60]
        print(f"  key_{idx}: {code} — {body[:60]}")
    except Exception as e:
        print(f"  key_{idx}: ERR {e}")

print(f"\n{'READY: ' + str(len(working)) + ' keys working!' if working else 'ALL KEYS EXHAUSTED — wait for midnight UTC quota reset'}")
