#!/usr/bin/env python3
"""
Fix CPX Integration Redirect URL

This script updates the CPX vendor's completeRD and terminateRD redirect URLs
to use the correct format with message_id and subid_1 parameters.

Correct URL format: https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}

The script will:
1. Connect to MongoDB
2. Find the CPX vendor
3. Update completeRD and terminateRD with the correct URL
4. Display the changes made
"""

import os
from pymongo import MongoClient
from datetime import datetime

# Configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DATABASE_NAME = "campaign_platform"  # or "operations" if vendors are there
VENDORS_COLLECTION = "vendors"

# The correct CPX redirect URL
CORRECT_CPX_REDIRECT_URL = "https://torpedo.cogentixresearch.com/cpx-research?message_id={message_id}&subid={subid_1}"

def fix_cpx_redirect_url():
    """Update CPX vendor's redirect URLs to correct format"""
    try:
        # Connect to MongoDB
        client = MongoClient(MONGO_URI)
        db = client[DATABASE_NAME]
        vendors_collection = db[VENDORS_COLLECTION]
        
        print("=" * 80)
        print("🔧 CPX REDIRECT URL FIX")
        print("=" * 80)
        print(f"\n📍 Database: {DATABASE_NAME}")
        print(f"📍 Collection: {VENDORS_COLLECTION}")
        print(f"🔗 Correct URL: {CORRECT_CPX_REDIRECT_URL}\n")
        
        # Find CPX vendor (could be named "cpx", "CPX", "CPX Research", etc.)
        cpx_vendor = vendors_collection.find_one({"vendorName": {"$regex": "cpx", "$options": "i"}})
        
        if not cpx_vendor:
            # Try looking for vendor with vid="cpx"
            cpx_vendor = vendors_collection.find_one({"vid": "cpx"})
        
        if not cpx_vendor:
            print("❌ ERROR: CPX vendor not found!")
            print("\nSearching for all vendors:")
            all_vendors = list(vendors_collection.find())
            for v in all_vendors:
                print(f"  - {v.get('vendorName', 'N/A')} (vid: {v.get('vid', 'N/A')})")
            return False
        
        print(f"✅ Found CPX vendor: {cpx_vendor.get('vendorName')}")
        print(f"   Vendor ID (vid): {cpx_vendor.get('vid')}")
        print(f"   MongoDB _id: {cpx_vendor.get('_id')}\n")
        
        # Display current URLs
        print("📋 CURRENT CONFIGURATION:")
        print("-" * 80)
        current_complete_rd = cpx_vendor.get("completeRD", [])
        current_terminate_rd = cpx_vendor.get("terminateRD", [])
        
        print(f"completeRD ({len(current_complete_rd)} URL{'s' if len(current_complete_rd) != 1 else ''}):")
        for url in current_complete_rd:
            print(f"  • {url}")
        if not current_complete_rd:
            print("  (empty)")
        
        print(f"\nterminateRD ({len(current_terminate_rd)} URL{'s' if len(current_terminate_rd) != 1 else ''}):")
        for url in current_terminate_rd:
            print(f"  • {url}")
        if not current_terminate_rd:
            print("  (empty)")
        
        # Ask for confirmation
        print("\n" + "=" * 80)
        print("📝 PROPOSED CHANGES:")
        print("=" * 80)
        print(f"\ncompleteRD will be updated to:")
        print(f"  [{CORRECT_CPX_REDIRECT_URL}]")
        print(f"\nterminateRD will be updated to:")
        print(f"  [{CORRECT_CPX_REDIRECT_URL}]")
        
        confirm = input("\n⚠️  Continue with the update? (type 'YES' to confirm): ").strip().upper()
        
        if confirm != "YES":
            print("\n❌ Update cancelled by user.")
            return False
        
        # Update the vendor document
        update_data = {
            "completeRD": [CORRECT_CPX_REDIRECT_URL],
            "terminateRD": [CORRECT_CPX_REDIRECT_URL],
            "updated_at": datetime.utcnow(),
            "updated_by": "fix_cpx_redirect_url.py"
        }
        
        result = vendors_collection.update_one(
            {"_id": cpx_vendor["_id"]},
            {"$set": update_data}
        )
        
        print(f"\n✅ Update successful!")
        print(f"   Modified: {result.modified_count} document(s)")
        
        # Verify the update
        print("\n🔍 VERIFICATION:")
        print("-" * 80)
        updated_vendor = vendors_collection.find_one({"_id": cpx_vendor["_id"]})
        
        print(f"completeRD:")
        for url in updated_vendor.get("completeRD", []):
            print(f"  ✓ {url}")
        
        print(f"\nterminateRD:")
        for url in updated_vendor.get("terminateRD", []):
            print(f"  ✓ {url}")
        
        print("\n✅ CPX redirect URL fix completed successfully!")
        print("=" * 80)
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if 'client' in locals():
            client.close()

if __name__ == "__main__":
    success = fix_cpx_redirect_url()
    exit(0 if success else 1)
