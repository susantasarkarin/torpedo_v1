from pymongo import MongoClient

c = MongoClient("mongodb://localhost:27017/")
db = c["torpedo_gmail"]

total = db.email_metadata.count_documents({})
classified = db.email_metadata.count_documents({"ai_classification": {"$exists": True, "$ne": None}})
with_summary = db.email_metadata.count_documents({"ai_summary": {"$exists": True, "$ne": None}})

print(f"Total emails: {total}")
print(f"With AI classification: {classified}")
print(f"With AI summary: {with_summary}")
print(f"Not classified: {total - classified}")

sample = db.email_metadata.find_one()
if sample:
    print(f"Sample fields: {list(sample.keys())}")
