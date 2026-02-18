#!/usr/bin/env python3
"""Check CINT survey inventory"""
from pymongo import MongoClient

c = MongoClient()
coll = c.cint_research.cint_surveys

print("=== CINT Survey Inventory ===")
print(f"Total CINT surveys: {coll.count_documents({})}")
print(f"Active (is_active_in_pool=True): {coll.count_documents({'is_active_in_pool': True})}")

# Check by country_language suffix
for country in ['uk', 'in', 'us', 'gb', 'au']:
    query = {
        "country_language": {"$regex": f"_{country}$", "$options": "i"},
        "is_active_in_pool": True
    }
    count = coll.count_documents(query)
    print(f"Active for country '{country}': {count}")

# Check by country_code field (if migrated)
print("\n=== By country_code field ===")
for cc in ['UK', 'IN', 'US', 'GB', 'AU']:
    query = {"country_code": cc, "is_active_in_pool": True}
    count = coll.count_documents(query)
    print(f"Active for country_code '{cc}': {count}")

# Sample surveys
print("\n=== Sample Active Surveys ===")
for s in coll.find({"is_active_in_pool": True}).limit(5):
    print(f"  - ID: {s.get('survey_id')}, Country: {s.get('country_language')} / {s.get('country_code')}")
