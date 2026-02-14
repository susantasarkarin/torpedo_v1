#!/usr/bin/env python3
"""Check if active surveys exist in CINT API"""
import httpx
from pymongo import MongoClient

API_KEY = "C61C48A6-8154-4F9F-B616-8DFB66F452A7"
SUPPLIER_CODE = "6777"

c = MongoClient()
surveys = c.cint_research.cint_surveys

# Get sample of active surveys
active_sample = list(surveys.find({'is_active': True}, {'survey_id': 1}).limit(5))
print(f"Checking {len(active_sample)} sample active surveys...")

headers = {"Authorization": API_KEY}
valid_count = 0
invalid_count = 0

for s in active_sample:
    survey_id = s['survey_id']
    url = f"https://api.samplicio.us/Supply/v1/Surveys/BySurveyNumber/{survey_id}/{SUPPLIER_CODE}"
    try:
        resp = httpx.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            valid_count += 1
            print(f"  {survey_id}: VALID")
        else:
            invalid_count += 1
            print(f"  {survey_id}: INVALID ({resp.status_code})")
    except Exception as e:
        print(f"  {survey_id}: ERROR - {e}")

print(f"\nResults: {valid_count} valid, {invalid_count} invalid")
