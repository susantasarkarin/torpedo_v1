#!/usr/bin/env python3
"""Check survey status breakdown"""
from pymongo import MongoClient
import json

c = MongoClient()
db = c['cint_research']

print("=== SURVEY STATUS BREAKDOWN ===")
total = db.cint_surveys.count_documents({})
active = db.cint_surveys.count_documents({"is_active": True})
inactive = db.cint_surveys.count_documents({"is_active": False})
live = db.cint_surveys.count_documents({"is_live": True})
not_live = db.cint_surveys.count_documents({"is_live": False})

print(f"Total: {total}")
print(f"is_active=True: {active}")
print(f"is_active=False: {inactive}")
print(f"is_live=True: {live}")
print(f"is_live=False: {not_live}")

# Check a sample inactive survey
print("\n=== SAMPLE INACTIVE SURVEY ===")
sample = db.cint_surveys.find_one({"is_active": False})
if sample:
    sample['_id'] = str(sample['_id'])
    print(json.dumps(sample, indent=2, default=str))
else:
    print("No inactive surveys found")

# Check what fields determine activity
print("\n=== SAMPLE ACTIVE SURVEY ===")
active_sample = db.cint_surveys.find_one({"is_active": True, "is_live": True})
if active_sample:
    keys = list(active_sample.keys())
    print(f"Fields: {keys}")
    print(f"is_active: {active_sample.get('is_active')}")
    print(f"is_live: {active_sample.get('is_live')}")
    print(f"message_reason: {active_sample.get('message_reason')}")
    print(f"total_remaining: {active_sample.get('total_remaining')}")
