"""
Migration: Add engagement tracking fields to leads collection

Fields added:
- engagement_score: float - Numeric score for lead engagement level
- engagement_status: str - Current engagement status (active, inactive, cold, etc.)
- sequence_stage: str - Current stage in the outreach sequence
- last_outreach_date: datetime - Date of last contact
- outreach_history: list - Array of outreach attempts
- reengagement_eligible: bool - Whether lead can be reengaged
- reengagement_pool_date: datetime - When lead was moved to reengagement pool
- timezone: str - Lead's timezone
- linkedin_connection_status: str - LinkedIn connection status (connected, pending, none)
- linkedin_connection_date: datetime - Date connection was established
- linkedin_last_message_date: datetime - Last LinkedIn message date
- reply_sentiment: str - Sentiment of last reply (positive, neutral, negative)
"""

from pymongo import MongoClient
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)


def up(db):
    """
    Apply migration: Add engagement tracking fields to leads collection
    
    This operation is idempotent - it only adds missing fields and leaves
    existing data intact.
    """
    logger.info("Running migration 001_add_engagement_fields")
    
    try:
        # Add engagement tracking fields with default values
        # Using conditional check to make it idempotent
        result = db.leads.update_many(
            {"engagement_score": {"$exists": False}},
            {"$set": {
                "engagement_score": 0.0,
                "engagement_status": None,
                "sequence_stage": None,
                "last_outreach_date": None,
                "outreach_history": [],
                "reengagement_eligible": False,
                "reengagement_pool_date": None,
                "timezone": None,
                "linkedin_connection_status": None,
                "linkedin_connection_date": None,
                "linkedin_last_message_date": None,
                "reply_sentiment": None,
                "migration_001_applied": True,
                "migration_001_date": datetime.utcnow()
            }}
        )
        
        logger.info(
            f"Migration 001 completed: Updated {result.modified_count} leads, "
            f"matched {result.matched_count} documents"
        )
        return True
        
    except Exception as e:
        logger.error(f"Migration 001 failed: {str(e)}")
        raise


def down(db):
    """
    Rollback migration: Remove engagement tracking fields from leads collection
    """
    logger.info("Rolling back migration 001_add_engagement_fields")
    
    try:
        result = db.leads.update_many(
            {},
            {"$unset": {
                "engagement_score": "",
                "engagement_status": "",
                "sequence_stage": "",
                "last_outreach_date": "",
                "outreach_history": "",
                "reengagement_eligible": "",
                "reengagement_pool_date": "",
                "timezone": "",
                "linkedin_connection_status": "",
                "linkedin_connection_date": "",
                "linkedin_last_message_date": "",
                "reply_sentiment": "",
                "migration_001_applied": "",
                "migration_001_date": ""
            }}
        )
        
        logger.info(f"Rollback 001 completed: Modified {result.modified_count} documents")
        return True
        
    except Exception as e:
        logger.error(f"Rollback 001 failed: {str(e)}")
        raise


if __name__ == "__main__":
    # For testing individual migration
    from dotenv import load_dotenv
    
    load_dotenv()
    
    logging.basicConfig(level=logging.INFO)
    
    client = MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
    db = client[os.getenv("MONGODB_DB", "email_automation")]
    
    up(db)
