#!/usr/bin/env python3
"""
Batch update synthetic entry links with real Cint entry links.

This script:
1. Gets all synthetic entry links from the database
2. For each, calls the Cint API to get/create the real entry link
3. Updates the database with the correct LiveLink

Run this script on the server to fix all existing entry links.
"""

import asyncio
import httpx
import json
from pymongo import MongoClient
from datetime import datetime

# Cint credentials
SUPPLIER_CODE = "6777"
API_KEY = "C61C48A6-8154-4F9F-B616-8DFB66F452A7"
BASE_URL = "https://api.samplicio.us"

# Redirect URLs
API_BASE = "https://torpedo.cogentixresearch.com"
FRONTEND_URL = "https://surveyfieldwork.com"

# Connect to MongoDB
client = MongoClient()
db = client['cint_research']

async def get_or_create_entry_link(http_client: httpx.AsyncClient, survey_id: int):
    """Get existing or create new entry link from Cint API"""
    headers = {
        "Authorization": API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    # First try to get existing entry link
    get_url = f"{BASE_URL}/Supply/v1/SupplierLinks/BySurveyNumber/{survey_id}/{SUPPLIER_CODE}"
    try:
        response = await http_client.get(get_url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if "SupplierLink" in data and data["SupplierLink"].get("LiveLink"):
                return data["SupplierLink"]
    except Exception as e:
        print(f"  Error getting entry link: {e}")
    
    # If not found, create new entry link
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
            # Already exists - try GET again
            response = await http_client.get(get_url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if "SupplierLink" in data:
                    return data["SupplierLink"]
    except Exception as e:
        print(f"  Error creating entry link: {e}")
    
    return None

async def update_entry_links():
    """Update all synthetic entry links with real Cint links"""
    
    # Find all entry links that have torpedo URLs (synthetic)
    synthetic_links = list(db.cint_entry_links.find(
        {"live_link": {"$regex": "torpedo.cogentixresearch.com"}},
        {"survey_id": 1, "live_link": 1}
    ))
    
    print(f"Found {len(synthetic_links)} synthetic entry links to update")
    
    if not synthetic_links:
        print("No synthetic links found!")
        return
    
    updated = 0
    failed = 0
    
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        for i, link in enumerate(synthetic_links, 1):
            survey_id = link['survey_id']
            print(f"[{i}/{len(synthetic_links)}] Processing survey {survey_id}...", end=" ")
            
            try:
                result = await get_or_create_entry_link(http_client, survey_id)
                
                if result and result.get("LiveLink"):
                    # Update the database
                    db.cint_entry_links.update_one(
                        {"survey_id": survey_id},
                        {
                            "$set": {
                                "live_link": result["LiveLink"],
                                "test_link": result.get("TestLink"),
                                "supplier_link_type_code": result.get("SupplierLinkTypeCode", "OWS"),
                                "tracking_type_code": result.get("TrackingTypeCode", "NONE"),
                                "default_link": result.get("DefaultLink"),
                                "success_link": result.get("SuccessLink"),
                                "failure_link": result.get("FailureLink"),
                                "over_quota_link": result.get("OverQuotaLink"),
                                "quality_termination_link": result.get("QualityTerminationLink"),
                                "cpi": result.get("CPI"),
                                "rpi": result.get("RPI"),
                                "updated_at": datetime.utcnow(),
                                "synthetic": False
                            },
                            "$unset": {"_type": ""}
                        }
                    )
                    updated += 1
                    print(f"✅ Updated - {result['LiveLink'][:60]}...")
                else:
                    failed += 1
                    print("❌ Failed - No LiveLink returned")
                    
            except Exception as e:
                failed += 1
                print(f"❌ Error: {e}")
            
            # Rate limit - don't hit API too fast
            await asyncio.sleep(0.2)
    
    print(f"\n{'='*60}")
    print(f"Completed: {updated} updated, {failed} failed")
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(update_entry_links())
