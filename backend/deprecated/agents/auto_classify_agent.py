#!/usr/bin/env python3
"""
AUTO-CLASSIFICATION AGENT
=========================
Background agent that automatically classifies new leads as they are added.
Runs continuously in parallel with the main backend.

Features:
- Monitors leads_raw collection for pending leads
- Classifies in batches for efficiency
- Rate limiting to avoid API overload
- Graceful shutdown handling
- Automatic retry for failed classifications
"""

import os
import sys
import time
import signal
import logging
from datetime import datetime, timedelta
from typing import Optional
import threading

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# ============== CONFIGURATION ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
BATCH_SIZE = 10  # Leads to classify per batch
POLL_INTERVAL = 5  # Seconds between checks for new leads
MAX_RETRIES = 3  # Max classification attempts per lead
RATE_LIMIT_DELAY = 1  # Seconds between API calls

# ============== LOGGING ==============

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [AUTO-CLASSIFY] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/var/log/auto_classify.log')
    ]
)
logger = logging.getLogger(__name__)

# ============== DATABASE CONNECTION ==============

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client['email_automation']
leads_raw_collection = db['leads_raw']
leads_enriched_collection = db['leads_enriched']
classification_logs_collection = db['lead_ai_classification_logs']
agent_state_collection = db['auto_classify_agent_state']

# ============== SHUTDOWN HANDLING ==============

shutdown_flag = threading.Event()

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signum}, shutting down...")
    shutdown_flag.set()

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# ============== AGENT STATE ==============

def get_agent_state() -> dict:
    """Get current agent state from database"""
    state = agent_state_collection.find_one({"_id": "auto_classify"})
    if not state:
        state = {
            "_id": "auto_classify",
            "status": "stopped",
            "last_run": None,
            "leads_classified_today": 0,
            "leads_classified_total": 0,
            "last_error": None,
            "started_at": None
        }
        agent_state_collection.insert_one(state)
    return state

def update_agent_state(updates: dict):
    """Update agent state in database"""
    agent_state_collection.update_one(
        {"_id": "auto_classify"},
        {"$set": updates},
        upsert=True
    )

# ============== CLASSIFICATION LOGIC ==============

def classify_lead(lead: dict) -> Optional[dict]:
    """
    Classify a single lead using OpenAI.
    Returns enriched lead data or None on failure.
    """
    from leads.ai_classifier import classify_lead as ai_classify
    
    try:
        result = ai_classify(lead)
        return result
    except Exception as e:
        logger.error(f"Classification error for {lead.get('email', 'unknown')}: {e}")
        return None

def process_pending_leads():
    """Process a batch of pending leads"""
    from leads.ai_classifier import classify_lead as ai_classify
    from leads.models import ClassificationStatus
    
    # Find pending leads that haven't exceeded max retries
    pending = list(leads_raw_collection.find({
        "classification_status": {"$in": ["pending", ClassificationStatus.PENDING.value]},
        "$or": [
            {"classification_attempts": {"$exists": False}},
            {"classification_attempts": {"$lt": MAX_RETRIES}}
        ]
    }).limit(BATCH_SIZE))
    
    if not pending:
        return 0
    
    logger.info(f"Processing {len(pending)} pending leads...")
    classified_count = 0
    
    for lead in pending:
        if shutdown_flag.is_set():
            logger.info("Shutdown requested, stopping batch processing")
            break
        
        lead_id = lead.get("_id")
        email = lead.get("email", "unknown")
        
        try:
            # Mark as processing
            leads_raw_collection.update_one(
                {"_id": lead_id},
                {
                    "$set": {"classification_status": "processing"},
                    "$inc": {"classification_attempts": 1}
                }
            )
            
            # Perform classification
            result = ai_classify(lead)
            
            if result and result.get("success"):
                # Update raw lead status
                leads_raw_collection.update_one(
                    {"_id": lead_id},
                    {"$set": {
                        "classification_status": "classified",
                        "classified_at": datetime.utcnow()
                    }}
                )
                
                # Create or update enriched lead
                enriched_data = result.get("enriched_data", {})
                enriched_data["raw_lead_id"] = str(lead_id)
                enriched_data["email"] = email
                enriched_data["name"] = lead.get("name")
                enriched_data["first_name"] = lead.get("first_name")
                enriched_data["last_name"] = lead.get("last_name")
                enriched_data["company_name"] = lead.get("company_name") or enriched_data.get("company_name")
                enriched_data["company_domain"] = lead.get("company_domain")
                enriched_data["linkedin_url"] = lead.get("linkedin_url")
                enriched_data["title"] = lead.get("title")
                enriched_data["source"] = lead.get("source")
                enriched_data["classified_at"] = datetime.utcnow()
                enriched_data["stage"] = "new"
                
                # Upsert enriched lead
                leads_enriched_collection.update_one(
                    {"raw_lead_id": str(lead_id)},
                    {"$set": enriched_data},
                    upsert=True
                )
                
                classified_count += 1
                logger.info(f"✓ Classified: {email} -> {enriched_data.get('persona', 'unknown')}")
                
            else:
                # Classification failed
                error_msg = result.get("error", "Unknown error") if result else "No result"
                attempts = lead.get("classification_attempts", 0) + 1
                
                if attempts >= MAX_RETRIES:
                    leads_raw_collection.update_one(
                        {"_id": lead_id},
                        {"$set": {
                            "classification_status": "failed",
                            "classification_error": error_msg,
                            "failed_at": datetime.utcnow()
                        }}
                    )
                    logger.warning(f"✗ Failed (max retries): {email} - {error_msg}")
                else:
                    leads_raw_collection.update_one(
                        {"_id": lead_id},
                        {"$set": {
                            "classification_status": "pending",
                            "last_error": error_msg
                        }}
                    )
                    logger.warning(f"⟳ Retry queued: {email} - {error_msg}")
            
            # Rate limiting
            time.sleep(RATE_LIMIT_DELAY)
            
        except Exception as e:
            logger.error(f"Error processing {email}: {e}")
            leads_raw_collection.update_one(
                {"_id": lead_id},
                {"$set": {
                    "classification_status": "pending",
                    "last_error": str(e)
                }}
            )
    
    return classified_count

def run_agent():
    """Main agent loop"""
    logger.info("=" * 50)
    logger.info("AUTO-CLASSIFICATION AGENT STARTING")
    logger.info("=" * 50)
    
    # Update state
    update_agent_state({
        "status": "running",
        "started_at": datetime.utcnow(),
        "last_error": None
    })
    
    total_classified = 0
    
    try:
        while not shutdown_flag.is_set():
            try:
                # Get pending count
                pending_count = leads_raw_collection.count_documents({
                    "classification_status": {"$in": ["pending", "PENDING"]},
                    "$or": [
                        {"classification_attempts": {"$exists": False}},
                        {"classification_attempts": {"$lt": MAX_RETRIES}}
                    ]
                })
                
                if pending_count > 0:
                    logger.info(f"Found {pending_count} pending leads")
                    classified = process_pending_leads()
                    total_classified += classified
                    
                    # Update state
                    update_agent_state({
                        "last_run": datetime.utcnow(),
                        "leads_classified_today": total_classified,
                        "$inc": {"leads_classified_total": classified}
                    })
                else:
                    logger.debug("No pending leads, waiting...")
                
                # Wait before next poll
                shutdown_flag.wait(timeout=POLL_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                update_agent_state({"last_error": str(e)})
                time.sleep(POLL_INTERVAL * 2)  # Back off on error
                
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        update_agent_state({
            "status": "stopped",
            "stopped_at": datetime.utcnow()
        })
        logger.info(f"Agent stopped. Total classified this session: {total_classified}")

# ============== ENTRY POINT ==============

if __name__ == "__main__":
    run_agent()
