"""
Migration: Create deliverability tracking collections

Collections created:
1. domain_health - Track domain reputation and health metrics
   - Fields: domain, status, bounce_rate, spam_complaint_rate, last_updated
   
2. gmail_account_usage - Track Gmail account usage and limits
   - Fields: email, daily_limit, sent_today, last_reset, status, account_health
   
3. reputation_metrics - Store detailed reputation scores and history
   - Fields: metric_type, value, timestamp, domain, account_id, trend_data
"""

from pymongo import MongoClient
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)


def up(db):
    """
    Apply migration: Create deliverability collections
    
    Creates three new collections for tracking email deliverability:
    - domain_health
    - gmail_account_usage
    - reputation_metrics
    """
    logger.info("Running migration 004_create_deliverability_collections")
    
    try:
        # Create domain_health collection
        if "domain_health" not in db.list_collection_names():
            db.create_collection("domain_health")
            db.domain_health.insert_one({
                "_id": "template",
                "domain": None,
                "status": "unknown",
                "bounce_rate": 0.0,
                "spam_complaint_rate": 0.0,
                "daily_emails_sent": 0,
                "authentication_status": {
                    "spf": False,
                    "dkim": False,
                    "dmarc": False
                },
                "reputation_score": 0,
                "last_updated": datetime.utcnow(),
                "created_at": datetime.utcnow()
            })
            db.domain_health.delete_one({"_id": "template"})
            logger.info("Created domain_health collection")
        
        # Create gmail_account_usage collection
        if "gmail_account_usage" not in db.list_collection_names():
            db.create_collection("gmail_account_usage")
            db.gmail_account_usage.insert_one({
                "_id": "template",
                "email": None,
                "daily_limit": 500,
                "sent_today": 0,
                "last_reset": datetime.utcnow(),
                "status": "active",
                "account_health": "good",
                "suspension_risk": False,
                "warnings": [],
                "updated_at": datetime.utcnow()
            })
            db.gmail_account_usage.delete_one({"_id": "template"})
            logger.info("Created gmail_account_usage collection")
        
        # Create reputation_metrics collection
        if "reputation_metrics" not in db.list_collection_names():
            db.create_collection("reputation_metrics")
            db.reputation_metrics.insert_one({
                "_id": "template",
                "metric_type": None,
                "value": 0.0,
                "timestamp": datetime.utcnow(),
                "domain": None,
                "account_id": None,
                "trend_data": [],
                "source": "system",
                "notes": ""
            })
            db.reputation_metrics.delete_one({"_id": "template"})
            logger.info("Created reputation_metrics collection")
        
        # Mark migration as complete
        db.migrations_log.update_one(
            {"migration": "004_create_deliverability_collections"},
            {"$set": {
                "migration": "004_create_deliverability_collections",
                "completed_at": datetime.utcnow(),
                "status": "success"
            }},
            upsert=True
        )
        
        logger.info("Migration 004 completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Migration 004 failed: {str(e)}")
        raise


def down(db):
    """
    Rollback migration: Drop deliverability collections
    """
    logger.info("Rolling back migration 004_create_deliverability_collections")
    
    try:
        collections_to_drop = [
            "domain_health",
            "gmail_account_usage",
            "reputation_metrics"
        ]
        
        for collection_name in collections_to_drop:
            if collection_name in db.list_collection_names():
                db.drop_collection(collection_name)
                logger.info(f"Dropped collection: {collection_name}")
        
        logger.info("Rollback 004 completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Rollback 004 failed: {str(e)}")
        raise


if __name__ == "__main__":
    from dotenv import load_dotenv
    
    load_dotenv()
    
    logging.basicConfig(level=logging.INFO)
    
    client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
    db = client[os.getenv("MONGODB_DB", "email_automation")]
    
    up(db)

