#!/usr/bin/env python3
"""Check CPX postback and redirect activity"""
from pymongo import MongoClient
import os
from datetime import datetime, timedelta

# Connect to MongoDB
mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
client = MongoClient(mongo_uri)
db = client["traffic_flow_db"]

print("=" * 60)
print("CPX ACTIVITY CHECK")
print("=" * 60)

# Check CPX Postbacks (S2S)
print("\n📥 CPX POSTBACK LOGS (S2S - Server to Server)")
print("-" * 60)
postback_count = db["cpx_postback_logs"].count_documents({})
print(f"Total postbacks received: {postback_count}")

if postback_count > 0:
    print("\nLast 5 postbacks:")
    postbacks = db["cpx_postback_logs"].find().sort("timestamp", -1).limit(5)
    for p in postbacks:
        print(f"  {p.get('timestamp')} | sfwid: {p.get('subid')} | status: {p.get('cpx_status')} | success: {p.get('success')}")
else:
    print("  No postbacks received yet")

# Check CPX Callbacks (User Redirects)
print("\n🔄 CPX CALLBACK LOGS (User Redirects)")
print("-" * 60)
callback_count = db["cpx_callback_logs"].count_documents({})
print(f"Total callbacks received: {callback_count}")

if callback_count > 0:
    print("\nLast 5 callbacks:")
    callbacks = db["cpx_callback_logs"].find().sort("timestamp", -1).limit(5)
    for c in callbacks:
        print(f"  {c.get('timestamp')} | sfwid: {c.get('sfwid')} | key: {c.get('callback_key')}")
else:
    print("  No callbacks received yet")

# Check recent traffic records with CPX surveys
print("\n🎯 RECENT CPX TRAFFIC ASSIGNMENTS")
print("-" * 60)
last_24h = datetime.utcnow() - timedelta(hours=24)
recent_cpx = db["url_parameters"].find({
    "surveyId": {"$exists": True},
    "createdAt": {"$gte": last_24h}
}).sort("createdAt", -1).limit(5)

recent_count = 0
for traffic in recent_cpx:
    recent_count += 1
    print(f"  {traffic.get('createdAt')} | sfwid: {traffic['_id']} | vendor: {traffic.get('vendorId')}")

if recent_count == 0:
    print("  No CPX traffic assigned in last 24 hours")

print("\n" + "=" * 60)
