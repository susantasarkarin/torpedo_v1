from pymongo import MongoClient
client = MongoClient("mongodb://localhost:27017/")

# Check ALL country_language values in cint_research.cint_surveys
db = client["cint_research"]
coll = db["cint_surveys"]
print("=== cint_research.cint_surveys ===")
print(f"Total: {coll.count_documents({})}")

pipeline = [
    {"$group": {"_id": "$country_language", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}}
]
results = list(coll.aggregate(pipeline))
print(f"\nAll country_language values ({len(results)} unique):")
for r in results:
    print(f"  {r['_id']}: {r['count']}")

# Check a sample document to see all fields
sample = coll.find_one()
if sample:
    print("\nSample document keys:", list(sample.keys()))
    print("country_language:", sample.get("country_language"))
    print("country:", sample.get("country"))

# Check survey_allocation.surveys for country info
db2 = client["survey_allocation"]
coll2 = db2["surveys"]
print("\n=== survey_allocation.surveys ===")
print(f"Total: {coll2.count_documents({})}")

pipeline2 = [
    {"$group": {"_id": "$country", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
    {"$limit": 50}
]
results2 = list(coll2.aggregate(pipeline2))
print(f"\nCountry distribution:")
for r in results2:
    print(f"  {r['_id']}: {r['count']}")

# Check if there's a country_language field in survey_allocation
pipeline3 = [
    {"$group": {"_id": "$country_language", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
    {"$limit": 50}
]
results3 = list(coll2.aggregate(pipeline3))
print(f"\nCountry_language distribution in survey_allocation:")
for r in results3:
    print(f"  {r['_id']}: {r['count']}")

# Sample from survey_allocation
sample2 = coll2.find_one({"country": {"$ne": None, "$ne": "ALL"}})
if sample2:
    print("\nSample survey_allocation document with country:")
    print("  country:", sample2.get("country"))
    print("  country_language:", sample2.get("country_language"))
    print("  source:", sample2.get("source"))
    print("  provider:", sample2.get("provider"))
