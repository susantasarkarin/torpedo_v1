#!/usr/bin/env python3
"""Check a traffic record by ID"""
import os, sys, json
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

traffic_id = sys.argv[1] if len(sys.argv) > 1 else "6997da99b4c2704f491197d9"

client = MongoClient(os.getenv("MONGO_URI"))
db = client["traffic_flow_db"]
col = db["url_parameters"]

doc = col.find_one({"_id": ObjectId(traffic_id)})
if not doc:
    print("NOT FOUND")
    sys.exit(1)

doc["_id"] = str(doc["_id"])

fields = [
    "status", "surveySource", "assignedSurveyId", "redirectUrl",
    "cintCandidateIds", "cintAttemptCount", "cintTriedSurveyIds",
    "currentCintSurveyId", "currentCintLink", "countryCode",
    "vendorId", "createdAt", "updatedAt",
]

for f in fields:
    val = doc.get(f, "--NOT SET--")
    if isinstance(val, list) and len(val) > 10:
        print(f"{f}: [{len(val)} items] first5: {val[:5]}")
    elif isinstance(val, datetime):
        print(f"{f}: {val.isoformat()}")
    else:
        print(f"{f}: {val}")

print()
print("ALL KEYS:", sorted(doc.keys()))
