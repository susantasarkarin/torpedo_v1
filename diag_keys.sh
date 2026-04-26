#!/bin/bash
python3 << 'PYEOF'
import os

print("=== ENV VARS ===")
for k, v in os.environ.items():
    if 'OPENAI' in k.upper() or 'API_KEY' in k.upper():
        display = v[:25] + '...' + v[-8:] if len(v) > 33 else v
        print(f"  {k}: {display}")

print()
print("=== ROTATOR KEYS (email_automation.openai_quota) ===")
from pymongo import MongoClient
db = MongoClient()['email_automation']
quota = list(db['openai_quota'].find().sort('key_index', 1))
for q in quota:
    idx = q.get('key_index', '?')
    key = q.get('api_key', '')
    key_display = key[:20] + '...' + key[-8:] if len(key) > 28 else key
    err = str(q.get('last_error', ''))[:80]
    print(f"  Key {idx}: {key_display}  error={err}")
if not quota:
    print("  (empty)")

print()
print("=== HOW ROTATOR LOADS KEYS ===")
# Check if keys come from env or DB
for i in range(1, 13):
    envk = f'OPENAI_API_KEY_{i}'
    v = os.getenv(envk, '')
    if v:
        display = v[:15] + '...' + v[-6:] if len(v) > 21 else v
        print(f"  {envk}: {display}")
    else:
        print(f"  {envk}: NOT SET")

print()
print("=== SETTINGS DB ===")
db2 = MongoClient()['torpedo_settings']
for doc in db2['settings'].find():
    k = doc.get('key', '')
    if 'openai' in k.lower() or 'api' in k.lower() or 'key' in k.lower():
        v = str(doc.get('value', ''))[:100]
        print(f"  {k}: {v}")
PYEOF
