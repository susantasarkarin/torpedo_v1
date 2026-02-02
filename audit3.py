#!/usr/bin/env python3
from pymongo import MongoClient
import os
from dotenv import load_dotenv
load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))
sfwid = "69809ce2dd20421911277e08"

print("=" * 60)
print(f"DEEP AUDIT FOR SFWID: {sfwid}")
print("=" * 60)

# 1. Check survey_allocation.allocation_log
print("\n1. SURVEY ALLOCATION LOG:")
alloc_db = client["survey_allocation"]
alloc = alloc_db["allocation_log"].find_one({"respondent_id": sfwid})
if not alloc:
    alloc = alloc_db["allocation_log"].find_one({"rid": sfwid})
if alloc:
    print("   FOUND:")
    for k, v in alloc.items():
        print(f"      {k}: {v}")
else:
    print("   NOT FOUND - checking recent allocations:")
    recent = list(alloc_db["allocation_log"].find().sort("timestamp", -1).limit(10))
    for r in recent:
        print(f"      {r.get('respondent_id')} -> {r.get('survey_id')} at {r.get('timestamp')}")

# 2. Check traffic_flow_db
print("\n2. TRAFFIC FLOW DB:")
traffic_db = client["traffic_flow_db"]
for coll_name in traffic_db.list_collection_names():
    print(f"   Collection: {coll_name}")
    # Try to find sfwid
    for field in ["sfwid", "respondent_id", "subid_1", "rid"]:
        doc = traffic_db[coll_name].find_one({field: sfwid})
        if doc:
            print(f"   FOUND in {coll_name} by {field}:")
            for k, v in list(doc.items())[:15]:
                print(f"      {k}: {str(v)[:100]}")

# 3. Check recent CPX callbacks
print("\n3. RECENT CPX CALLBACKS (cpx_callback_logs):")
callbacks = list(traffic_db["cpx_callback_logs"].find().sort("_id", -1).limit(10))
if callbacks:
    for cb in callbacks:
        print(f"   {cb.get('sfwid', 'N/A')} - status: {cb.get('status')} - {cb.get('created_at', cb.get('_id'))}")
else:
    print("   No callbacks found")

# 4. Check cpx_postback_logs
print("\n4. RECENT CPX POSTBACKS (cpx_postback_logs):")
postbacks = list(traffic_db["cpx_postback_logs"].find().sort("_id", -1).limit(10))
if postbacks:
    for pb in postbacks:
        print(f"   {pb.get('sfwid', 'N/A')} - status: {pb.get('status')} - msg: {pb.get('msg', 'N/A')[:50]}")
else:
    print("   No postbacks found")

# 5. Check survey_transactions
print("\n5. RECENT SURVEY TRANSACTIONS:")
txns = list(traffic_db["survey_transactions"].find().sort("_id", -1).limit(10))
if txns:
    for tx in txns:
        print(f"   {tx.get('respondent_id', tx.get('sfwid', 'N/A'))} - status: {tx.get('status')} - survey: {tx.get('survey_id')}")
else:
    print("   No transactions found")

# 6. Check what the cpx-response endpoint is doing
print("\n6. SEARCHING BY PARTIAL MATCH (last part of sfwid):")
partial = sfwid[-8:]  # Last 8 chars
for db_name in ["traffic_flow_db", "survey_allocation", "cpx_research"]:
    db = client[db_name]
    for coll_name in db.list_collection_names():
        try:
            docs = list(db[coll_name].find().limit(1000))
            for doc in docs:
                doc_str = str(doc)
                if partial in doc_str or sfwid in doc_str:
                    print(f"   FOUND in {db_name}.{coll_name}: {doc.get('_id')}")
                    for k, v in list(doc.items())[:8]:
                        print(f"      {k}: {str(v)[:80]}")
                    break
        except:
            pass

print("\n" + "=" * 60)
