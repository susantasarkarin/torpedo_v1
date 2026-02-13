#!/usr/bin/env python3
"""
Test CINT entry link creation via the service.
"""
import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from pymongo import MongoClient
from app.services.cint_service import CintService
from app.models.cint import SupplierLinkCreate
from dotenv import load_dotenv

load_dotenv()

async def test_create_entry_link():
    print("=== Testing Entry Link Creation via CintService ===\n")
    
    # Get MongoDB connection
    client = MongoClient()
    db = client['cint_research']
    
    # Get a recent survey
    recent_survey = db.cint_surveys.find_one(
        {"is_live": True},
        sort=[("updated_at", -1)]
    )
    
    if not recent_survey:
        print("No live surveys found!")
        return
    
    survey_id = recent_survey['survey_id']
    print(f"Testing with survey_id: {survey_id}")
    
    # Initialize CintService
    cint_service = CintService(
        api_key=os.getenv("CINT_API_KEY", "C61C48A6-8154-4F9F-B616-8DFB66F452A7"),
        supplier_code=os.getenv("CINT_SUPPLIER_CODE", "6777"),
        environment="production",
        cint_surveys_collection=db.cint_surveys,
        cint_entry_links_collection=db.cint_entry_links,
        cint_settings_collection=db.cint_settings,
    )
    
    # Check if entry link already exists
    existing = await cint_service.get_entry_link_by_survey_id(survey_id)
    if existing:
        print(f"Entry link already exists for survey {survey_id}")
        print(f"  live_link: {existing.live_link}")
        return
    
    # Create entry link
    print(f"Creating entry link for survey {survey_id}...")
    result = await cint_service._auto_create_entry_link(survey_id)
    
    print(f"\nResult: {result}")
    
    if result.get("success"):
        print("SUCCESS!")
        link = result.get("link")
        if link:
            print(f"  live_link: {link.live_link}")
            print(f"  test_link: {link.test_link}")
    else:
        print(f"FAILED: {result.get('error')}")
    
    # Check MongoDB
    print("\nChecking MongoDB...")
    stored = db.cint_entry_links.find_one({"survey_id": survey_id})
    if stored:
        print(f"Entry link stored in MongoDB!")
        print(f"  live_link: {stored.get('live_link')}")
    else:
        print("Entry link NOT stored in MongoDB")
    
    client.close()
    await cint_service.close()

if __name__ == "__main__":
    asyncio.run(test_create_entry_link())
