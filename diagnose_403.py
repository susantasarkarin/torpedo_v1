#!/usr/bin/env python3
"""
Diagnose 403 error on Cint entry links.

The error URL was:
rx.samplicio.us/error/?SID=3746c4d6-ee5c-4093-af09-6e5b1fc28996&PID=698ade67634effbd7abe46d68&lang=en-us

This script:
1. Checks the database for entry links with the SID
2. Checks the Cint API for the entry link status
3. Validates the entry link configuration
"""

import httpx
from pymongo import MongoClient
from datetime import datetime
import os

# Cint API credentials
SUPPLIER_CODE = "6777"
API_KEY = "C61C48A6-8154-4F9F-B616-8DFB66F452A7"
BASE_URL = "https://api.samplicio.us"

# Connect to MongoDB
client = MongoClient()
db = client['cint_research']
traffic_db = client['traffic_flow_db']

print("=" * 60)
print("CINT 403 ERROR DIAGNOSIS")
print("=" * 60)

# The SID from the error URL (this is the session ID from Cint, not survey number)
error_sid = "3746c4d6-ee5c-4093-af09-6e5b1fc28996"
error_pid = "698ade67634effbd7abe46d68"

print(f"\nError SID: {error_sid}")
print(f"Error PID: {error_pid}")

# 1. Check database for the PID (traffic record)
print("\n" + "=" * 60)
print("1. CHECKING DATABASE FOR PID")
print("=" * 60)

from bson import ObjectId
try:
    # PID might be ObjectId or string
    traffic_record = traffic_db.url_parameters.find_one({"_id": ObjectId(error_pid[:24])})
    if traffic_record:
        print(f"✅ Found traffic record for PID")
        print(f"   Status: {traffic_record.get('status')}")
        print(f"   Survey ID: {traffic_record.get('assignedSurveyId')}")
        print(f"   Survey Source: {traffic_record.get('surveySource')}")
        redirect = traffic_record.get('redirectUrl', '')
        print(f"   Redirect URL: {redirect[:150]}...")
    else:
        print(f"❌ No traffic record found with PID prefix")
except Exception as e:
    print(f"⚠️ Error checking traffic record: {e}")

# 2. Check entry links collection
print("\n" + "=" * 60)
print("2. CHECKING ENTRY LINKS IN DATABASE")
print("=" * 60)

entry_links = list(db.cint_entry_links.find().limit(5))
print(f"Total entry links in DB: {db.cint_entry_links.count_documents({})}")

if entry_links:
    print("\nSample entry links:")
    for link in entry_links:
        print(f"  Survey {link.get('survey_id')}: {link.get('live_link', 'N/A')[:80]}...")
else:
    print("❌ NO entry links in database!")

# 3. Check surveys in database
print("\n" + "=" * 60)
print("3. CHECKING SURVEYS IN DATABASE")
print("=" * 60)

total_surveys = db.cint_surveys.count_documents({})
live_surveys = db.cint_surveys.count_documents({'is_live': True})
active_surveys = db.cint_surveys.count_documents({'is_active_in_pool': True})

print(f"Total surveys: {total_surveys}")
print(f"Live surveys: {live_surveys}")
print(f"Active in pool: {active_surveys}")

# Get some sample surveys
sample_surveys = list(db.cint_surveys.find({'is_active_in_pool': True}).limit(3))
print("\nSample active surveys:")
for s in sample_surveys:
    print(f"  Survey {s.get('survey_id')}: live_link={s.get('live_link')}")

# 4. Test Cint API - Get a live survey and check its entry link
print("\n" + "=" * 60)
print("4. TESTING CINT API ENTRY LINKS")
print("=" * 60)

headers = {
    "Authorization": API_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# Get a sample survey from the API
try:
    response = httpx.get(
        f"{BASE_URL}/Supply/v1/Surveys/AllOfferwall/{SUPPLIER_CODE}",
        headers=headers,
        timeout=30
    )
    if response.status_code == 200:
        data = response.json()
        surveys = data.get("Surveys", [])
        print(f"✅ API returned {len(surveys)} surveys")
        
        if surveys:
            # Take first 3 US surveys (CountryLanguageID 9)
            us_surveys = [s for s in surveys if s.get("CountryLanguageID") == 9][:3]
            
            for survey in us_surveys:
                survey_id = survey.get("SurveyNumber")
                print(f"\nChecking entry link for survey {survey_id}...")
                
                # Get entry link
                link_url = f"{BASE_URL}/Supply/v1/SupplierLinks/BySurveyNumber/{survey_id}/{SUPPLIER_CODE}"
                link_resp = httpx.get(link_url, headers=headers, timeout=10)
                
                if link_resp.status_code == 200:
                    link_data = link_resp.json()
                    supplier_link = link_data.get("SupplierLink", {})
                    live_link = supplier_link.get("LiveLink")
                    
                    if live_link:
                        print(f"  ✅ Found LiveLink: {live_link}")
                        print(f"  SupplierLinkTypeCode: {supplier_link.get('SupplierLinkTypeCode')}")
                        print(f"  SuccessLink: {supplier_link.get('SuccessLink', 'N/A')[:80]}...")
                        print(f"  FailureLink: {supplier_link.get('FailureLink', 'N/A')[:80]}...")
                    else:
                        print(f"  ⚠️ Entry link exists but no LiveLink")
                elif link_resp.status_code == 404:
                    print(f"  ❌ No entry link exists for survey {survey_id}")
                    
                    # Try to create one
                    print(f"  📝 Attempting to create entry link...")
                    create_url = f"{BASE_URL}/Supply/v1/SupplierLinks/Create/{survey_id}/{SUPPLIER_CODE}"
                    create_payload = {
                        "SupplierLinkTypeCode": "OWS",
                        "TrackingTypeCode": "NONE",
                        "DefaultLink": "https://surveyfieldwork.com/survey",
                        "SuccessLink": "https://torpedo.cogentixresearch.com/cint-response?status=complete&pid=[%PID%]&mid=[%MID%]&revenue=[%REVENUE%]",
                        "FailureLink": "https://torpedo.cogentixresearch.com/cint-response?status=terminate&pid=[%PID%]&mid=[%MID%]",
                        "OverQuotaLink": "https://torpedo.cogentixresearch.com/cint-response?status=quota_full&pid=[%PID%]&mid=[%MID%]",
                        "QualityTerminationLink": "https://torpedo.cogentixresearch.com/cint-response?status=quality_terminate&pid=[%PID%]&mid=[%MID%]"
                    }
                    create_resp = httpx.post(create_url, json=create_payload, headers=headers, timeout=15)
                    print(f"  Create response: {create_resp.status_code}")
                    if create_resp.status_code in [200, 201]:
                        print(f"  ✅ Entry link created!")
                        created_data = create_resp.json()
                        new_link = created_data.get("SupplierLink", {}).get("LiveLink")
                        print(f"  LiveLink: {new_link}")
                    else:
                        print(f"  ⚠️ Create failed: {create_resp.text[:200]}")
                else:
                    print(f"  ⚠️ API error: {link_resp.status_code}")
    else:
        print(f"⚠️ API error: {response.status_code}")
except Exception as e:
    print(f"❌ API error: {e}")

# 5. Check the redirect URL format
print("\n" + "=" * 60)
print("5. REDIRECT URL FORMAT CHECK")
print("=" * 60)

# The correct LiveLink format should be:
# https://www.samplicio.us/s/default.aspx?SID=<session-uuid>&PID=
# OR with rx domain:
# https://rx.samplicio.us/s/default.aspx?SID=<session-uuid>&PID=

print("""
The 403 error happens when:
1. Entry link doesn't exist or is invalid
2. Survey is closed/paused/over quota  
3. Redirect URLs in entry link config are malformed
4. The [%PID%] placeholder is not properly replaced

Expected LiveLink format:
  https://www.samplicio.us/s/default.aspx?SID=<uuid>&PID=

If PID is being appended, final URL should be:
  https://www.samplicio.us/s/default.aspx?SID=<uuid>&PID=<traffic_id>
""")

print("\n" + "=" * 60)
print("DIAGNOSIS COMPLETE")
print("=" * 60)
