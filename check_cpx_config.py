#!/usr/bin/env python3
from pymongo import MongoClient
import os
from dotenv import load_dotenv
load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))
settings = client["torpedo_settings"]["app_settings"].find_one({"_id": "app_config"})

print("=" * 60)
print("CPX CONFIGURATION CHECK")
print("=" * 60)

if settings:
    print("From database (torpedo_settings.app_settings._id='app_config'):")
    print(f"  cpx_app_id: {settings.get('cpx_app_id', 'NOT SET')}")
    print(f"  cpx_ext_user_id: {settings.get('cpx_ext_user_id', 'NOT SET')}")
    print(f"  cpx_secure_hash_key: {'SET (' + settings.get('cpx_secure_hash_key', '')[:10] + '...)' if settings.get('cpx_secure_hash_key') else 'NOT SET'}")
else:
    print("No app_config found in database")

print("\nFrom environment variables:")
print(f"  CPX_APP_ID: {os.getenv('CPX_APP_ID', 'NOT SET')}")
print(f"  CPX_EXT_USER_ID: {os.getenv('CPX_EXT_USER_ID', 'NOT SET')}")
print(f"  CPX_SECURE_HASH_KEY: {'SET' if os.getenv('CPX_SECURE_HASH_KEY') else 'NOT SET'}")

print("\n" + "=" * 60)
print("ISSUE EXPLANATION:")
print("=" * 60)
print("""
The ext_user_id '164508284' or 'PANEL_88921' appears in two flows:

1. REFRESH FLOW (runs every 1 min - NOW PAUSED):
   - Uses the global cpx_service created in main.py
   - ext_user_id comes from app_config.cpx_ext_user_id
   - This is CORRECT for bulk survey refresh

2. ALLOCATION FLOW (/api/store or survey-allocation/entry):
   - OLD flow: Uses global cpx_service.generate_entry_link()
     → href has ext_user_id baked in from refresh
   - NEW flow: Uses fetch_and_allocate_for_respondent()
     → Calls CPX API with respondent_id as ext_user_id

The issue is in traffic.py lines 760-770:
   cpx_service.generate_entry_link() uses CACHED href from refresh
   That href contains ext_user_id=PANEL_88921 (from refresh)

The FIX is already in survey_allocation_service._build_cpx_entry_link():
   It calls fetch_and_allocate_for_respondent(respondent_id)
   Which makes a FRESH API call with respondent as ext_user_id
""")
print("=" * 60)
