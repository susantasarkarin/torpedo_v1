#!/usr/bin/env python3
"""Check classification status"""
from pymongo import MongoClient

db = MongoClient()["torpedo_gmail"]
coll = db["email_metadata"]

total = coll.count_documents({})
classified = coll.count_documents({"ai_category": {"$ne": None}})
null_category = coll.count_documents({"ai_category": None})
missing_field = coll.count_documents({"ai_category": {"$exists": False}})

print(f"Total emails: {total:,}")
print(f"With ai_category set (not None): {classified:,}")
print(f"ai_category = None: {null_category:,}")
print(f"ai_category field missing: {missing_field:,}")

# Sample recent classifications
print("\n--- Recent Classifications ---")
recent = coll.find(
    {"ai_category": {"$ne": None}},
    {"subject": 1, "ai_category": 1, "ai_confidence": 1, "classified_at": 1}
).sort("classified_at", -1).limit(5)

for doc in recent:
    print(f"- {doc.get('ai_category', 'N/A')} ({doc.get('ai_confidence', 'N/A'):.2f}): {str(doc.get('subject', 'N/A'))[:50]}")

# Distribution by category
print("\n--- Category Distribution ---")
pipeline = [
    {"$match": {"ai_category": {"$ne": None}}},
    {"$group": {"_id": "$ai_category", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
    {"$limit": 10}
]
for doc in coll.aggregate(pipeline):
    print(f"  {doc['_id']}: {doc['count']:,}")
