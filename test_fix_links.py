#!/usr/bin/env python3
"""
Test updating just 5 synthetic entry links with real Cint entry links.
"""

import asyncio
import httpx
from pymongo import MongoClient
from datetime import datetime

SUPPLIER_CODE = "6777"
API_KEY = "C61C48A6-8154-4F9F-B616-8DFB66F452A7"
BASE_URL = "https://api.samplicio.us"
API_BASE = "https://torpedo.cogentixresearch.com"
FRONTEND_URL = "https://surveyfieldwork.com"

client = MongoClient()
db = client['cint_research']

async def get_or_create_entry_link(http_client, survey_id):
    headers = {
        "Authorization": API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    get_url = f"{BASE_URL}/Supply/v1/SupplierLinks/BySurveyNumber/{survey_id}/{SUPPLIER_CODE}"
    try:
        response = await http_client.get(get_url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if "SupplierLink" in data and data["SupplierLink"].get("LiveLink"):
                return data["SupplierLink"]
    except Exception as e:
        print(f"  Error getting: {e}")
    
    create_url = f"{BASE_URL}/Supply/v1/SupplierLinks/Create/{survey_id}/{SUPPLIER_CODE}"
    payload = {
        "SupplierLinkTypeCode": "OWS",
        "TrackingTypeCode": "NONE",
        "DefaultLink": f"{FRONTEND_URL}/survey",
        "SuccessLink": f"{API_BASE}/cint-response?status=complete&mid=[%MID%]&revenue=[%REVENUE%]",
        "FailureLink": f"{API_BASE}/cint-response?status=terminate&mid=[%MID%]",
        "OverQuotaLink": f"{API_BASE}/cint-response?status=quota_full&mid=[%MID%]",
        "QualityTerminationLink": f"{API_BASE}/cint-response?status=quality_terminate&mid=[%MID%]"
    }
    
    try:
        response = await http_client.post(create_url, json=payload, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if "SupplierLink" in data:
                return data["SupplierLink"]
        elif response.status_code == 409:
            response = await http_client.get(get_url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if "SupplierLink" in data:
                    return data["SupplierLink"]
    except Exception as e:
        print(f"  Error creating: {e}")
    
    return None

async def test_update():
    synthetic = list(db.cint_entry_links.find(
        {"live_link": {"$regex": "torpedo.cogentixresearch.com"}},
        {"survey_id": 1, "live_link": 1}
    ).limit(5))
    
    print(f"Testing with {len(synthetic)} synthetic links")
    
    updated = 0
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        for link in synthetic:
            survey_id = link['survey_id']
            print(f"\nSurvey {survey_id}:")
            print(f"  Old: {link['live_link'][:60]}...")
            
            result = await get_or_create_entry_link(http_client, survey_id)
            
            if result and result.get("LiveLink"):
                db.cint_entry_links.update_one(
                    {"survey_id": survey_id},
                    {
                        "$set": {
                            "live_link": result["LiveLink"],
                            "test_link": result.get("TestLink"),
                            "cpi": result.get("CPI"),
                            "rpi": result.get("RPI"),
                            "updated_at": datetime.utcnow(),
                            "synthetic": False
                        }
                    }
                )
                updated += 1
                print(f"  New: {result['LiveLink'][:60]}...")
            else:
                print("  ❌ Failed")
            
            await asyncio.sleep(0.2)
    
    print(f"\n✅ Updated {updated}/5 links")

if __name__ == "__main__":
    asyncio.run(test_update())
