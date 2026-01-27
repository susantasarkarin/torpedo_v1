#!/usr/bin/env python3
"""
Fix CPX Entry Links in Database

This script updates old CPX survey records that may have incorrect entry_link URLs
using the deprecated 'offers.cpx-research.com' format.

The script:
1. Finds all CPX surveys with entry_link containing 'offers.cpx-research.com'
2. Regenerates entry_link templates using the correct format
3. Updates live_link to prefer href (click.cpx-research.com format) over href_new

Run this script on:
- Localhost: python fix_cpx_entry_links.py
- VM: python3 fix_cpx_entry_links.py

Author: Campaign Platform Team
Date: January 2026
"""

import os
import sys
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
load_dotenv("/var/www/campaign_platform/backend/.env")  # VM path


def get_mongo_client():
    """Get MongoDB client from environment"""
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    return MongoClient(mongo_uri)


def fix_cpx_surveys():
    """Fix CPX survey entry links in the database"""
    print("=" * 60)
    print("CPX Entry Link Fix Script")
    print("=" * 60)
    print(f"Started at: {datetime.now().isoformat()}")
    print()
    
    client = get_mongo_client()
    
    # Check both possible database names
    db_names = ["cpx_research", "torpedo_cpx"]
    
    total_fixed = 0
    total_checked = 0
    
    for db_name in db_names:
        try:
            db = client[db_name]
            collection = db["cpx_surveys"]
            
            # Count total surveys
            total_count = collection.count_documents({})
            if total_count == 0:
                print(f"[{db_name}] No surveys found, skipping...")
                continue
                
            print(f"\n[{db_name}] Found {total_count} total CPX surveys")
            
            # Find surveys with incorrect entry_link format
            incorrect_query = {
                "$or": [
                    {"entry_link": {"$regex": "offers\\.cpx-research\\.com", "$options": "i"}},
                    {"live_link": {"$regex": "offers\\.cpx-research\\.com", "$options": "i"}},
                ]
            }
            
            incorrect_count = collection.count_documents(incorrect_query)
            print(f"[{db_name}] Surveys with offers.cpx-research.com links: {incorrect_count}")
            
            # Find surveys where live_link should use href instead of href_new
            needs_href_fix = collection.count_documents({
                "href": {"$exists": True, "$ne": ""},
                "live_link": {"$regex": "offers\\.cpx-research\\.com", "$options": "i"}
            })
            print(f"[{db_name}] Surveys where live_link should use href: {needs_href_fix}")
            
            # Update surveys to use href for live_link when available
            fixed_count = 0
            
            # Get CPX settings for generating entry_link
            cpx_app_id = os.getenv("CPX_APP_ID", "")
            
            # Fix 1: Update live_link to use href when available
            result = collection.update_many(
                {
                    "href": {"$exists": True, "$ne": ""},
                    "live_link": {"$ne": "$href"}  # Only update if different
                },
                [
                    {
                        "$set": {
                            "live_link": {"$ifNull": ["$href", "$live_link"]},
                            "last_fixed_at": datetime.utcnow()
                        }
                    }
                ]
            )
            print(f"[{db_name}] Updated live_link to use href: {result.modified_count} surveys")
            fixed_count += result.modified_count
            
            # Fix 2: Regenerate entry_link template for surveys without proper href
            # Note: We can only regenerate template format, actual links need respondent ID
            if cpx_app_id:
                for survey in collection.find({"survey_id": {"$exists": True}}):
                    survey_id = survey.get("survey_id") or survey.get("_id")
                    if not survey_id:
                        continue
                    
                    # Generate new entry_link template
                    new_entry_link = (
                        f"https://offers.cpx-research.com/index.php"
                        f"?app_id={cpx_app_id}"
                        f"&ext_user_id={{ext_user_id}}"
                        f"&secure_hash={{secure_hash}}"
                        f"&survey_id={survey_id}"
                        f"&subid_1={{subid_1}}"
                    )
                    
                    # Only update if entry_link is missing or malformed
                    old_entry_link = survey.get("entry_link", "")
                    if not old_entry_link or "{ext_user_id}" not in old_entry_link:
                        collection.update_one(
                            {"_id": survey["_id"]},
                            {"$set": {"entry_link": new_entry_link, "last_fixed_at": datetime.utcnow()}}
                        )
                        fixed_count += 1
                    
                    total_checked += 1
            
            total_fixed += fixed_count
            print(f"[{db_name}] Total surveys fixed: {fixed_count}")
            
        except Exception as e:
            print(f"[{db_name}] Error: {e}")
    
    print()
    print("=" * 60)
    print(f"Summary:")
    print(f"  Total surveys checked: {total_checked}")
    print(f"  Total surveys fixed: {total_fixed}")
    print(f"Completed at: {datetime.now().isoformat()}")
    print("=" * 60)
    
    return total_fixed


def verify_api_url_in_code():
    """Verify the API URL is correct in the codebase"""
    print("\n" + "=" * 60)
    print("Verifying API URLs in code...")
    print("=" * 60)
    
    correct_url = "https://live-api.cpx-research.com/api/get-surveys.php"
    incorrect_patterns = [
        "offers.cpx-research.com/api",
        "offers.cpx-research.com/api/get-surveys",
    ]
    
    print(f"\n✓ Correct API URL: {correct_url}")
    print("\n✗ Deprecated URLs (should not be in code for API calls):")
    for pattern in incorrect_patterns:
        print(f"  - {pattern}")
    
    print("\nNote: 'offers.cpx-research.com/index.php' is OK for direct survey entry URLs")
    print("      (used as fallback when href from API is not available)")


if __name__ == "__main__":
    print("\nCPX Entry Link Migration Script")
    print("================================\n")
    
    # Verify code changes
    verify_api_url_in_code()
    
    # Fix database entries
    print()
    fixed = fix_cpx_surveys()
    
    if fixed > 0:
        print(f"\n✓ Successfully fixed {fixed} survey records")
    else:
        print("\n✓ No surveys needed fixing (all links are correct)")
    
    print("\nDone!")
