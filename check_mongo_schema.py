#!/usr/bin/env python3
"""Inspect latest MongoDB record schema + find India Cint allocations."""
import os, json, pymongo
from dotenv import load_dotenv
load_dotenv('/var/www/campaign_platform/backend/.env')

uri = os.getenv('MONGO_URI') or os.getenv('MONGODB_URI') or os.getenv('MONGO_URL')
client = pymongo.MongoClient(uri)
db = client['traffic_flow_db']
coll = db['url_parameters']

# Latest record – check field names
r = coll.find_one({}, sort=[('_id', -1)])
if r:
    print("=== Latest record fields ===")
    for k, v in r.items():
        print(f"  {k}: {str(v)[:100]}")

# Try finding IN records with various field names
print("\n=== Searching for IN records with Cint links ===")
for field in ['countryCode', 'ipCountry', 'country', 'cc']:
    for val in ['IN', 'in', 'India']:
        q = {field: val}
        n = coll.count_documents(q)
        if n > 0:
            print(f"  {field}={val!r}: {n} records")

# Find any record with a Cint entry link
for field in ['cintEntryLink', 'cint_entry_link', 'entryLink', 'entry_link', 'surveyLink']:
    n = coll.count_documents({field: {'$exists': True}})
    if n > 0:
        print(f"  Records with {field}: {n}")
        sample = coll.find_one({field: {'$exists': True}}, sort=[('_id', -1)])
        link = str(sample.get(field, ''))
        if '?' in link:
            qs = link.split('?', 1)[1]
            params = {p.split('=')[0]: p.split('=', 1)[1] for p in qs.split('&') if '=' in p}
            nums = {k: v for k, v in params.items() if k.isdigit()}
            print(f"    Sample numeric profile vars: {nums}")
            print(f"    ipRegion={sample.get('ipRegion')}, ipCity={sample.get('ipCity')}, ipCountry={sample.get('ipCountry')}")
