#!/usr/bin/env python3
"""Find a survey without an existing entry link"""
from pymongo import MongoClient

c = MongoClient()
db = c['cint_research']

# Find surveys that don't have entry links yet
print("Finding surveys without entry links...")

surveys_with_links = set(
    doc['survey_id'] for doc in db.cint_entry_links.find({}, {'survey_id': 1})
)
print(f"Total surveys with entry links: {len(surveys_with_links)}")

# Find live surveys without links
live_surveys = list(db.cint_surveys.find(
    {"is_live": True, "survey_id": {"$nin": list(surveys_with_links)}},
    {"survey_id": 1, "survey_name": 1, "_id": 0}
).sort("created_at", -1).limit(5))

print(f"\nLive surveys WITHOUT entry links:")
for s in live_surveys:
    print(f"  - {s['survey_id']}: {s.get('survey_name', 'N/A')}")
