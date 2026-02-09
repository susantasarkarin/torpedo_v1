from pymongo import MongoClient
client = MongoClient("mongodb://localhost:27017/")

# Check cint_research.cint_surveys
db = client["cint_research"]
coll = db["cint_surveys"]
total = coll.count_documents({})
print(f"cint_research.cint_surveys: {total}")

# Check country_language values
pipeline = [
    {"$group": {"_id": "$country_language", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
    {"$limit": 50}
]
results = list(coll.aggregate(pipeline))
print("\nCountry_language distribution:")
for r in results:
    cid = r["_id"]
    cnt = r["count"]
    print(f"  {cid}: {cnt}")

# Check survey_allocation.surveys  
db2 = client["survey_allocation"]
coll2 = db2["surveys"]
total2 = coll2.count_documents({})
print(f"\nsurvey_allocation.surveys: {total2}")

# Check countries in survey_allocation
pipeline2 = [
    {"$group": {"_id": "$country", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
    {"$limit": 30}
]
results2 = list(coll2.aggregate(pipeline2))
print("\nsurvey_allocation countries:")
for r in results2:
    cid = r["_id"]
    cnt = r["count"]
    print(f"  {cid}: {cnt}")
