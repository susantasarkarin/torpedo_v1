"""
LinkedIn Automation Database Setup
Initializes MongoDB collections and indexes for LinkedIn automation.
"""

import logging
from database import DatabaseManager

logger = logging.getLogger(__name__)


def setup_linkedin_collections():
    """Setup MongoDB collections and indexes for LinkedIn automation"""
    try:
        db_manager = DatabaseManager()
        db_name = "linkedin_db"
        
        # Get collections
        accounts_collection = db_manager.get_collection(db_name, "accounts")
        jobs_collection = db_manager.get_collection(db_name, "automation_jobs")
        
        # Create indexes for accounts collection
        accounts_collection.create_index("email", unique=True)
        accounts_collection.create_index("account_name")
        accounts_collection.create_index("active")
        accounts_collection.create_index("created_at")
        accounts_collection.create_index("last_run")
        
        logger.info("✓ LinkedIn accounts collection indexes created")
        
        # Create indexes for jobs collection
        jobs_collection.create_index("account_id")
        jobs_collection.create_index([("account_id", 1), ("started_at", -1)])
        jobs_collection.create_index("status")
        jobs_collection.create_index("started_at")
        jobs_collection.create_index([("account_id", 1), ("status", 1)])
        
        # TTL index to auto-delete old jobs after 90 days
        try:
            jobs_collection.create_index("started_at", expireAfterSeconds=7776000)
        except Exception as e:
            logger.warning(f"Could not create TTL index: {e}")
        
        logger.info("✓ LinkedIn jobs collection indexes created")
        
        # Verify collections exist
        collections = db_manager.get_database(db_name).list_collection_names()
        assert "accounts" in collections, "Accounts collection not found"
        assert "automation_jobs" in collections, "Jobs collection not found"
        
        logger.info("✓ LinkedIn automation database setup completed successfully")
        return True
    
    except Exception as e:
        logger.error(f"Error setting up LinkedIn collections: {str(e)}")
        raise


def initialize_linkedin_module():
    """Initialize LinkedIn automation module on startup"""
    try:
        setup_linkedin_collections()
        logger.info("✓ LinkedIn Automation module initialized")
    except Exception as e:
        logger.error(f"Failed to initialize LinkedIn Automation module: {e}")
        # Don't raise - let the app continue even if LinkedIn setup fails
