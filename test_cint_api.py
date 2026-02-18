#!/usr/bin/env python3
"""Test CINT APIs to understand access."""
import os
import httpx

# Load credentials
api_key = "C61C48A6-8154-4F9F-B616-8DFB66F452A7"
supplier_code = "6777"

headers = {
    "Authorization": api_key,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

print("Testing CINT API endpoints...")
print(f"Supplier Code: {supplier_code}")
print(f"API Key: {api_key[:10]}...")

with httpx.Client(timeout=30.0) as client:
    # Test 1: Get allocated surveys for our supplier
    print("\n" + "="*60)
    print("1. Testing /supply/v1/surveys/allocated endpoint:")
    print("="*60)
    resp1 = client.get(
        f"https://api.samplicio.us/supply/v1/surveys/allocated/{supplier_code}",
        headers=headers,
    )
    print(f"Status: {resp1.status_code}")
    if resp1.status_code == 200:
        data = resp1.json()
        surveys = data.get("surveys", data.get("Surveys", []))
        print(f"Allocated surveys: {len(surveys)}")
        if surveys:
            print("Sample (first 3):")
            for s in surveys[:3]:
                print(f"  - ID: {s.get('SurveyId', s.get('survey_id'))}, Country: {s.get('CountryLanguage', s.get('country_language'))}")
    else:
        print(f"Response: {resp1.text[:500]}")

    # Test 2: Get available surveys via offerwall
    print("\n" + "="*60)
    print("2. Testing /supply/v1/surveys/AllOfferwall endpoint:")
    print("="*60)
    resp2 = client.get(
        f"https://api.samplicio.us/supply/v1/surveys/AllOfferwall/{supplier_code}",
        headers=headers,
    )
    print(f"Status: {resp2.status_code}")
    if resp2.status_code == 200:
        data = resp2.json()
        surveys = data.get("surveys", data.get("Surveys", data if isinstance(data, list) else []))
        print(f"Offerwall surveys: {len(surveys)}")
        if surveys:
            print("Sample (first 3):")
            for s in surveys[:3]:
                print(f"  - ID: {s.get('SurveyId', s.get('survey_id'))}, Country: {s.get('CountryLanguageID', s.get('country_language'))}")
    else:
        print(f"Response: {resp2.text[:500]}")
    
    # Test 3: Check supplier link (different from entry link)
    print("\n" + "="*60)
    print("3. Testing /supply/v1/SupplierLinks endpoint:")
    print("="*60)
    resp3 = client.get(
        f"https://api.samplicio.us/supply/v1/SupplierLinks/{supplier_code}",
        headers=headers,
    )
    print(f"Status: {resp3.status_code}")
    print(f"Response: {resp3.text[:500]}")
