#!/usr/bin/env python3
"""Check recent India Cint entry links in MongoDB to find active profile variable IDs."""
import os
import json
from dotenv import load_dotenv
load_dotenv('/var/www/campaign_platform/backend/.env')
import pymongo

uri = os.getenv('MONGO_URI') or os.getenv('MONGODB_URI') or os.getenv('MONGO_URL')
if not uri:
    print("❌ MONGO_URI not set")
    raise SystemExit(1)

client = pymongo.MongoClient(uri)
db = client['traffic_flow_db']
coll = db['url_parameters']

# Find recent India records with Cint allocation
query = {
    '$or': [
        {'countryCode': {'$in': ['IN', 'in']}},
        {'ipCountry': {'$in': ['IN', 'in']}},
    ],
    'cintSurveyNumber': {'$exists': True},
}
recent = list(coll.find(query, {
    'cintEntryLink': 1,
    'cintSurveyNumber': 1,
    'profilingData': 1,
    'ipCountry': 1,
    'ipRegion': 1,
    'ipCity': 1,
    '_id': 0,
}).sort('_id', -1).limit(5))

print(f"Found {len(recent)} recent IN+Cint records\n")
for r in recent:
    entry_link = r.get('cintEntryLink', '')
    # Extract query string from entry link to see what variables were passed
    if '?' in entry_link:
        qs = entry_link.split('?', 1)[1]
        params = dict(p.split('=', 1) for p in qs.split('&') if '=' in p)
        print(f"  SurveyNumber: {r.get('cintSurveyNumber')}")
        print(f"  ipRegion: {r.get('ipRegion')}, ipCity: {r.get('ipCity')}")
        print(f"  profilingData: {r.get('profilingData', {})}")
        profile_vars = {k: v for k, v in params.items() if k.isdigit()}
        print(f"  Entry link profile vars: {profile_vars}")
        print()
