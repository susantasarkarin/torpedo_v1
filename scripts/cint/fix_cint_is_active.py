#!/usr/bin/env python3
"""
Migration: Set is_active=True for all live, non-deactivated CINT surveys.

This fixes the issue where is_active was not being stored in MongoDB because:
1. Older surveys were inserted before the is_active logic was added
2. The field was being excluded or set to None

Run: python fix_cint_is_active.py
"""
from pymongo import MongoClient
from datetime import datetime, timezone

def main():
    print("=== CINT Survey Migration: Set is_active ===")
    print()
    
    client = MongoClient()
    db = client['cint_research']
    collection = db.cint_surveys
    
    # Count surveys needing fix
    need_fix_query = {
        "is_live": True,
        "message_reason": {"$ne": "deactivated"},
        "$or": [
            {"is_active": None},
            {"is_active": {"$exists": False}}
        ]
    }
    
    count_need_fix = collection.count_documents(need_fix_query)
    print(f"Surveys needing is_active fix: {count_need_fix}")
    
    if count_need_fix == 0:
        print("No migration needed!")
        client.close()
        return
    
    # Run the migration
    print()
    print("Running migration...")
    
    result = collection.update_many(
        need_fix_query,
        {
            "$set": {
                "is_active": True,
                "is_active_fixed_at": datetime.now(timezone.utc)
            }
        }
    )
    
    print(f"Modified {result.modified_count} surveys")
    
    # Also set is_active=False for deactivated surveys
    deactivated_query = {
        "message_reason": "deactivated",
        "$or": [
            {"is_active": None},
            {"is_active": True},
            {"is_active": {"$exists": False}}
        ]
    }
    
    deactivated_count = collection.count_documents({"message_reason": "deactivated"})
    if deactivated_count > 0:
        result2 = collection.update_many(
            deactivated_query,
            {
                "$set": {
                    "is_active": False,
                    "is_active_fixed_at": datetime.now(timezone.utc)
                }
            }
        )
        print(f"Set is_active=False for {result2.modified_count} deactivated surveys")
    
    # Verify
    print()
    print("Post-migration counts:")
    print(f"  Total surveys: {collection.count_documents({})}")
    print(f"  is_live=True: {collection.count_documents({'is_live': True})}")
    print(f"  is_active=True: {collection.count_documents({'is_active': True})}")
    print(f"  is_active=False: {collection.count_documents({'is_active': False})}")
    print(f"  is_active=None: {collection.count_documents({'is_active': None})}")
    
    client.close()
    print()
    print("Migration complete!")

if __name__ == "__main__":
    main()
