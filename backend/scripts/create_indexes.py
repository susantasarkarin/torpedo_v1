"""
Migration: Create all required unique/compound indexes.
Run: python backend/scripts/create_indexes.py

This script is idempotent - safe to run multiple times.
"""
import os
import sys
from pymongo import MongoClient
from pymongo.errors import OperationFailure

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

# Index definitions: (db_name, collection, field_or_fields, options)
INDEXES = [
    # Suppression list - unique email
    ("email_automation", "suppression_list", "email", {"unique": True}),
    
    # Panel vendors - unique VID (sparse to allow nulls)
    ("email_automation", "panel_vendors", "vid", {"unique": True, "sparse": True}),
    
    # Campaign sends - idempotency key
    ("email_automation", "campaign_sends", "idempotency_key", {"unique": True, "sparse": True}),
    
    # Invoices - idempotency key
    ("campaign_platform", "invoices", "idempotency_key", {"unique": True, "sparse": True}),
    
    # Traffic records - callback key
    ("traffic_flow_db", "traffic_records", "callback_key", {"unique": True, "sparse": True}),
    
    # Audit log - compound index for queries
    ("email_automation", "audit_log", [("entity_type", 1), ("entity_id", 1), ("timestamp", -1)], {}),
    
    # Email audit log - compound index
    ("email_automation", "email_audit_log", [("campaign_id", 1), ("timestamp", -1)], {}),
    
    # AI review queue - status and timestamp
    ("email_automation", "ai_review_queue", [("status", 1), ("queued_at", -1)], {}),
    
    # Rate limits - account_id
    ("torpedo_gmail", "rate_limits", "account_id", {}),
]

def create_index_safe(collection, index_spec, options):
    """Create index, handling already exists gracefully."""
    try:
        if isinstance(index_spec, list):
            # Compound index
            collection.create_index(index_spec, **options)
        else:
            # Single field index
            collection.create_index(index_spec, **options)
        return True, None
    except OperationFailure as e:
        if "already exists" in str(e):
            return True, "already exists"
        return False, str(e)

def create_all_indexes():
    """Create all required indexes."""
    client = MongoClient(MONGO_URI)
    
    results = {"success": 0, "exists": 0, "failed": 0}
    
    print("Creating indexes...\n")
    
    for db_name, coll_name, index_spec, options in INDEXES:
        db = client[db_name]
        collection = db[coll_name]
        
        success, msg = create_index_safe(collection, index_spec, options)
        
        index_desc = str(index_spec)
        if success:
            if msg == "already exists":
                print(f"✓ {db_name}.{coll_name} ({index_desc}): Already exists")
                results["exists"] += 1
            else:
                print(f"✓ {db_name}.{coll_name} ({index_desc}): Created")
                results["success"] += 1
        else:
            print(f"✗ {db_name}.{coll_name} ({index_desc}): FAILED - {msg}")
            results["failed"] += 1
    
    client.close()
    
    print(f"\n=== Index Creation Complete ===")
    print(f"Created: {results['success']}")
    print(f"Already existed: {results['exists']}")
    print(f"Failed: {results['failed']}")

if __name__ == "__main__":
    print("Starting index creation...")
    print(f"MongoDB URI: {MONGO_URI}\n")
    create_all_indexes()
