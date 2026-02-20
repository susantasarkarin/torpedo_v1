#!/usr/bin/env python3
"""Detailed analysis of a traffic record's waterfall flow."""
import sys
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from bson import ObjectId

load_dotenv("backend/.env")
c = MongoClient(os.getenv("MONGO_URI"))
db = c["traffic_flow_db"]
col = db["url_parameters"]

tid = sys.argv[1] if len(sys.argv) > 1 else "6997fc7a935cde88b1873e1c"
doc = col.find_one({"_id": ObjectId(tid)})

if not doc:
    print(f"Traffic ID {tid} not found")
    sys.exit(1)

print("=" * 60)
print(f"TRAFFIC ID: {tid}")
print("=" * 60)

print("\n--- ALLOCATION ---")
print(f"  status:                  {doc.get('status')}")
print(f"  surveySource:            {doc.get('surveySource')}")
print(f"  assignedSurveyId:        {doc.get('assignedSurveyId')}")
print(f"  allocationAttempts:      {doc.get('allocationAttempts')}")
print(f"  allocationFailureReason: {doc.get('allocationFailureReason', 'none')}")
print(f"  countryCode:             {doc.get('countryCode')}")
print(f"  vendorId:                {doc.get('vendorId')}")

print("\n--- CINT WATERFALL ---")
attempt_count = doc.get("cintAttemptCount", 0)
tried = doc.get("cintTriedSurveyIds", [])
candidates = doc.get("cintCandidateIds", [])
current_id = doc.get("currentCintSurveyId", "NOT SET")
current_link = doc.get("currentCintLink", "NOT SET")

print(f"  cintAttemptCount:        {attempt_count}")
print(f"  cintTriedSurveyIds:      {len(tried)} surveys tried")
for i, sid in enumerate(tried):
    print(f"    [{i+1}] {sid}")
print(f"  currentCintSurveyId:     {current_id}")
print(f"  currentCintLink:         {str(current_link)[:120]}")
print(f"  cintCandidateIds:        {len(candidates)} total candidates")
remaining = [c for c in candidates if c not in tried]
print(f"  remaining untried:       {len(remaining)}")

print("\n--- REDIRECT ---")
print(f"  redirectUrl: {doc.get('redirectUrl', 'NOT SET')}")
print(f"  outUrl:      {doc.get('outUrl', 'NOT SET')}")

print("\n--- TIMELINE ---")
print(f"  createdAt:   {doc.get('createdAt')}")
print(f"  assignedAt:  {doc.get('assignedAt')}")
print(f"  updatedAt:   {doc.get('updatedAt')}")

created = doc.get("createdAt")
updated = doc.get("updatedAt")
if created and updated:
    delta = (updated - created).total_seconds()
    print(f"  total duration: {delta:.1f}s")

print("\n--- PARAMS ---")
params = doc.get("params", {})
for k, v in params.items():
    print(f"  {k}: {v}")

# Check PM2 logs for this traffic ID
print("\n--- LOG SEARCH ---")
print(f"  Search PM2 logs with: pm2 logs campaign-backend --lines 5000 --nostream 2>&1 | grep '{tid}'")

c.close()
