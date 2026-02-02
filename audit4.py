#!/usr/bin/env python3
from pymongo import MongoClient
from bson import ObjectId
import os
from dotenv import load_dotenv
load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))
sfwid = "69809ce2dd20421911277e08"

print("=" * 70)
print(f"FULL FLOW AUDIT FOR SFWID: {sfwid}")
print("=" * 70)

traffic_db = client["traffic_flow_db"]

# 1. Check url_parameters (traffic records)
print("\n1. TRAFFIC RECORD (url_parameters):")
try:
    traffic = traffic_db["url_parameters"].find_one({"_id": ObjectId(sfwid)})
    if traffic:
        print("   FOUND:")
        for k, v in traffic.items():
            print(f"      {k}: {v}")
    else:
        print(f"   NOT FOUND by ObjectId")
        # Check by string
        traffic = traffic_db["url_parameters"].find_one({"_id": sfwid})
        if traffic:
            print("   FOUND by string _id:")
            for k, v in traffic.items():
                print(f"      {k}: {v}")
        else:
            print("   NOT FOUND at all")
except Exception as e:
    print(f"   ERROR: {e}")

# 2. Check cpx_callback_logs for this sfwid
print("\n2. CPX CALLBACK LOG (by decoded_sfwid):")
callbacks = list(traffic_db["cpx_callback_logs"].find({"decoded_sfwid": sfwid}))
if callbacks:
    for cb in callbacks:
        print("   CALLBACK:")
        for k, v in cb.items():
            print(f"      {k}: {str(v)[:100]}")
else:
    print("   NOT FOUND by decoded_sfwid")
    # Check by callback_url containing sfwid
    print("   Searching by callback_url...")
    for cb in traffic_db["cpx_callback_logs"].find().sort("_id", -1).limit(50):
        url = str(cb.get("callback_url", ""))
        if sfwid in url:
            print("   FOUND by callback_url:")
            for k, v in cb.items():
                print(f"      {k}: {str(v)[:100]}")
            break

# 3. Check survey_allocation.allocation_log
print("\n3. ALLOCATION LOG:")
alloc_db = client["survey_allocation"]
alloc = alloc_db["allocation_log"].find_one({"respondent_id": sfwid})
if alloc:
    print("   FOUND:")
    for k, v in alloc.items():
        print(f"      {k}: {v}")
else:
    print("   NOT FOUND")

# 4. Recent traffic records to see format
print("\n4. SAMPLE RECENT TRAFFIC RECORDS:")
for tr in traffic_db["url_parameters"].find().sort("_id", -1).limit(3):
    print(f"   _id: {tr.get('_id')}")
    print(f"      respondentId: {tr.get('respondentId')}")
    print(f"      vendorId: {tr.get('vendorId')}")
    print(f"      status: {tr.get('status')}")
    print()

# 5. Check if this is a CPX-generated SFWID vs a traffic record ID
print("\n5. ANALYSIS:")
# CPX allocation creates respondent_id in format like "69809c86dd20421911277df1"
# These are MongoDB ObjectIds from survey_allocation.allocation_log
# But they should also exist in url_parameters for callback to work

# Check if SFWID exists in allocation_log
alloc_check = alloc_db["allocation_log"].find_one({"respondent_id": sfwid})
if alloc_check:
    print(f"   ✅ SFWID {sfwid} EXISTS in allocation_log")
else:
    print(f"   ❌ SFWID {sfwid} NOT IN allocation_log")

# Check if SFWID exists in url_parameters
try:
    traffic_check = traffic_db["url_parameters"].find_one({"_id": ObjectId(sfwid)})
    if traffic_check:
        print(f"   ✅ SFWID {sfwid} EXISTS in url_parameters")
    else:
        print(f"   ❌ SFWID {sfwid} NOT IN url_parameters (as _id)")
except:
    print(f"   ❌ SFWID {sfwid} is not a valid ObjectId for url_parameters")

print("\n" + "=" * 70)
