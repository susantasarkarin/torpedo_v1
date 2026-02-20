#!/usr/bin/env python3
"""Check CINT survey counts in the database by country"""
from pymongo import MongoClient
import os

client = MongoClient(os.environ.get("MONGO_URI", "mongodb://localhost:27017"))
cint_db = client["cint_research"]
cint_surveys = cint_db["cint_surveys"]

# Check counts by country with ONLY is_active (ignoring is_active_in_pool)
print("=== Surveys with is_active=True (ignoring is_active_in_pool) ===")
countries = ["gb", "us", "in"]
for country in countries:
    query = {
        "is_active": True,
        "country_language": {"$regex": f"_{country}$", "$options": "i"}
    }
    count = cint_surveys.count_documents(query)
    print(f"{country.upper()}: {count} surveys")

print("\n=== Surveys with is_active_in_pool=True ===")
for country in countries:
    query = {
        "is_active_in_pool": True,
        "country_language": {"$regex": f"_{country}$", "$options": "i"}
    }
    count = cint_surveys.count_documents(query)
    print(f"{country.upper()}: {count} surveys")

# Total active count
print("\n=== Distribution of is_active_in_pool values ===")
pool_true = cint_surveys.count_documents({"is_active_in_pool": True})
pool_false = cint_surveys.count_documents({"is_active_in_pool": False})
pool_missing = cint_surveys.count_documents({"is_active_in_pool": {"$exists": False}})
print(f"is_active_in_pool=True: {pool_true}")
print(f"is_active_in_pool=False: {pool_false}")
print(f"is_active_in_pool missing: {pool_missing}")

# All surveys count
all_count = cint_surveys.count_documents({})
print(f"\nTOTAL all surveys: {all_count}")
