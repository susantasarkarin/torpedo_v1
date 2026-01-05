"""
Migration: Add soft delete fields to all collections.
Run: python backend/scripts/add_soft_delete_fields.py

This script is idempotent - safe to run multiple times.
"""
import os
import sys
from datetime import datetime
from pymongo import MongoClient

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

# Collections to add soft delete fields to
COLLECTIONS_BY_DB = {
    "email_automation": [
        "panel_vendors",
        "projects", 
        "contacts",
        "leads",
        "email_templates",
        "lists",
        "campaign_recipients"
    ],
    "cpx_research": [
        "vendors"  # billing vendors
    ],
    "campaign_platform": [
        "invoices",
        "bills", 
        "estimates",
        "expenses",
        "items",
        "rfqs"
    ]
}

def add_soft_delete_fields():
    """Add is_deleted field to documents that don't have it."""
    client = MongoClient(MONGO_URI)
    
    total_updated = 0
    
    for db_name, collections in COLLECTIONS_BY_DB.items():
        db = client[db_name]
        print(f"\n=== Database: {db_name} ===")
        
        for coll_name in collections:
            collection = db[coll_name]
            
            # Check if collection exists
            if coll_name not in db.list_collection_names():
                print(f"  {coll_name}: SKIPPED (does not exist)")
                continue
            
            # Count documents without is_deleted field
            count_before = collection.count_documents({"is_deleted": {"$exists": False}})
            
            if count_before == 0:
                existing = collection.count_documents({})
                print(f"  {coll_name}: OK ({existing} docs already have is_deleted)")
                continue
            
            # Add is_deleted: false to documents that don't have it
            result = collection.update_many(
                {"is_deleted": {"$exists": False}},
                {"$set": {"is_deleted": False}}
            )
            
            print(f"  {coll_name}: Updated {result.modified_count} documents")
            total_updated += result.modified_count
            
            # Create index on is_deleted
            collection.create_index("is_deleted")
            print(f"  {coll_name}: Index created on is_deleted")
    
    client.close()
    print(f"\n=== Migration Complete: {total_updated} documents updated ===")

if __name__ == "__main__":
    print("Starting soft delete migration...")
    print(f"MongoDB URI: {MONGO_URI}")
    add_soft_delete_fields()
