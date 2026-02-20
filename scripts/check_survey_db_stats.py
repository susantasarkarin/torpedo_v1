#!/usr/bin/env python3
"""Check CPX + CINT survey DB stats."""
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv("backend/.env")
c = MongoClient(os.getenv("MONGO_URI"))

# CPX surveys
cpx = c["cpx_research"]["cpx_surveys"]
ct = cpx.count_documents({})
ca = cpx.count_documents({"is_active": True})
ci = cpx.count_documents({"is_active": False})

cut3 = datetime.utcnow() - timedelta(days=3)

co3_r = cpx.count_documents({"received_at": {"$lt": cut3}})
co3_l = cpx.count_documents({"last_updated": {"$lt": cut3}})
co3_c = cpx.count_documents({"created_at": {"$lt": cut3}})
nr = cpx.count_documents({"received_at": {"$exists": False}})
nl = cpx.count_documents({"last_updated": {"$exists": False}})

# CINT after cleanup
cint = c["cint_research"]["cint_surveys"]
cint_t = cint.count_documents({})
cint_a = cint.count_documents({"is_active": True})

print("=== CPX cpx_surveys ===")
print(f"Total: {ct}")
print(f"Active: {ca}")
print(f"Inactive: {ci}")
print(f"Older than 3d (received_at): {co3_r}")
print(f"Older than 3d (last_updated): {co3_l}")
print(f"Older than 3d (created_at): {co3_c}")
print(f"No received_at: {nr}")
print(f"No last_updated: {nl}")
print()
print("=== CINT cint_surveys (post-cleanup) ===")
print(f"Total: {cint_t}")
print(f"Active: {cint_a}")

# Sample CPX doc
sample = cpx.find_one()
if sample:
    print(f"\n=== Sample CPX doc keys ===")
    print(list(sample.keys()))

c.close()
