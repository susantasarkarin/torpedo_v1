#!/usr/bin/env python3
"""Check Gmail lead stages"""
from pymongo import MongoClient
db = MongoClient()["email_automation"]

print("=== Stage values for Gmail leads ===")
for r in db["leads_enriched"].aggregate([{"$match": {"source": "gmail"}}, {"$group": {"_id": "$stage", "count": {"$sum": 1}}}]):
    stage = r["_id"]
    cnt = r["count"]
    print(f"  '{stage}': {cnt}")

print()
print("=== Sample Gmail lead ===")
sample = db["leads_enriched"].find_one({"source": "gmail"})
if sample:
    print(f"  Name: {sample.get('name')}")
    print(f"  Stage: '{sample.get('stage')}'")
    print(f"  Lead Stage: '{sample.get('lead_stage')}'")
    print(f"  Source: {sample.get('source')}")
