#!/usr/bin/env python3
"""Check email count and classification status"""
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['torpedo_gmail']

# Total count
total = db.email_metadata.count_documents({})
classified = db.email_metadata.count_documents({"ai_category": {"$ne": None}})
unclassified = total - classified
print(f"Total emails: {total}")
print(f"Classified: {classified}")
print(f"Unclassified: {unclassified}")

# Check classification distribution
pipeline = [
    {"$group": {"_id": "$ai_category", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}}
]
results = list(db.email_metadata.aggregate(pipeline))
print("\nClassification Results:")
for r in results:
    print(f"  {r['_id']}: {r['count']}")
