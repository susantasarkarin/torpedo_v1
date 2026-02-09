from pymongo import MongoClient
client = MongoClient("mongodb://localhost:27017/")
db = client["campaign_platform"]
total = db.cint_surveys.count_documents({})
print("Total surveys in DB:", total)

pipeline = [
    {"$group": {"_id": "$country_language", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
    {"$limit": 50}
]
results = list(db.cint_surveys.aggregate(pipeline))
print("Top country_language values:")
for r in results:
    cid = r["_id"]
    cnt = r["count"]
    print(f"  {cid}: {cnt}")
