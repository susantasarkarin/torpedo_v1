#!/usr/bin/env python3
"""Check CINT surveys DB stats - how many old docs exist."""
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv("backend/.env")
client = MongoClient(os.getenv("MONGO_URI"))
db = client["cint_research"]
col = db["cint_surveys"]

total = col.count_documents({})
active = col.count_documents({"is_active": True})
inactive = col.count_documents({"is_active": False})

cutoff3 = datetime.utcnow() - timedelta(days=3)
cutoff7 = datetime.utcnow() - timedelta(days=7)

old3 = col.count_documents({"received_at": {"$lt": cutoff3}})
old7 = col.count_documents({"received_at": {"$lt": cutoff7}})
no_date = col.count_documents({"received_at": {"$exists": False}})

# Check inactive + old (candidates for deletion)
old_inactive = col.count_documents({"is_active": False, "received_at": {"$lt": cutoff3}})

print(f"Total docs: {total}")
print(f"Active: {active}")
print(f"Inactive: {inactive}")
print(f"Older than 3 days: {old3}")
print(f"Older than 7 days: {old7}")
print(f"No received_at field: {no_date}")
print(f"Inactive + older than 3 days: {old_inactive}")

client.close()
