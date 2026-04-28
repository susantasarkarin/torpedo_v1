import pymongo

client = pymongo.MongoClient("mongodb://localhost:27017/")
col = client["email_automation"]["leads_enriched"]

# Check basket distribution
pipeline = [
    {"$match": {"email": {"$exists": True, "$ne": ""}}},
    {"$group": {"_id": "$classification_basket", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
]
print("=== Basket counts (email+basket) ===")
for row in col.aggregate(pipeline):
    print(f"  {row['_id']}: {row['count']}")

total = col.count_documents({})
with_email = col.count_documents({"email": {"$exists": True, "$ne": ""}})
with_basket = col.count_documents({"classification_basket": {"$exists": True, "$ne": None, "$ne": ""}})
print(f"\nTotal leads_enriched: {total}")
print(f"With email: {with_email}")
print(f"With basket: {with_basket}")

# Check a sample
sample = col.find_one({"email": {"$exists": True, "$ne": ""}})
if sample:
    print(f"\nSample lead basket: {sample.get('classification_basket')}, email: {sample.get('email','')[:30]}")
