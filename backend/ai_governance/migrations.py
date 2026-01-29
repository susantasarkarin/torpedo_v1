"""
AI GOVERNANCE DATABASE MIGRATION
================================
Sets up required database constraints for AI governance.

This migration creates:
1. Unique constraint on email_id in classification_guard collection
2. Gemini daily usage tracking collection with date index
3. Removes any DeepSeek-related settings from database

Run this migration ONCE before deploying the new governance framework.
"""

import os
import sys
from datetime import datetime
from pymongo import MongoClient, ASCENDING
from pymongo.errors import CollectionInvalid, OperationFailure

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_mongo_client():
    """Get MongoDB client"""
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    return MongoClient(mongo_uri, serverSelectionTimeoutMS=10000)


def run_migration():
    """Run all AI governance migrations"""
    print("=" * 60)
    print("AI GOVERNANCE DATABASE MIGRATION")
    print("=" * 60)
    print()
    
    client = get_mongo_client()
    
    # Test connection
    try:
        client.admin.command('ping')
        print("✓ MongoDB connection successful")
    except Exception as e:
        print(f"✗ MongoDB connection failed: {e}")
        return False
    
    success = True
    
    # Migration 1: Create ai_governance database and collections
    print("\n--- Migration 1: Create AI Governance Collections ---")
    success = success and create_governance_collections(client)
    
    # Migration 2: Add unique constraint for email classification
    print("\n--- Migration 2: Add Email Classification Unique Constraint ---")
    success = success and add_email_classification_constraint(client)
    
    # Migration 3: Remove DeepSeek settings
    print("\n--- Migration 3: Remove DeepSeek Settings ---")
    success = success and remove_deepseek_settings(client)
    
    # Migration 4: Update email_metadata to track classification status
    print("\n--- Migration 4: Add Classification Status Indexes ---")
    success = success and add_classification_indexes(client)
    
    print("\n" + "=" * 60)
    if success:
        print("✓ ALL MIGRATIONS COMPLETED SUCCESSFULLY")
    else:
        print("✗ SOME MIGRATIONS FAILED - CHECK OUTPUT ABOVE")
    print("=" * 60)
    
    return success


def create_governance_collections(client):
    """Create ai_governance database and required collections"""
    try:
        db = client['ai_governance']
        
        # Collection 1: gemini_daily_usage - tracks daily Gemini API usage
        try:
            db.create_collection('gemini_daily_usage')
            print("  ✓ Created collection: gemini_daily_usage")
        except CollectionInvalid:
            print("  • Collection already exists: gemini_daily_usage")
        
        # Add index on date (unique)
        db['gemini_daily_usage'].create_index(
            [("date", ASCENDING)],
            unique=True,
            name="unique_date"
        )
        print("  ✓ Created unique index on date for gemini_daily_usage")
        
        # Collection 2: email_classification_guard - prevents duplicate classification
        try:
            db.create_collection('email_classification_guard')
            print("  ✓ Created collection: email_classification_guard")
        except CollectionInvalid:
            print("  • Collection already exists: email_classification_guard")
        
        # Collection 3: governance_audit_log - tracks all AI calls
        try:
            db.create_collection('governance_audit_log')
            print("  ✓ Created collection: governance_audit_log")
        except CollectionInvalid:
            print("  • Collection already exists: governance_audit_log")
        
        # Add index on timestamp for audit log
        db['governance_audit_log'].create_index(
            [("timestamp", ASCENDING)],
            name="idx_timestamp"
        )
        print("  ✓ Created index on timestamp for governance_audit_log")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Error creating governance collections: {e}")
        return False


def add_email_classification_constraint(client):
    """Add unique constraint on email_id to prevent duplicate classification"""
    try:
        db = client['ai_governance']
        collection = db['email_classification_guard']
        
        # Drop existing index if it exists (to recreate with correct settings)
        try:
            collection.drop_index("unique_email_classification")
        except OperationFailure:
            pass  # Index doesn't exist
        
        # Create unique index on email_id
        collection.create_index(
            [("email_id", ASCENDING)],
            unique=True,
            name="unique_email_classification",
            background=True
        )
        print("  ✓ Created unique index on email_id")
        
        # Also create index on status for querying
        collection.create_index(
            [("status", ASCENDING)],
            name="idx_status"
        )
        print("  ✓ Created index on status")
        
        # Create compound index for querying
        collection.create_index(
            [("status", ASCENDING), ("classification_started_at", ASCENDING)],
            name="idx_status_time"
        )
        print("  ✓ Created compound index on status + time")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Error adding email classification constraint: {e}")
        return False


def remove_deepseek_settings(client):
    """Remove all DeepSeek-related settings from database"""
    try:
        settings_db = client['torpedo_settings']
        app_settings = settings_db['app_settings']
        
        # Find and update settings document
        result = app_settings.update_many(
            {},
            {
                "$unset": {
                    "deepseek_api_key": "",
                    "deepseek_model": "",
                    "deepseek_base_url": "",
                    "ai_default_provider": ""  # Remove if it was set to deepseek
                }
            }
        )
        
        if result.modified_count > 0:
            print(f"  ✓ Removed DeepSeek settings from {result.modified_count} document(s)")
        else:
            print("  • No DeepSeek settings found to remove")
        
        # Log the removal for audit
        audit_db = client['ai_governance']
        audit_db['governance_audit_log'].insert_one({
            "event": "deepseek_removal",
            "timestamp": datetime.utcnow(),
            "details": "Removed all DeepSeek configuration from database",
            "documents_affected": result.modified_count
        })
        print("  ✓ Logged DeepSeek removal to audit log")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Error removing DeepSeek settings: {e}")
        return False


def add_classification_indexes(client):
    """Add indexes to email_metadata collection for classification tracking"""
    try:
        # torpedo_gmail database
        gmail_db = client['torpedo_gmail']
        email_metadata = gmail_db['email_metadata']
        
        # Index for finding unclassified emails
        email_metadata.create_index(
            [("ai_classification_status.status", ASCENDING)],
            name="idx_classification_status",
            background=True,
            sparse=True
        )
        print("  ✓ Created index on ai_classification_status.status")
        
        # Index for classification timestamp
        email_metadata.create_index(
            [("ai_classification_status.classified_at", ASCENDING)],
            name="idx_classified_at",
            background=True,
            sparse=True
        )
        print("  ✓ Created index on ai_classification_status.classified_at")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Error adding classification indexes: {e}")
        return False


def verify_constraints():
    """Verify all constraints are in place"""
    print("\n--- Verifying Constraints ---")
    
    client = get_mongo_client()
    db = client['ai_governance']
    
    # Check email_classification_guard indexes
    indexes = list(db['email_classification_guard'].list_indexes())
    unique_email_idx = [i for i in indexes if i.get('name') == 'unique_email_classification']
    
    if unique_email_idx and unique_email_idx[0].get('unique'):
        print("  ✓ Unique constraint on email_id is ACTIVE")
    else:
        print("  ✗ Unique constraint on email_id is MISSING")
        return False
    
    # Check daily usage index
    indexes = list(db['gemini_daily_usage'].list_indexes())
    date_idx = [i for i in indexes if i.get('name') == 'unique_date']
    
    if date_idx and date_idx[0].get('unique'):
        print("  ✓ Unique constraint on date is ACTIVE")
    else:
        print("  ✗ Unique constraint on date is MISSING")
        return False
    
    # Check DeepSeek is removed
    settings_db = client['torpedo_settings']
    settings = settings_db['app_settings'].find_one()
    
    if settings and settings.get('deepseek_api_key'):
        print("  ✗ DeepSeek API key still present in settings")
        return False
    else:
        print("  ✓ DeepSeek settings removed")
    
    print("\n  ✓ All constraints verified successfully")
    return True


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='AI Governance Database Migration')
    parser.add_argument('--verify', action='store_true', help='Only verify constraints')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    
    args = parser.parse_args()
    
    if args.verify:
        success = verify_constraints()
    elif args.dry_run:
        print("DRY RUN - No changes will be made")
        print("\nThe following migrations would be run:")
        print("  1. Create ai_governance database and collections")
        print("  2. Add unique constraint on email_id for classification guard")
        print("  3. Remove all DeepSeek settings from database")
        print("  4. Add classification status indexes to email_metadata")
        success = True
    else:
        success = run_migration()
        if success:
            verify_constraints()
    
    sys.exit(0 if success else 1)
