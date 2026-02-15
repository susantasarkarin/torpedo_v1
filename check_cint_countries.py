#!/usr/bin/env python3
import pymongo

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["cint_research"]

result = list(db.cint_surveys.aggregate([
    {"$group": {"_id": "$country_code", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}}
]))

print("Countries with CINT surveys:")
for r in result:
    print(f"  {r['_id']}: {r['count']}")

total = db.cint_surveys.count_documents({})
print(f"\nTotal CINT surveys: {total}")
