"""
Migration: Create LinkedIn automation collections

Collections created:
1. linkedin_sessions - Store LinkedIn session tokens and metadata
   - Fields: session_id, user_id, token, expires_at, created_at, last_accessed
   
2. linkedin_connections - Track LinkedIn connections made via automation
   - Fields: connection_id, lead_id, campaign_id, status, created_at, accepted_at
   
3. linkedin_messages - Store LinkedIn outreach messages
   - Fields: message_id, lead_id, connection_id, campaign_id, content, sent_at, read_at
   
4. linkedin_activities - Log all LinkedIn automation activities
   - Fields: activity_id, lead_id, action_type, status, metadata, created_at
"""

from pymongo import MongoClient
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)


def up(db):
    """
    Apply migration: Create LinkedIn collections
    
    Creates four new collections for LinkedIn automation tracking:
    - linkedin_sessions
    - linkedin_connections
    - linkedin_messages
    - linkedin_activities
    """
    logger.info("Running migration 003_create_linkedin_collections")
    
    try:
        # Create linkedin_sessions collection
        if "linkedin_sessions" not in db.list_collection_names():
            db.create_collection("linkedin_sessions")
            db.linkedin_sessions.insert_one({
                "_id": "template",
                "session_id": None,
                "user_id": None,
                "token": None,
                "expires_at": None,
                "created_at": datetime.utcnow(),
                "last_accessed": datetime.utcnow()
            })
            db.linkedin_sessions.delete_one({"_id": "template"})
            logger.info("Created linkedin_sessions collection")
        
        # Create linkedin_connections collection
        if "linkedin_connections" not in db.list_collection_names():
            db.create_collection("linkedin_connections")
            db.linkedin_connections.insert_one({
                "_id": "template",
                "connection_id": None,
                "lead_id": None,
                "campaign_id": None,
                "status": None,
                "created_at": datetime.utcnow(),
                "accepted_at": None
            })
            db.linkedin_connections.delete_one({"_id": "template"})
            logger.info("Created linkedin_connections collection")
        
        # Create linkedin_messages collection
        if "linkedin_messages" not in db.list_collection_names():
            db.create_collection("linkedin_messages")
            db.linkedin_messages.insert_one({
                "_id": "template",
                "message_id": None,
                "lead_id": None,
                "connection_id": None,
                "campaign_id": None,
                "content": None,
                "sent_at": datetime.utcnow(),
                "read_at": None
            })
            db.linkedin_messages.delete_one({"_id": "template"})
            logger.info("Created linkedin_messages collection")
        
        # Create linkedin_activities collection
        if "linkedin_activities" not in db.list_collection_names():
            db.create_collection("linkedin_activities")
            db.linkedin_activities.insert_one({
                "_id": "template",
                "activity_id": None,
                "lead_id": None,
                "action_type": None,
                "status": None,
                "metadata": {},
                "created_at": datetime.utcnow()
            })
            db.linkedin_activities.delete_one({"_id": "template"})
            logger.info("Created linkedin_activities collection")
        
        # Mark migration as complete
        db.migrations_log.update_one(
            {"migration": "003_create_linkedin_collections"},
            {"$set": {
                "migration": "003_create_linkedin_collections",
                "completed_at": datetime.utcnow(),
                "status": "success"
            }},
            upsert=True
        )
        
        logger.info("Migration 003 completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Migration 003 failed: {str(e)}")
        raise


def down(db):
    """
    Rollback migration: Drop LinkedIn collections
    """
    logger.info("Rolling back migration 003_create_linkedin_collections")
    
    try:
        collections_to_drop = [
            "linkedin_sessions",
            "linkedin_connections",
            "linkedin_messages",
            "linkedin_activities"
        ]
        
        for collection_name in collections_to_drop:
            if collection_name in db.list_collection_names():
                db.drop_collection(collection_name)
                logger.info(f"Dropped collection: {collection_name}")
        
        logger.info("Rollback 003 completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Rollback 003 failed: {str(e)}")
        raise


if __name__ == "__main__":
    from dotenv import load_dotenv
    
    load_dotenv()
    
    logging.basicConfig(level=logging.INFO)
    
    client = MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
    db = client[os.getenv("MONGODB_DB", "email_automation")]
    
    up(db)
