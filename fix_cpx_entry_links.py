#!/usr/bin/env python3
"""
Fix CPX Entry Links in Database

This script updates all CPX survey records to use the correct entry_link format:
https://offers.cpx-research.com/index.php?app_id={app_id}&ext_user_id={ext_user_id}&secure_hash={secure_hash}&survey_id={survey_id}&subid_1={subid_1}

The script:
1. Finds all CPX surveys
2. Regenerates live_link and entry_link using the correct offers.cpx-research.com format

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


def generate_entry_link_template(app_id: str, survey_id: str) -> str:
    """
    Generate entry link template in the correct format:
    https://offers.cpx-research.com/index.php?app_id={app_id}&ext_user_id={ext_user_id}&secure_hash={secure_hash}&survey_id={survey_id}&subid_1={subid_1}
    """
    return (
        f"https://offers.cpx-research.com/index.php"
        f"?app_id={app_id}"
        f"&ext_user_id={{ext_user_id}}"
        f"&secure_hash={{secure_hash}}"
        f"&survey_id={survey_id}"
        f"&subid_1={{subid_1}}"
    )


def fix_cpx_surveys():
    """Fix CPX survey entry links in the database"""
    print("=" * 60)
    print("CPX Entry Link Fix Script")
    print("=" * 60)
    print(f"Started at: {datetime.now().isoformat()}")
    print()
    
    # Get CPX app_id from environment
    cpx_app_id = os.getenv("CPX_APP_ID", "10754")
    print(f"Using CPX App ID: {cpx_app_id}")
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
            
            # Update all surveys to use the correct format
            fixed_count = 0
            
            for survey in collection.find({}):
                survey_id = survey.get("survey_id") or survey.get("_id")
                if not survey_id:
                    continue
                
                # Generate new entry_link and live_link in correct format
                new_link = generate_entry_link_template(cpx_app_id, str(survey_id))
                
                old_live_link = survey.get("live_link", "")
                old_entry_link = survey.get("entry_link", "")
                
                # Update if different
                if old_live_link != new_link or old_entry_link != new_link:
                    collection.update_one(
                        {"_id": survey["_id"]},
                        {
                            "$set": {
                                "live_link": new_link,
                                "entry_link": new_link,
                                "last_fixed_at": datetime.utcnow()
                            }
                        }
                    )
                    fixed_count += 1
                
                total_checked += 1
            
            total_fixed += fixed_count
            print(f"[{db_name}] Surveys checked: {total_count}")
            print(f"[{db_name}] Surveys updated: {fixed_count}")
            
        except Exception as e:
            print(f"[{db_name}] Error: {e}")
    
    print()
    print("=" * 60)
    print(f"Summary:")
    print(f"  Total surveys checked: {total_checked}")
    print(f"  Total surveys updated: {total_fixed}")
    print(f"Completed at: {datetime.now().isoformat()}")
    print("=" * 60)
    
    return total_fixed


def verify_url_format():
    """Show the correct URL format"""
    print("\n" + "=" * 60)
    print("Correct CPX Entry Link Format:")
    print("=" * 60)
    
    example_url = (
        "https://offers.cpx-research.com/index.php"
        "?app_id=10754"
        "&ext_user_id=6978b600bdb8af017a2af233"
        "&secure_hash=e24cc699402ddea4954679b793956f82"
        "&survey_id=60392723"
        "&subid_1=6978b600bdb8af017a2af233"
    )
    
    print(f"\nExample (with values):\n{example_url}")
    
    template_url = (
        "https://offers.cpx-research.com/index.php"
        "?app_id=10754"
        "&ext_user_id={ext_user_id}"
        "&secure_hash={secure_hash}"
        "&survey_id=60392723"
        "&subid_1={subid_1}"
    )
    
    print(f"\nTemplate (stored in DB):\n{template_url}")


if __name__ == "__main__":
    print("\nCPX Entry Link Migration Script")
    print("================================\n")
    
    # Show correct format
    verify_url_format()
    
    # Fix database entries
    print()
    fixed = fix_cpx_surveys()
    
    if fixed > 0:
        print(f"\n✓ Successfully updated {fixed} survey records")
    else:
        print("\n✓ All surveys already have the correct format")
    
    print("\nDone!")
