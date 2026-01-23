#!/usr/bin/env python3
"""Check leads by source in the database"""
from pymongo import MongoClient
db = MongoClient()["email_automation"]

print("=== Leads by Source (leads_raw) ===")
for r in db["leads_raw"].aggregate([{"$group": {"_id": "$source", "count": {"$sum": 1}}}]):
    src = r["_id"]
    cnt = r["count"]
    print(f"{src}: {cnt}")

print()
print("=== Leads by Source (leads_enriched) ===")
for r in db["leads_enriched"].aggregate([{"$group": {"_id": "$source", "count": {"$sum": 1}}}]):
    src = r["_id"]
    cnt = r["count"]
    print(f"{src}: {cnt}")

# Check Gmail sources specifically
print()
print("=== Gmail-related sources in enriched ===")
gmail_sources = ["gmail", "gmail_workspace", "email_sync", "email_import", "email_classification", "gmail_api", "gmail_archive"]
for s in gmail_sources:
    count = db["leads_enriched"].count_documents({"source": s})
    if count > 0:
        print(f"{s}: {count}")
        
# Sample Gmail lead if exists
print()
print("=== Sample lead from Gmail sources (if any) ===")
sample = db["leads_enriched"].find_one({"source": {"$in": gmail_sources}})
if sample:
    name = sample.get("name")
    source = sample.get("source")
    email = sample.get("email")
    print(f"Name: {name}, Source: {source}, Email: {email}")
else:
    print("No Gmail leads found in enriched collection")
