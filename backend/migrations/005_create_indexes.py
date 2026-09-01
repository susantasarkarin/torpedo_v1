"""
Migration: Create indexes for optimal query performance

Indexes created:
LEADS collection:
- engagement_score, engagement_status, reengagement_eligible, linkedin_connection_status
- last_outreach_date, sequence_stage
- Compound: (campaign_id, engagement_status, last_outreach_date)

CAMPAIGNS collection:
- campaign_type, personalization_level
- Compound: (ab_test_config.enabled, reengagement_timeline.days_before_reengagement)

LINKEDIN collections:
- linkedin_sessions: (user_id, expires_at)
- linkedin_connections: (lead_id, status, created_at)
- linkedin_messages: (lead_id, campaign_id, sent_at)
- linkedin_activities: (lead_id, action_type, created_at)

DELIVERABILITY collections:
- domain_health: (domain, status, last_updated)
- gmail_account_usage: (email, status, sent_today)
- reputation_metrics: (metric_type, domain, timestamp)
"""

from pymongo import MongoClient, ASCENDING, DESCENDING
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)


def up(db):
    """
    Apply migration: Create performance indexes
    
    Creates compound and single field indexes for optimal query performance
    across all relevant collections.
    """
    logger.info("Running migration 005_create_indexes")
    
    try:
        # LEADS collection indexes
        logger.info("Creating indexes for leads collection...")
        db.leads.create_index([("engagement_score", DESCENDING)])
        db.leads.create_index([("engagement_status", ASCENDING)])
        db.leads.create_index([("reengagement_eligible", ASCENDING)])
        db.leads.create_index([("linkedin_connection_status", ASCENDING)])
        db.leads.create_index([("last_outreach_date", DESCENDING)])
        db.leads.create_index([("sequence_stage", ASCENDING)])
        db.leads.create_index([
            ("campaign_id", ASCENDING),
            ("engagement_status", ASCENDING),
            ("last_outreach_date", DESCENDING)
        ])
        db.leads.create_index([("timezone", ASCENDING)])
        logger.info("Leads indexes created")
        
        # CAMPAIGNS collection indexes
        logger.info("Creating indexes for campaigns collection...")
        db.campaigns.create_index([("campaign_type", ASCENDING)])
        db.campaigns.create_index([("personalization_level", ASCENDING)])
        db.campaigns.create_index([
            ("ab_test_config.enabled", ASCENDING),
            ("reengagement_timeline.days_before_reengagement", ASCENDING)
        ])
        db.campaigns.create_index([("multi_channel_enabled", ASCENDING)])
        logger.info("Campaigns indexes created")
        
        # LINKEDIN_SESSIONS indexes
        logger.info("Creating indexes for linkedin_sessions collection...")
        db.linkedin_sessions.create_index([
            ("user_id", ASCENDING),
            ("expires_at", ASCENDING)
        ])
        db.linkedin_sessions.create_index([("created_at", DESCENDING)])
        logger.info("LinkedIn sessions indexes created")
        
        # LINKEDIN_CONNECTIONS indexes
        logger.info("Creating indexes for linkedin_connections collection...")
        db.linkedin_connections.create_index([("lead_id", ASCENDING)])
        db.linkedin_connections.create_index([("status", ASCENDING)])
        db.linkedin_connections.create_index([
            ("lead_id", ASCENDING),
            ("status", ASCENDING),
            ("created_at", DESCENDING)
        ])
        db.linkedin_connections.create_index([("campaign_id", ASCENDING)])
        logger.info("LinkedIn connections indexes created")
        
        # LINKEDIN_MESSAGES indexes
        logger.info("Creating indexes for linkedin_messages collection...")
        db.linkedin_messages.create_index([("lead_id", ASCENDING)])
        db.linkedin_messages.create_index([("campaign_id", ASCENDING)])
        db.linkedin_messages.create_index([
            ("lead_id", ASCENDING),
            ("sent_at", DESCENDING)
        ])
        db.linkedin_messages.create_index([("sent_at", DESCENDING)])
        logger.info("LinkedIn messages indexes created")
        
        # LINKEDIN_ACTIVITIES indexes
        logger.info("Creating indexes for linkedin_activities collection...")
        db.linkedin_activities.create_index([("lead_id", ASCENDING)])
        db.linkedin_activities.create_index([("action_type", ASCENDING)])
        db.linkedin_activities.create_index([
            ("lead_id", ASCENDING),
            ("action_type", ASCENDING),
            ("created_at", DESCENDING)
        ])
        db.linkedin_activities.create_index([("status", ASCENDING)])
        logger.info("LinkedIn activities indexes created")
        
        # DOMAIN_HEALTH indexes
        logger.info("Creating indexes for domain_health collection...")
        db.domain_health.create_index([("domain", ASCENDING)])
        db.domain_health.create_index([("status", ASCENDING)])
        db.domain_health.create_index([
            ("domain", ASCENDING),
            ("status", ASCENDING),
            ("last_updated", DESCENDING)
        ])
        logger.info("Domain health indexes created")
        
        # GMAIL_ACCOUNT_USAGE indexes
        logger.info("Creating indexes for gmail_account_usage collection...")
        db.gmail_account_usage.create_index([("email", ASCENDING)])
        db.gmail_account_usage.create_index([("status", ASCENDING)])
        db.gmail_account_usage.create_index([
            ("email", ASCENDING),
            ("status", ASCENDING),
            ("updated_at", DESCENDING)
        ])
        db.gmail_account_usage.create_index([("account_health", ASCENDING)])
        logger.info("Gmail account usage indexes created")
        
        # REPUTATION_METRICS indexes
        logger.info("Creating indexes for reputation_metrics collection...")
        db.reputation_metrics.create_index([("metric_type", ASCENDING)])
        db.reputation_metrics.create_index([("domain", ASCENDING)])
        db.reputation_metrics.create_index([("account_id", ASCENDING)])
        db.reputation_metrics.create_index([
            ("metric_type", ASCENDING),
            ("domain", ASCENDING),
            ("timestamp", DESCENDING)
        ])
        db.reputation_metrics.create_index([("timestamp", DESCENDING)])
        logger.info("Reputation metrics indexes created")
        
        # Mark migration as complete
        db.migrations_log.update_one(
            {"migration": "005_create_indexes"},
            {"$set": {
                "migration": "005_create_indexes",
                "completed_at": datetime.utcnow(),
                "status": "success"
            }},
            upsert=True
        )
        
        logger.info("Migration 005 completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Migration 005 failed: {str(e)}")
        raise


def down(db):
    """
    Rollback migration: Drop all custom indexes
    
    Note: Does not drop the default _id index
    """
    logger.info("Rolling back migration 005_create_indexes")
    
    try:
        collections = [
            "leads",
            "campaigns",
            "linkedin_sessions",
            "linkedin_connections",
            "linkedin_messages",
            "linkedin_activities",
            "domain_health",
            "gmail_account_usage",
            "reputation_metrics"
        ]
        
        for collection_name in collections:
            if collection_name in db.list_collection_names():
                collection = db[collection_name]
                # Get all indexes except _id
                indexes = collection.list_indexes()
                for index in indexes:
                    if index['name'] != '_id_':
                        collection.drop_index(index['name'])
                        logger.info(f"Dropped index: {index['name']} from {collection_name}")
        
        logger.info("Rollback 005 completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Rollback 005 failed: {str(e)}")
        raise


if __name__ == "__main__":
    from dotenv import load_dotenv
    
    load_dotenv()
    
    logging.basicConfig(level=logging.INFO)
    
    client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
    db = client[os.getenv("MONGODB_DB", "email_automation")]
    
    up(db)

