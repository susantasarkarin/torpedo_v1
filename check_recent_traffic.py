#!/usr/bin/env python3
"""Check recent traffic after new changes."""
from pymongo import MongoClient
from datetime import datetime, timezone, timedelta

client = MongoClient("mongodb://localhost:27017/")

# Check recent traffic (since 04:41 UTC - after deploy)
print("=" * 60)
print("Recent traffic (since 04:41 UTC - after new fix):")
print("=" * 60)
traffic_db = client["traffic_flow_db"]["url_parameters"]
cutoff = datetime(2026, 2, 18, 4, 41, 0, tzinfo=timezone.utc)
recent = list(traffic_db.find({"createdAt": {"$gte": cutoff}}).sort("createdAt", -1).limit(15))
print(f"Records: {len(recent)}")
for r in recent:
    status = r.get("status", "?")
    source = r.get("surveySource", "N/A")
    country = r.get("countryCode", "?")
    survey = r.get("assignedSurveyId", "none")
    reason = r.get("allocationFailureReason") or r.get("terminationReason") or ""
    attempts = r.get("allocationAttempts", [])
    print(f"  {r.get('createdAt')} | {country} | {status} | {source} | survey={survey} | attempts={len(attempts)}")
    if reason:
        print(f"    -> {reason[:80]}")

# Status breakdown
print()
print("=" * 60)
print("Status breakdown (last 30 minutes):")
print("=" * 60)
cutoff2 = datetime.utcnow() - timedelta(minutes=30)
pipeline = [
    {"$match": {"createdAt": {"$gte": cutoff2}}},
    {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}}
]
for doc in traffic_db.aggregate(pipeline):
    print(f"  {doc['_id']}: {doc['count']}")
