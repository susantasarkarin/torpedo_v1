#!/usr/bin/env python3
from pymongo import MongoClient
import os
from dotenv import load_dotenv
load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))

print("=" * 60)
print("CPX AUTO-REFRESH PAUSE & EXT_USER_ID CHECK")
print("=" * 60)

# 1. Pause CPX auto-refresh
settings_db = client["torpedo_settings"]
result = settings_db["app_settings"].update_one(
    {"_id": "survey_filters"},
    {"$set": {"auto_refresh_enabled": False}},
    upsert=True
)
print("\n1. ✅ CPX Auto-refresh PAUSED")

# Verify
settings = settings_db["app_settings"].find_one({"_id": "survey_filters"})
print(f"   auto_refresh_enabled: {settings.get('auto_refresh_enabled')}")

# 2. Check CPX configuration - where is ext_user_id coming from?
print("\n2. CHECKING CPX CONFIGURATION:")

# Check environment variables
print("\n   Environment variables (from .env):")
print(f"   CPX_APP_ID: {os.getenv('CPX_APP_ID', 'NOT SET')}")
print(f"   CPX_EXT_USER_ID: {os.getenv('CPX_EXT_USER_ID', 'NOT SET')}")
print(f"   CPX_SECURE_HASH_KEY: {'SET' if os.getenv('CPX_SECURE_HASH_KEY') else 'NOT SET'}")

# 3. Check what's in cpx_surveys - what ext_user_id was used?
print("\n3. CHECKING CPX SURVEYS (recent):")
cpx_db = client["cpx_research"]
recent_survey = cpx_db["cpx_surveys"].find_one({}, sort=[("last_updated", -1)])
if recent_survey:
    raw_data = recent_survey.get("raw_data", {})
    href = recent_survey.get("href", "")
    print(f"   Survey ID: {recent_survey.get('_id')}")
    print(f"   href (first 150 chars): {href[:150]}...")
    # Check if ext_user_id is in the href
    if "ext_user_id=" in href:
        # Extract ext_user_id from href
        import urllib.parse
        parsed = urllib.parse.urlparse(href)
        params = urllib.parse.parse_qs(parsed.query)
        ext_user_id = params.get("ext_user_id", ["NOT FOUND"])[0]
        print(f"   ext_user_id in href: {ext_user_id}")

# 4. Check if there's a CPX service init somewhere storing this
print("\n4. ISSUE ANALYSIS:")
print("   The ext_user_id '164508284' or 'PANEL_88921' is from:")
print("   - Environment variable CPX_EXT_USER_ID")
print("   - OR hardcoded in the CPXService initialization")
print("")
print("   For per-respondent allocation, the flow should use:")
print("   - fetch_and_allocate_for_respondent(respondent_id)")
print("   - This method generates secure_hash with respondent_id as ext_user_id")
print("")
print("   If you're seeing PANEL_88921, the OLD fetch_cpx_surveys() is being called")
print("   instead of fetch_and_allocate_for_respondent()")

print("\n" + "=" * 60)
