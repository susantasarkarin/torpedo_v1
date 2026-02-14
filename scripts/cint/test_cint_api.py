#!/usr/bin/env python3
"""
Test Cint Entry Link Creation API

This script tests the actual Cint API to see what is returned when creating an entry link.
It will help diagnose why live_link is not being populated correctly.
"""

import asyncio
import httpx
import json
import os
from datetime import datetime

# Cint credentials
SUPPLIER_CODE = "6777"
API_KEY = "C61C48A6-8154-4F9F-B616-8DFB66F452A7"
BASE_URL = "https://api.samplicio.us"

# Redirect URLs
API_BASE = "https://torpedo.cogentixresearch.com"
FRONTEND_URL = "https://surveyfieldwork.com"

async def test_create_entry_link(survey_id: int):
    """Test creating an entry link for a specific survey"""
    
    print(f"\n{'='*60}")
    print(f"Testing Entry Link Creation for Survey {survey_id}")
    print(f"{'='*60}")
    
    url = f"{BASE_URL}/Supply/v1/SupplierLinks/Create/{survey_id}/{SUPPLIER_CODE}"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": API_KEY,
        "Accept": "application/json",
    }
    
    payload = {
        "SupplierLinkTypeCode": "OWS",
        "TrackingTypeCode": "NONE",
        "DefaultLink": f"{FRONTEND_URL}/survey",
        "SuccessLink": f"{API_BASE}/cint-response?status=complete&mid=[%MID%]&revenue=[%REVENUE%]",
        "FailureLink": f"{API_BASE}/cint-response?status=terminate&mid=[%MID%]",
        "OverQuotaLink": f"{API_BASE}/cint-response?status=quota_full&mid=[%MID%]",
        "QualityTerminationLink": f"{API_BASE}/cint-response?status=quality_terminate&mid=[%MID%]"
    }
    
    print(f"\nRequest URL: {url}")
    print(f"\nRequest Headers: {json.dumps(headers, indent=2)}")
    print(f"\nRequest Payload: {json.dumps(payload, indent=2)}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            
            print(f"\n--- Response ---")
            print(f"Status Code: {response.status_code}")
            print(f"Response Headers: {dict(response.headers)}")
            
            try:
                response_json = response.json()
                print(f"\nResponse JSON:\n{json.dumps(response_json, indent=2)}")
                
                # Check for SupplierLink key
                if "SupplierLink" in response_json:
                    link_data = response_json["SupplierLink"]
                    print(f"\n--- SupplierLink Analysis ---")
                    print(f"Keys: {list(link_data.keys())}")
                    
                    # Check for LiveLink
                    live_link = link_data.get("LiveLink") or link_data.get("live_link")
                    test_link = link_data.get("TestLink") or link_data.get("test_link")
                    
                    print(f"LiveLink: {live_link}")
                    print(f"TestLink: {test_link}")
                    
                    if live_link and "samplicio" in live_link.lower():
                        print(f"\n✅ SUCCESS: LiveLink points to Cint's survey entry URL!")
                    elif live_link:
                        print(f"\n⚠️ WARNING: LiveLink exists but doesn't contain 'samplicio'")
                    else:
                        print(f"\n❌ ERROR: LiveLink is missing or empty!")
                else:
                    print(f"\n❌ No 'SupplierLink' key in response!")
                    
            except json.JSONDecodeError:
                print(f"\nResponse Text (not JSON): {response.text}")
                
        except httpx.HTTPStatusError as e:
            print(f"\n❌ HTTP Error: {e.response.status_code}")
            print(f"Response: {e.response.text}")
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")

async def get_active_survey():
    """Get an active/live survey ID from the database"""
    from pymongo import MongoClient
    
    client = MongoClient()
    db = client['cint_research']
    
    # Find a live survey that doesn't have an entry link yet, or any live survey
    survey = db.cint_surveys.find_one(
        {"is_live": True},
        {"survey_id": 1, "survey_name": 1, "_id": 0},
        sort=[("created_at", -1)]
    )
    
    if survey:
        print(f"\nFound active survey: {survey['survey_id']} - {survey.get('survey_name', 'N/A')}")
        return survey['survey_id']
    
    return None

async def main():
    print("\n" + "="*60)
    print("CINT ENTRY LINK API TEST")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("="*60)
    
    # First, try to find an active survey
    survey_id = await get_active_survey()
    
    if survey_id:
        await test_create_entry_link(survey_id)
    else:
        print("\n❌ No active survey found to test with!")
        # Test with a known survey ID from the database
        print("\nTrying with survey_id from existing entry links...")
        from pymongo import MongoClient
        client = MongoClient()
        db = client['cint_research']
        entry = db.cint_entry_links.find_one({}, {"survey_id": 1})
        if entry:
            await test_create_entry_link(entry['survey_id'])

if __name__ == "__main__":
    asyncio.run(main())
