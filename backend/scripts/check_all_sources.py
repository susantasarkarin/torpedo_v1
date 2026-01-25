#!/usr/bin/env python3
"""Check all lead sources in the database"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017/'))
db = client['email_automation']

print("LEADS_RAW sources:")
raw_sources = list(db.leads_raw.aggregate([
    {"$group": {"_id": "$source", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}}
]))
for s in raw_sources:
    print(f"  {s['_id']}: {s['count']}")

print()
print("LEADS_ENRICHED sources:")
enriched_sources = list(db.leads_enriched.aggregate([
    {"$group": {"_id": "$source", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}}
]))
for s in enriched_sources:
    print(f"  {s['_id']}: {s['count']}")

print()
print(f"Total leads_raw: {db.leads_raw.count_documents({})}")
print(f"Total leads_enriched: {db.leads_enriched.count_documents({})}")

# Check for gmail in enriched with missing fields
print()
print("Checking leads_enriched with 'gmail' source and missing seniority:")
gmail_enriched = db.leads_enriched.count_documents({
    "source": "gmail",
    "$or": [
        {"seniority_level": {"$exists": False}},
        {"seniority_level": None},
        {"seniority_level": ""}
    ]
})
print(f"  Gmail leads missing seniority_level: {gmail_enriched}")

# Sample a lead with gmail source
sample = db.leads_enriched.find_one({"source": "gmail"})
if sample:
    print()
    print("Sample gmail lead from leads_enriched:")
    for k in ["email", "name", "source", "seniority_level", "department", "persona", "title", "company_name"]:
        print(f"  {k}: {sample.get(k)}")
