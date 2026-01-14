"""
Migration Script: Add Click Tracking Fields to Existing Surveys

This one-time migration adds the following fields to existing CPX and CINT surveys:
- click_count: 0 (number of times respondents were allocated to this survey)
- last_clicked_at: None (timestamp of last allocation)
- created_at: datetime (when survey was first stored - uses existing date fields as fallback)

Run this script once after deploying the click-based survey management update.

Usage:
    python scripts/migrate_survey_click_tracking.py

The script is idempotent - running it multiple times won't overwrite existing values.
"""

import os
import sys
from datetime import datetime, timezone
from pymongo import MongoClient
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment
load_dotenv()


def migrate_cpx_surveys(client: MongoClient) -> dict:
    """
    Add click tracking fields to CPX surveys.
    
    Returns migration statistics.
    """
    db = client["cpx_research"]
    collection = db["cpx_surveys"]
    
    stats = {
        "total": 0,
        "updated": 0,
        "already_migrated": 0,
        "errors": 0
    }
    
    print("\n📊 Migrating CPX surveys...")
    
    # Count total documents
    stats["total"] = collection.count_documents({})
    print(f"   Total CPX surveys: {stats['total']}")
    
    if stats["total"] == 0:
        print("   No CPX surveys to migrate")
        return stats
    
    # Find surveys without click_count field
    surveys_to_migrate = collection.find({
        "click_count": {"$exists": False}
    })
    
    for survey in surveys_to_migrate:
        try:
            survey_id = survey.get("_id")
            
            # Determine created_at from existing fields (fallback order)
            created_at = (
                survey.get("created_at") or
                survey.get("inserted_at") or
                survey.get("last_updated") or
                datetime.utcnow()
            )
            
            # Update with click tracking fields
            result = collection.update_one(
                {"_id": survey_id},
                {
                    "$set": {
                        "click_count": 0,
                        "last_clicked_at": None,
                    },
                    "$setOnInsert": {
                        "created_at": created_at
                    }
                }
            )
            
            if result.modified_count > 0:
                stats["updated"] += 1
            
        except Exception as e:
            print(f"   ❌ Error migrating survey {survey.get('_id')}: {e}")
            stats["errors"] += 1
    
    # Count already migrated
    stats["already_migrated"] = stats["total"] - stats["updated"] - stats["errors"]
    
    # Also ensure created_at exists on all documents
    result = collection.update_many(
        {"created_at": {"$exists": False}},
        [
            {
                "$set": {
                    "created_at": {
                        "$ifNull": [
                            "$inserted_at",
                            {"$ifNull": ["$last_updated", datetime.utcnow()]}
                        ]
                    }
                }
            }
        ]
    )
    
    print(f"   ✅ Updated {stats['updated']} surveys")
    print(f"   ℹ️  Already migrated: {stats['already_migrated']}")
    if stats["errors"] > 0:
        print(f"   ❌ Errors: {stats['errors']}")
    
    return stats


def migrate_cint_surveys(client: MongoClient) -> dict:
    """
    Add click tracking fields to CINT surveys.
    
    Returns migration statistics.
    """
    db = client["cint_research"]
    collection = db["cint_surveys"]
    
    stats = {
        "total": 0,
        "updated": 0,
        "already_migrated": 0,
        "errors": 0
    }
    
    print("\n📊 Migrating CINT surveys...")
    
    # Count total documents
    stats["total"] = collection.count_documents({})
    print(f"   Total CINT surveys: {stats['total']}")
    
    if stats["total"] == 0:
        print("   No CINT surveys to migrate")
        return stats
    
    # Find surveys without click_count field
    surveys_to_migrate = collection.find({
        "click_count": {"$exists": False}
    })
    
    for survey in surveys_to_migrate:
        try:
            survey_id = survey.get("survey_id")
            
            # Determine created_at from existing fields (fallback order)
            created_at = (
                survey.get("created_at") or
                survey.get("received_at") or
                survey.get("last_updated_at") or
                datetime.now(timezone.utc)
            )
            
            # Update with click tracking fields
            result = collection.update_one(
                {"survey_id": survey_id},
                {
                    "$set": {
                        "click_count": 0,
                        "last_clicked_at": None,
                    },
                    "$setOnInsert": {
                        "created_at": created_at
                    }
                }
            )
            
            if result.modified_count > 0:
                stats["updated"] += 1
            
        except Exception as e:
            print(f"   ❌ Error migrating survey {survey.get('survey_id')}: {e}")
            stats["errors"] += 1
    
    # Count already migrated
    stats["already_migrated"] = stats["total"] - stats["updated"] - stats["errors"]
    
    # Also ensure created_at exists on all documents
    result = collection.update_many(
        {"created_at": {"$exists": False}},
        [
            {
                "$set": {
                    "created_at": {
                        "$ifNull": [
                            "$received_at",
                            {"$ifNull": ["$last_updated_at", datetime.now(timezone.utc)]}
                        ]
                    }
                }
            }
        ]
    )
    
    print(f"   ✅ Updated {stats['updated']} surveys")
    print(f"   ℹ️  Already migrated: {stats['already_migrated']}")
    if stats["errors"] > 0:
        print(f"   ❌ Errors: {stats['errors']}")
    
    return stats


def create_indexes(client: MongoClient):
    """
    Create indexes for efficient click-based cleanup queries.
    """
    print("\n📊 Creating indexes for click tracking...")
    
    # CPX indexes
    cpx_collection = client["cpx_research"]["cpx_surveys"]
    cpx_collection.create_index([("click_count", 1)], name="click_count_idx")
    cpx_collection.create_index([("created_at", 1)], name="created_at_idx")
    cpx_collection.create_index(
        [("click_count", 1), ("created_at", 1)],
        name="click_cleanup_compound_idx"
    )
    print("   ✅ CPX indexes created")
    
    # CINT indexes
    cint_collection = client["cint_research"]["cint_surveys"]
    cint_collection.create_index([("click_count", 1)], name="click_count_idx")
    cint_collection.create_index([("created_at", 1)], name="created_at_idx")
    cint_collection.create_index(
        [("click_count", 1), ("created_at", 1)],
        name="click_cleanup_compound_idx"
    )
    print("   ✅ CINT indexes created")


def main():
    """Run the migration."""
    print("=" * 60)
    print("🚀 Survey Click Tracking Migration")
    print("=" * 60)
    
    # Connect to MongoDB
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    print(f"\n📡 Connecting to MongoDB...")
    
    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        print("   ✅ Connected successfully")
    except Exception as e:
        print(f"   ❌ Failed to connect: {e}")
        sys.exit(1)
    
    # Run migrations
    cpx_stats = migrate_cpx_surveys(client)
    cint_stats = migrate_cint_surveys(client)
    
    # Create indexes
    create_indexes(client)
    
    # Summary
    print("\n" + "=" * 60)
    print("📋 Migration Summary")
    print("=" * 60)
    print(f"\n   CPX Surveys:")
    print(f"     Total: {cpx_stats['total']}")
    print(f"     Updated: {cpx_stats['updated']}")
    print(f"     Already migrated: {cpx_stats['already_migrated']}")
    print(f"     Errors: {cpx_stats['errors']}")
    
    print(f"\n   CINT Surveys:")
    print(f"     Total: {cint_stats['total']}")
    print(f"     Updated: {cint_stats['updated']}")
    print(f"     Already migrated: {cint_stats['already_migrated']}")
    print(f"     Errors: {cint_stats['errors']}")
    
    total_errors = cpx_stats["errors"] + cint_stats["errors"]
    if total_errors == 0:
        print("\n✅ Migration completed successfully!")
    else:
        print(f"\n⚠️  Migration completed with {total_errors} errors")
    
    client.close()


if __name__ == "__main__":
    main()
