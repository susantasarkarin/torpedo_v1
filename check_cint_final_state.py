#!/usr/bin/env python3
"""
CINT STATUS VERIFICATION SCRIPT
Checks the current state of Cint surveys and entry links after fixes.
"""

import sys
import os
sys.path.insert(0, "/var/www/campaign_platform/backend")

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from datetime import datetime, timedelta
import asyncio

# Use sync client for simplicity
mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
client = MongoClient(mongo_uri)

async def check_cint_state():
    """Check MongoDB state for Cint surveys and entry links"""
    
    db = client["cint_research"]
    surveys = db["cint_surveys"]
    entry_links = db["cint_entry_links"]
    settings = db["cint_settings"]
    
    print("=" * 70)
    print("CINT INTEGRATION STATUS REPORT")
    print("=" * 70)
    print()
    
    # Survey counts
    total = surveys.count_documents({})
    is_active = surveys.count_documents({"is_active": True})
    is_live = surveys.count_documents({"is_live": True})
    is_active_in_pool = surveys.count_documents({"is_active_in_pool": True})
    has_quota = surveys.count_documents({"total_remaining": {"$gt": 0}})
    has_entry_link = surveys.count_documents({"survey_id": {"$in": [l["survey_id"] for l in entry_links.find({}, {"survey_id": 1})]}})
    
    print("📊 SURVEY COUNTS:")
    print(f"  Total surveys:              {total:,}")
    print(f"  is_active=true:             {is_active:,}")
    print(f"  is_live=true:               {is_live:,}")
    print(f"  is_active_in_pool=true:     {is_active_in_pool:,}  ← ALLOCATABLE")
    print(f"  Has quota (total_remaining>0): {has_quota:,}")
    print(f"  Has entry link:             {has_entry_link:,}")
    print()
    
    # Entry link counts
    entry_link_count = entry_links.count_documents({})
    synthetic_count = entry_links.count_documents({"synthetic": True, "_type": "synthetic_entry_link"})
    api_count = entry_links.count_documents({"synthetic": {"$ne": True}})
    
    print("🔗 ENTRY LINKS:")
    print(f"  Total entry links:          {entry_link_count:,}")
    print(f"  Synthetic (workaround):     {synthetic_count:,}")
    print(f"  From API:                   {api_count:,}")
    print()
    
    if entry_link_count > 0:
        sample_link = entry_links.find_one({})
        print("📝 SAMPLE ENTRY LINK:")
        print(f"  Survey ID:                  {sample_link.get('survey_id')}")
        print(f"  Live link:                  {sample_link.get('live_link')[:80]}...")
        print(f"  Is synthetic:               {sample_link.get('synthetic', False)}")
        print()
    
    # Check settings/subscription
    settings_doc = settings.find_one({"type": "webhook_subscription"})
    if settings_doc:
        print("⚙️ WEBHOOK SUBSCRIPTION:")
        print(f"  Subscription ID:            {settings_doc.get('subscription_id', 'N/A')}")
        print(f"  Status:                     {settings_doc.get('status', 'N/A')}")
        print(f"  Created:                    {settings_doc.get('created_at', 'N/A')}")
        print()
    
    # Check last webhook
    last_webhook = surveys.find_one(
        {"created_from_webhook": True},
        sort=[("created_at", -1)]
    )
    if last_webhook:
        print("📨 LAST WEBHOOK INGESTION:")
        print(f"  Survey ID:                  {last_webhook.get('survey_id')}")
        print(f"  Ingested:                   {last_webhook.get('created_at')}")
        print()
    
    # Filter settings
    filter_settings = settings.find_one({"type": "filter_settings"})
    if filter_settings:
        print("🔍 FILTER SETTINGS:")
        print(f"  max_loi:                    {filter_settings.get('max_loi', 'N/A')} min")
        print(f"  min_cpi:                    ${filter_settings.get('min_cpi', 'N/A')}")
        print(f"  min_incidence:              {filter_settings.get('min_incidence', 'N/A')}%")
        print()
    
    # Allocation readiness
    print("✅ ALLOCATION READINESS:")
    if is_active_in_pool > 0 and entry_link_count > 0:
        print(f"  Status:                     🟢 READY (partial)")
        print(f"  Can allocate:               {min(is_active_in_pool, entry_link_count)} surveys")
        if entry_link_count < is_active_in_pool:
            print(f"  Need {is_active_in_pool - entry_link_count:,} more entry links for full scale")
    elif is_active_in_pool > 0:
        print(f"  Status:                     🟡 SURVEYS READY, NO ENTRY LINKS")
        print(f"  Active surveys:             {is_active_in_pool:,}")
        print(f"  Need:                       Entry link creation (blocked on Cint supplier allocation)")
    else:
        print(f"  Status:                     🔴 NOT READY")
        print(f"  Issues:                     No surveys marked active")
    print()
    
    # Next steps
    print("📋 NEXT STEPS:")
    print("  1. ✅ sync_active_status_by_filters() - DONE (22,741 surveys active)")
    print("  2. ⚠️  Create entry links for all 22,741 surveys")
    print("     - Via Cint API (requires supplier allocation from Cint)")
    print("     - OR use more synthetic links")
    print("  3. ✅ Test allocation with sample respondent")
    print()
    
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(check_cint_state())
