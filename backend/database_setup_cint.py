"""
Cint Integration - MongoDB Setup

Creates and indexes MongoDB collections for:
- cint_research database:
  - cint_surveys: Opportunity feed cache
  - cint_entry_links: Entry link storage
  - cint_settings: Integration settings
  - cint_filters: User filter preferences
  - cint_metrics: Performance metrics

- survey_allocation database (shared):
  - respondents: Extended for Cint respondents
  - surveys: Extended survey inventory
  - survey_metrics: Extended metrics
"""

from pymongo import MongoClient, ASCENDING, DESCENDING, TEXT
from pymongo.errors import CollectionInvalid, OperationFailure
import logging

logger = logging.getLogger(__name__)


def setup_cint_database(mongo_uri: str, db_name: str = "cint_research") -> dict:
    """
    Create and index Cint integration database
    
    Args:
        mongo_uri: MongoDB connection URI
        db_name: Database name (default: "cint_research")
    
    Returns:
        Dictionary with collection references
    """
    client = MongoClient(mongo_uri)
    db = client[db_name]
    
    collections = {}
    
    # ============================================
    # cint_surveys collection
    # ============================================
    try:
        collections["cint_surveys"] = db["cint_surveys"]
        
        # Create indexes
        db["cint_surveys"].create_index([("survey_id", ASCENDING)], unique=True)
        db["cint_surveys"].create_index([("is_active", ASCENDING)])
        db["cint_surveys"].create_index([("is_live", ASCENDING)])
        db["cint_surveys"].create_index([("country_language", ASCENDING)])
        db["cint_surveys"].create_index([("buyer_id", ASCENDING)])
        db["cint_surveys"].create_index([("message_reason", ASCENDING)])
        db["cint_surveys"].create_index([("received_at", DESCENDING)])
        db["cint_surveys"].create_index([("total_remaining", ASCENDING)])  # For quota monitoring
        db["cint_surveys"].create_index(
            [("survey_id", ASCENDING), ("is_active", ASCENDING)]
        )
        
        logger.info("✓ cint_surveys collection created and indexed")
    except OperationFailure as e:
        logger.warning(f"cint_surveys collection already exists: {e}")
    except Exception as e:
        logger.error(f"Error creating cint_surveys: {e}")
    
    # ============================================
    # cint_entry_links collection
    # ============================================
    try:
        collections["cint_entry_links"] = db["cint_entry_links"]
        
        # Create indexes
        db["cint_entry_links"].create_index([("survey_id", ASCENDING)], unique=True)
        db["cint_entry_links"].create_index([("created_at", DESCENDING)])
        db["cint_entry_links"].create_index([("updated_at", DESCENDING)])
        
        logger.info("✓ cint_entry_links collection created and indexed")
    except OperationFailure as e:
        logger.warning(f"cint_entry_links collection already exists: {e}")
    except Exception as e:
        logger.error(f"Error creating cint_entry_links: {e}")
    
    # ============================================
    # cint_settings collection
    # ============================================
    try:
        collections["cint_settings"] = db["cint_settings"]
        
        # Create indexes
        db["cint_settings"].create_index([("user_id", ASCENDING)])
        db["cint_settings"].create_index([("supplier_code", ASCENDING)])
        db["cint_settings"].create_index([("is_active", ASCENDING)])
        
        logger.info("✓ cint_settings collection created and indexed")
    except OperationFailure as e:
        logger.warning(f"cint_settings collection already exists: {e}")
    except Exception as e:
        logger.error(f"Error creating cint_settings: {e}")
    
    # ============================================
    # cint_filters collection
    # ============================================
    try:
        collections["cint_filters"] = db["cint_filters"]
        
        # Create indexes
        db["cint_filters"].create_index([("user_id", ASCENDING)])
        db["cint_filters"].create_index([("name", ASCENDING)])
        
        logger.info("✓ cint_filters collection created and indexed")
    except OperationFailure as e:
        logger.warning(f"cint_filters collection already exists: {e}")
    except Exception as e:
        logger.error(f"Error creating cint_filters: {e}")
    
    # ============================================
    # cint_metrics collection
    # ============================================
    try:
        collections["cint_metrics"] = db["cint_metrics"]
        
        # Create indexes
        db["cint_metrics"].create_index([("survey_id", ASCENDING)], unique=True)
        db["cint_metrics"].create_index([("last_updated", DESCENDING)])
        db["cint_metrics"].create_index([("last_allocation", DESCENDING)])
        
        logger.info("✓ cint_metrics collection created and indexed")
    except OperationFailure as e:
        logger.warning(f"cint_metrics collection already exists: {e}")
    except Exception as e:
        logger.error(f"Error creating cint_metrics: {e}")
    
    # ============================================
    # cint_subscriptions collection
    # ============================================
    try:
        collections["cint_subscriptions"] = db["cint_subscriptions"]
        
        # Create indexes
        db["cint_subscriptions"].create_index([("supplier_code", ASCENDING)], unique=True)
        db["cint_subscriptions"].create_index([("status", ASCENDING)])
        db["cint_subscriptions"].create_index([("last_webhook_received_at", DESCENDING)])
        
        logger.info("✓ cint_subscriptions collection created and indexed")
    except OperationFailure as e:
        logger.warning(f"cint_subscriptions collection already exists: {e}")
    except Exception as e:
        logger.error(f"Error creating cint_subscriptions: {e}")
    
    # ============================================
    # cint_respondent_outcomes collection
    # ============================================
    try:
        collections["cint_respondent_outcomes"] = db["cint_respondent_outcomes"]
        
        # Create indexes
        db["cint_respondent_outcomes"].create_index([("respondent_id", ASCENDING)])
        db["cint_respondent_outcomes"].create_index([("session_id", ASCENDING)], unique=True)
        db["cint_respondent_outcomes"].create_index([("survey_id", ASCENDING)])
        db["cint_respondent_outcomes"].create_index([("marketplace_status", ASCENDING)])
        db["cint_respondent_outcomes"].create_index([("client_status", ASCENDING)])
        db["cint_respondent_outcomes"].create_index([("received_at", DESCENDING)])
        db["cint_respondent_outcomes"].create_index(
            [("entry_date", DESCENDING), ("last_date", DESCENDING)]
        )
        
        logger.info("✓ cint_respondent_outcomes collection created and indexed")
    except OperationFailure as e:
        logger.warning(f"cint_respondent_outcomes collection already exists: {e}")
    except Exception as e:
        logger.error(f"Error creating cint_respondent_outcomes: {e}")
    
    logger.info("Cint database setup complete")
    return collections


def setup_survey_allocation_extensions(mongo_uri: str, db_name: str = "survey_allocation") -> dict:
    """
    Set up extensions to survey_allocation database for Cint support
    
    Args:
        mongo_uri: MongoDB connection URI
        db_name: Database name (default: "survey_allocation")
    
    Returns:
        Dictionary with collection references
    """
    client = MongoClient(mongo_uri)
    db = client[db_name]
    
    collections = {}
    
    # ============================================
    # respondents collection (extended for Cint)
    # ============================================
    try:
        collections["respondents"] = db["respondents"]
        
        # Add index for Cint-specific fields
        db["respondents"].create_index([("provider", ASCENDING)])  # Track which provider
        db["respondents"].create_index([("supplier_code", ASCENDING)])  # Cint supplier code
        
        logger.info("✓ respondents collection extended for Cint")
    except OperationFailure as e:
        logger.warning(f"respondents collection setup: {e}")
    except Exception as e:
        logger.error(f"Error extending respondents collection: {e}")
    
    # ============================================
    # surveys collection (extended for multi-provider)
    # ============================================
    try:
        collections["surveys"] = db["surveys"]
        
        # Add multi-provider indexes
        db["surveys"].create_index([("provider", ASCENDING)])
        db["surveys"].create_index([("provider", ASCENDING), ("external_id", ASCENDING)])
        db["surveys"].create_index([("provider", ASCENDING), ("is_active", ASCENDING)])
        
        logger.info("✓ surveys collection extended for multi-provider")
    except OperationFailure as e:
        logger.warning(f"surveys collection setup: {e}")
    except Exception as e:
        logger.error(f"Error extending surveys collection: {e}")
    
    # ============================================
    # survey_metrics collection
    # ============================================
    try:
        collections["survey_metrics"] = db["survey_metrics"]
        
        # Ensure time-series indexes for real-time metrics
        db["survey_metrics"].create_index([("survey_id", ASCENDING)])
        db["survey_metrics"].create_index([("provider", ASCENDING)])
        db["survey_metrics"].create_index([("last_updated", DESCENDING)])
        
        logger.info("✓ survey_metrics collection verified")
    except OperationFailure as e:
        logger.warning(f"survey_metrics collection setup: {e}")
    except Exception as e:
        logger.error(f"Error with survey_metrics collection: {e}")
    
    # ============================================
    # allocation_log collection (new, for audit trail)
    # ============================================
    try:
        collections["allocation_log"] = db["allocation_log"]
        
        # Create indexes for querying allocation history
        db["allocation_log"].create_index([("respondent_id", ASCENDING)])
        db["allocation_log"].create_index([("survey_id", ASCENDING)])
        db["allocation_log"].create_index([("provider", ASCENDING)])
        db["allocation_log"].create_index([("timestamp", DESCENDING)])
        db["allocation_log"].create_index([("status", ASCENDING)])
        
        # TTL index to auto-delete old logs (30 days)
        db["allocation_log"].create_index(
            [("timestamp", ASCENDING)],
            expireAfterSeconds=30 * 24 * 60 * 60
        )
        
        logger.info("✓ allocation_log collection created")
    except OperationFailure as e:
        logger.warning(f"allocation_log collection setup: {e}")
    except Exception as e:
        logger.error(f"Error creating allocation_log collection: {e}")
    
    logger.info("Survey allocation database extensions complete")
    return collections


def create_sample_documents(collections: dict) -> None:
    """
    Create sample documents for testing (if collections are empty)
    
    Args:
        collections: Dictionary of MongoDB collections
    """
    try:
        # Sample Cint survey opportunity
        if collections.get("cint_surveys") and collections["cint_surveys"].count_documents({}) == 0:
            sample_survey = {
                "survey_id": 123456,
                "survey_name": "Sample Survey",
                "account_name": "Test Account",
                "buyer_id": 789,
                "country_language": "eng_us",
                "industry": "technology",
                "study_type": "adhoc",
                "bid_length_of_interview": 10,
                "bid_incidence": 50.0,
                "collects_pii": False,
                "revenue_per_interview": {"value": 1.50, "currency_code": "USD"},
                "conversion": 0.65,
                "mobile_conversion": 0.50,
                "length_of_interview": 12,
                "total_remaining": 100,
                "is_live": True,
                "message_reason": "new",
                "is_active": True,
            }
            collections["cint_surveys"].insert_one(sample_survey)
            logger.info("✓ Sample survey document created")
        
        # Sample entry link
        if collections.get("cint_entry_links") and collections["cint_entry_links"].count_documents({}) == 0:
            sample_link = {
                "survey_id": 123456,
                "supplier_link_type_code": "OWS",
                "tracking_type_code": "NONE",
                "live_link": "https://samplicio.us/s/default.aspx?SID=abc123&PID=",
                "test_link": "https://samplicio.us/s/default.aspx?SID=test456&SUMSTAT=1&PID=test",
                "rpi": {"value": 1.50, "currency_code": "USD"},
            }
            collections["cint_entry_links"].insert_one(sample_link)
            logger.info("✓ Sample entry link document created")
    
    except Exception as e:
        logger.warning(f"Could not create sample documents: {e}")


if __name__ == "__main__":
    # For manual setup
    mongo_uri = "mongodb://localhost:27017"
    
    cint_collections = setup_cint_database(mongo_uri)
    survey_collections = setup_survey_allocation_extensions(mongo_uri)
    
    print("✓ All collections created successfully")
