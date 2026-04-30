"""
Migration: Add multi-channel and A/B testing fields to campaigns

Fields added to campaigns:
- campaign_type: str - Type of campaign (email, linkedin, multi_channel)
- personalization_level: str - Level of personalization (minimal, medium, advanced)
- ab_test_config: dict - A/B testing configuration
  - enabled: bool
  - variant_a_id: str
  - variant_b_id: str
  - test_percentage: float
  - metrics_to_track: list
- reengagement_timeline: dict - Timeline settings for reengagement
  - days_before_reengagement: int
  - max_reengagement_attempts: int

Fields added to campaign.sequence_steps (array elements):
- channel: str - Channel for this step (email, linkedin, sms, etc.)
- condition_type: str - Condition type (timing, engagement, response, etc.)
- wait_days: int - Days to wait before this step
"""

from pymongo import MongoClient
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)


def up(db):
    """
    Apply migration: Add campaign enhancement fields
    
    Adds multi-channel and A/B testing configuration fields to campaigns
    and enhances sequence steps with channel and condition information.
    """
    logger.info("Running migration 002_add_campaign_fields")
    
    try:
        # Add campaign-level fields
        campaign_result = db.campaigns.update_many(
            {"campaign_type": {"$exists": False}},
            {"$set": {
                "campaign_type": "email",
                "personalization_level": "minimal",
                "ab_test_config": {
                    "enabled": False,
                    "variant_a_id": None,
                    "variant_b_id": None,
                    "test_percentage": 0.0,
                    "metrics_to_track": []
                },
                "reengagement_timeline": {
                    "days_before_reengagement": 14,
                    "max_reengagement_attempts": 3
                },
                "multi_channel_enabled": False,
                "migration_002_applied": True,
                "migration_002_date": datetime.utcnow()
            }}
        )
        
        logger.info(f"Added campaign fields: {campaign_result.modified_count} documents updated")
        
        # Enhance sequence steps with channel info
        # Initialize channel and condition_type for existing steps
        db.campaigns.update_many(
            {"sequence_steps": {"$exists": True}},
            {"$set": {
                "sequence_steps.$[elem].channel": "email",
                "sequence_steps.$[elem].condition_type": "timing",
                "sequence_steps.$[elem].wait_days": 0
            }},
            array_filters=[{"elem": {}}],
            upsert=False
        )
        
        logger.info("Migration 002 completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Migration 002 failed: {str(e)}")
        raise


def down(db):
    """
    Rollback migration: Remove campaign enhancement fields
    """
    logger.info("Rolling back migration 002_add_campaign_fields")
    
    try:
        # Remove campaign-level fields
        result = db.campaigns.update_many(
            {},
            {"$unset": {
                "campaign_type": "",
                "personalization_level": "",
                "ab_test_config": "",
                "reengagement_timeline": "",
                "multi_channel_enabled": "",
                "migration_002_applied": "",
                "migration_002_date": ""
            }}
        )
        
        # Remove channel fields from sequence steps
        db.campaigns.update_many(
            {"sequence_steps": {"$exists": True}},
            {"$unset": {
                "sequence_steps.$[elem].channel": "",
                "sequence_steps.$[elem].condition_type": "",
                "sequence_steps.$[elem].wait_days": ""
            }},
            array_filters=[{"elem": {}}]
        )
        
        logger.info(f"Rollback 002 completed: Modified {result.modified_count} documents")
        return True
        
    except Exception as e:
        logger.error(f"Rollback 002 failed: {str(e)}")
        raise


if __name__ == "__main__":
    from dotenv import load_dotenv
    
    load_dotenv()
    
    logging.basicConfig(level=logging.INFO)
    
    client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
    db = client[os.getenv("MONGODB_DB", "email_automation")]
    
    up(db)

