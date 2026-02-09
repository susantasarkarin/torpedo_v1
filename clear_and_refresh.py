#!/usr/bin/env python3
"""Clear Cint data and wait for new surveys"""
from pymongo import MongoClient
import time

c = MongoClient()
db = c['cint_research']

# Delete all
db.cint_surveys.delete_many({})
db.cint_entry_links.delete_many({})
print("All Cint data cleared!")

print("Waiting 25 seconds for webhooks to deliver new surveys...")
time.sleep(25)

# Check new counts
surveys = db.cint_surveys.count_documents({})
live = db.cint_surveys.count_documents({"is_live": True})
active = db.cint_surveys.count_documents({"is_active": True})
print(f"New surveys received: {surveys}")
print(f"Live surveys: {live}")
print(f"Active surveys: {active}")

# Show samples
print("\nSample surveys:")
samples = list(db.cint_surveys.find({}, {"survey_id": 1, "survey_name": 1, "is_live": 1}).limit(5))
for s in samples:
    sid = s.get("survey_id")
    name = s.get("survey_name", "N/A")
    is_live = s.get("is_live")
    print(f"  - {sid}: {name} (live: {is_live})")
