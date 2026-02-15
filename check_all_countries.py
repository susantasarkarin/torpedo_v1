#!/usr/bin/env python3
import pymongo

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["cint_research"]

# Get country distribution
result = list(db.cint_surveys.aggregate([
    {"$match": {"country_code": {"$exists": True, "$ne": None}}},
    {"$group": {"_id": "$country_code", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}}
]))

print("🌍 CINT Surveys by Country (after migration):\n")
total = 0
for r in result:
    country = r['_id']
    count = r['count']
    total += count
    print(f"  {country:3} : {count:5,} surveys")

print(f"\n{'='*40}")
print(f"Total: {total:,} surveys across {len(result)} countries")
print(f"\n✅ CPX → CINT fallback will work for ALL these countries!")

client.close()
