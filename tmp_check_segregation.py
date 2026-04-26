from pymongo import MongoClient
c = MongoClient("mongodb://localhost:27017/")
db = c["torpedo_gmail"]
col = db["email_metadata"]
total = col.count_documents({})
classified = col.count_documents({"ai_classification_status": {"$exists": True}})
pending = total - classified
print(f"Total emails: {total}")
print(f"Classified: {classified}")
print(f"Pending: {pending}")
if classified > 0:
    pipeline = [
        {"$match": {"ai_classification_status": {"$exists": True}}},
        {"$group": {"_id": "$ai_classification_status.segment", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    print("\nSegment breakdown:")
    for doc in col.aggregate(pipeline):
        print(f"  {doc['_id']}: {doc['count']}")
    methods = list(col.aggregate([
        {"$match": {"ai_classification_status": {"$exists": True}}},
        {"$group": {"_id": "$ai_classification_status.classification_method", "count": {"$sum": 1}}}
    ]))
    print(f"\nClassification methods: {methods}")
