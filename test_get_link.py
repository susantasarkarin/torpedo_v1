#!/usr/bin/env python3
"""
Test getting entry link from Cint API
"""

import asyncio
import httpx
import json

SUPPLIER_CODE = "6777"
API_KEY = "C61C48A6-8154-4F9F-B616-8DFB66F452A7"
BASE_URL = "https://api.samplicio.us"

async def get_entry_link(survey_id: int):
    """Get entry link for a survey"""
    url = f"{BASE_URL}/Supply/v1/SupplierLinks/BySurveyNumber/{survey_id}/{SUPPLIER_CODE}"
    
    headers = {
        "Authorization": API_KEY,
        "Accept": "application/json",
    }
    
    print(f"\n=== Getting Entry Link for Survey {survey_id} ===")
    print(f"URL: {url}")
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.json()

async def main():
    # Test with the survey we created an entry link for
    survey_id = 73867171
    result = await get_entry_link(survey_id)
    
    if "SupplierLink" in result:
        print("\n=== SupplierLink Data ===")
        link = result["SupplierLink"]
        print(f"LiveLink: {link.get('LiveLink', 'NOT FOUND')}")
        print(f"TestLink: {link.get('TestLink', 'NOT FOUND')}")

asyncio.run(main())
