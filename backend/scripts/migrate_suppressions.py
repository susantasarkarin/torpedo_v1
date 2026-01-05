"""
Migration: Populate global suppression list from existing bounced/unsubscribed recipients.
Run: python backend/scripts/migrate_suppressions.py

This script is idempotent - safe to run multiple times.
"""
import os
import sys
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

def migrate_suppressions():
    """Migrate existing bounced/unsubscribed recipients to global suppression list."""
    client = MongoClient(MONGO_URI)
    db = client["email_automation"]
    
    recipients = db["campaign_recipients"]
    suppression = db["suppression_list"]
    
    # Ensure unique index exists
    suppression.create_index("email", unique=True)
    
    stats = {"bounced": 0, "unsubscribed": 0, "skipped": 0, "errors": 0}
    
    print("Migrating bounced recipients...")
    
    # Find all bounced recipients
    for recipient in recipients.find({"status": "bounced"}):
        email = recipient.get("email", "").lower().strip()
        if not email:
            continue
        
        try:
            suppression.insert_one({
                "email": email,
                "reason": "bounced",
                "source_campaign_id": str(recipient.get("campaign_id", "")),
                "suppressed_at": recipient.get("updated_at", datetime.utcnow()),
                "suppressed_by": "migration"
            })
            stats["bounced"] += 1
        except DuplicateKeyError:
            stats["skipped"] += 1
        except Exception as e:
            stats["errors"] += 1
            print(f"  Error: {email} - {e}")
    
    print("Migrating unsubscribed recipients...")
    
    # Find all unsubscribed recipients
    for recipient in recipients.find({"status": "unsubscribed"}):
        email = recipient.get("email", "").lower().strip()
        if not email:
            continue
        
        try:
            suppression.insert_one({
                "email": email,
                "reason": "unsubscribed",
                "source_campaign_id": str(recipient.get("campaign_id", "")),
                "suppressed_at": recipient.get("updated_at", datetime.utcnow()),
                "suppressed_by": "migration"
            })
            stats["unsubscribed"] += 1
        except DuplicateKeyError:
            stats["skipped"] += 1
        except Exception as e:
            stats["errors"] += 1
            print(f"  Error: {email} - {e}")
    
    client.close()
    
    print(f"\n=== Migration Complete ===")
    print(f"Bounced emails added: {stats['bounced']}")
    print(f"Unsubscribed emails added: {stats['unsubscribed']}")
    print(f"Already existed (skipped): {stats['skipped']}")
    print(f"Errors: {stats['errors']}")
    print(f"Total in suppression list: {stats['bounced'] + stats['unsubscribed']}")

if __name__ == "__main__":
    print("Starting suppression list migration...")
    print(f"MongoDB URI: {MONGO_URI}\n")
    migrate_suppressions()
