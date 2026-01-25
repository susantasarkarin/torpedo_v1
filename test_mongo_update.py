#!/usr/bin/env python3
"""Test MongoDB update directly"""
from pymongo import MongoClient

db = MongoClient()["torpedo_gmail"]
coll = db["email_metadata"]

# Check counts before
before = coll.count_documents({"ai_category": {"$ne": None}})
print(f"Classified before: {before}")

# Find one unclassified email
email = coll.find_one({"ai_category": None})
if email:
    eid = email["_id"]
    print(f"Testing email ID: {eid}")
    
    # Try update
    result = coll.update_one(
        {"_id": eid}, 
        {"$set": {"ai_category": "test123", "ai_confidence": 0.99}}
    )
    print(f"Matched: {result.matched_count}, Modified: {result.modified_count}")
    
    # Check if it worked
    check = coll.find_one({"_id": eid})
    print(f"After update: ai_category = {check.get('ai_category')}")
    
    # Restore
    coll.update_one({"_id": eid}, {"$set": {"ai_category": None, "ai_confidence": None}})
    print("Restored to None")
    
    # Final count
    after = coll.count_documents({"ai_category": {"$ne": None}})
    print(f"Classified after restore: {after}")
else:
    print("No unclassified emails found")
