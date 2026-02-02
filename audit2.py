#!/usr/bin/env python3
from pymongo import MongoClient
import os
from dotenv import load_dotenv
load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))
sfwid = "69809ce2dd20421911277e08"

print("=" * 60)
print(f"BACKEND AUDIT FOR SFWID: {sfwid}")
print("=" * 60)

# List all databases and collections
print("\n1. DATABASE STRUCTURE:")
for db_name in client.list_database_names():
    if db_name in ["admin", "local", "config"]:
        continue
    db = client[db_name]
    colls = db.list_collection_names()
    print(f"   {db_name}: {colls}")

# Search for SFWID in all databases
print(f"\n2. SEARCHING FOR SFWID {sfwid}:")
found = False
for db_name in client.list_database_names():
    if db_name in ["admin", "local", "config"]:
        continue
    db = client[db_name]
    for coll_name in db.list_collection_names():
        try:
            # Try common field names
            for field in ["sfwid", "respondent_id", "subid_1", "_id", "rid"]:
                count = db[coll_name].count_documents({field: sfwid})
                if count > 0:
                    print(f"   FOUND in {db_name}.{coll_name} ({field}): {count}")
                    doc = db[coll_name].find_one({field: sfwid})
                    if doc:
                        for k, v in list(doc.items())[:10]:
                            if k not in ["raw_data", "responses"]:
                                print(f"      {k}: {str(v)[:100]}")
                    found = True
        except Exception as e:
            pass

if not found:
    print("   NOT FOUND in any collection")

# Check CPX surveys collection
print("\n3. CPX SURVEYS COLLECTION (sample):")
cpx_db = client["cpx_research"]
survey = cpx_db["cpx_surveys"].find_one({})
if survey:
    print(f"   Sample survey fields: {list(survey.keys())}")
    print(f"   Sample _id: {survey.get('_id')}")
    print(f"   Sample href: {str(survey.get('href', ''))[:80]}...")

# Check where allocations are stored
print("\n4. LOOKING FOR ALLOCATION COLLECTIONS:")
for db_name in client.list_database_names():
    if db_name in ["admin", "local", "config"]:
        continue
    db = client[db_name]
    for coll_name in db.list_collection_names():
        if "alloc" in coll_name.lower() or "entry" in coll_name.lower() or "assign" in coll_name.lower():
            count = db[coll_name].count_documents({})
            print(f"   {db_name}.{coll_name}: {count} docs")
            if count > 0:
                doc = db[coll_name].find_one({})
                print(f"      Fields: {list(doc.keys())[:10]}")

# Check recent activity
print("\n5. RECENT CPX SURVEY CLICKS (last 5):")
recent = list(cpx_db["cpx_surveys"].find({"last_clicked_at": {"$exists": True, "$ne": None}}).sort("last_clicked_at", -1).limit(5))
for s in recent:
    print(f"   {s.get('_id')}: clicks={s.get('click_count')}, last={s.get('last_clicked_at')}")

print("\n" + "=" * 60)
