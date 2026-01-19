#!/usr/bin/env python3
"""
AUTO-CLASSIFICATION AGENT (Multi-Worker)
=========================================

Background agent that automatically classifies new leads as they're added.
Runs 5 parallel workers for high throughput classification.

Features:
- 5 parallel workers for concurrent classification
- Watches for pending leads and classifies them automatically
- Rate-limited to avoid API overload
- Handles retries for failed classifications
- Logs all activity for monitoring
- Graceful shutdown handling

Usage:
    python -m backend.leads.auto_classifier_agent
    
    Or as a service:
    nohup python -m backend.leads.auto_classifier_agent > /var/log/auto_classifier.log 2>&1 &
"""

import os
import sys
import time
import signal
import logging
from datetime import datetime, timedelta
from typing import Optional
from threading import Event, Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue, Empty
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

# ============== CONFIGURATION ==============

# Worker settings
NUM_WORKERS = 5  # Number of parallel classification workers
BATCH_SIZE = 50  # Fetch 50 leads at a time (10 per worker)
POLL_INTERVAL = 3  # Check for new leads every 3 seconds
RATE_LIMIT_DELAY = 0.5  # Delay between API calls per worker (seconds)
MAX_RETRIES = 3  # Max classification attempts per lead
RETRY_BACKOFF = 60  # Seconds to wait before retrying failed leads

# Logging
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/var/log/auto_classifier.log', mode='a') if os.path.exists('/var/log') else logging.StreamHandler()
    ]
)
logger = logging.getLogger('AutoClassifier')

# ============== DATABASE CONNECTION ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client['email_automation']
leads_raw_collection = db['leads_raw']
leads_enriched_collection = db['leads_enriched']
classification_logs_collection = db['lead_ai_classification_logs']
agent_stats_collection = db['auto_classifier_stats']

# ============== THREAD SAFETY ==============

stats_lock = Lock()
processing_ids = set()
processing_lock = Lock()

# ============== SHUTDOWN HANDLING ==============

shutdown_event = Event()

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_event.set()

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ============== IMPORTS (after path setup) ==============

from leads.models import LeadRaw, ClassificationStatus
from leads.ai_classifier import classify_lead as ai_classify_lead

# ============== CLASSIFICATION LOGIC ==============

def dict_to_lead_raw(doc: dict) -> LeadRaw:
    """Convert a MongoDB document to a LeadRaw model"""
    return LeadRaw(
        name=doc.get('name') or doc.get('first_name', '') + ' ' + doc.get('last_name', ''),
        title=doc.get('title') or '',
        linkedin_url=doc.get('linkedin_url') or f"email:{doc.get('email', '')}",
        snippet=doc.get('snippet') or '',
        source=doc.get('source') or 'unknown',
        first_name=doc.get('first_name'),
        last_name=doc.get('last_name'),
        email=doc.get('email'),
        email_status=doc.get('email_status'),
        location=doc.get('location'),
        company_name=doc.get('company_name'),
        company_domain=doc.get('company_domain'),
        company_website=doc.get('company_website'),
        company_employee_count=doc.get('company_employee_count'),
        company_employee_count_range=doc.get('company_employee_count_range'),
        company_founded=doc.get('company_founded'),
        company_industry=doc.get('company_industry'),
        company_type=doc.get('company_type'),
        company_headquarters=doc.get('company_headquarters'),
        company_revenue_range=doc.get('company_revenue_range'),
        company_linkedin_url=doc.get('company_linkedin_url'),
        created_at=doc.get('created_at') or datetime.utcnow(),
        classification_status=ClassificationStatus.PENDING
    )


def classify_lead(lead_doc: dict, worker_id: int = 1) -> dict:
    """
    Classify a single lead using AI.
    Returns enriched lead data with classification.
    
    Args:
        lead_doc: MongoDB document for the lead
        worker_id: Worker number (1-5) for per-worker rate limiting
    """
    lead_id = str(lead_doc['_id'])
    source = f"worker_{worker_id}"  # Use per-worker rate limit (20/min each)
    
    try:
        # Convert dict to LeadRaw model
        lead = dict_to_lead_raw(lead_doc)
        
        # Call the AI classifier with worker-specific source
        classification_result, classification_log = ai_classify_lead(lead, source=source)
        
        if classification_result and classification_log.success:
            # Update raw lead status
            leads_raw_collection.update_one(
                {'_id': lead_doc['_id']},
                {
                    '$set': {
                        'classification_status': ClassificationStatus.CLASSIFIED.value,
                        'classified_at': datetime.utcnow(),
                        'classification_attempts': lead_doc.get('classification_attempts', 0) + 1
                    }
                }
            )
            
            # Create enriched lead document
            enriched_data = {
                'raw_lead_id': lead_id,
                'linkedin_url': lead.linkedin_url,
                'name': lead.name,
                'first_name': classification_result.first_name,
                'last_name': classification_result.last_name,
                'email': lead.email,
                'title': lead.title,
                'company_name': classification_result.company_name or lead.company_name,
                'company_domain': classification_result.company_domain or lead.company_domain,
                'company_industry': classification_result.company_industry,
                'location': classification_result.inferred_location or lead.location,
                'seniority_level': classification_result.seniority_level.value if hasattr(classification_result.seniority_level, 'value') else str(classification_result.seniority_level),
                'department': classification_result.department.value if hasattr(classification_result.department, 'value') else str(classification_result.department),
                'persona': classification_result.persona.value if hasattr(classification_result.persona, 'value') else str(classification_result.persona),
                'company_size': classification_result.company_size.value if hasattr(classification_result.company_size, 'value') else str(classification_result.company_size),
                'region': classification_result.region.value if hasattr(classification_result.region, 'value') else str(classification_result.region),
                'buying_role': classification_result.buying_role.value if hasattr(classification_result.buying_role, 'value') else str(classification_result.buying_role),
                'confidence_score': classification_result.confidence_score,
                'classified_at': datetime.utcnow(),
                'source': lead_doc.get('source'),
                'stage': 'new'
            }
            
            leads_enriched_collection.update_one(
                {'raw_lead_id': lead_id},
                {'$set': enriched_data},
                upsert=True
            )
            
            # Log classification
            log_doc = classification_log.model_dump()
            log_doc['raw_lead_id'] = lead_id
            classification_logs_collection.insert_one(log_doc)
            
            return {'success': True, 'lead_id': lead_id}
        else:
            # Classification failed
            attempts = lead_doc.get('classification_attempts', 0) + 1
            new_status = ClassificationStatus.FAILED.value if attempts >= MAX_RETRIES else ClassificationStatus.PENDING.value
            
            leads_raw_collection.update_one(
                {'_id': lead_doc['_id']},
                {
                    '$set': {
                        'classification_status': new_status,
                        'classification_attempts': attempts,
                        'last_error': classification_log.error_message if classification_log else 'Unknown error',
                        'last_attempt_at': datetime.utcnow()
                    }
                }
            )
            
            return {'success': False, 'lead_id': lead_id, 'error': classification_log.error_message if classification_log else 'Unknown'}
            
    except Exception as e:
        logger.error(f"Error classifying lead {lead_id}: {e}")
        
        attempts = lead_doc.get('classification_attempts', 0) + 1
        leads_raw_collection.update_one(
            {'_id': lead_doc['_id']},
            {
                '$set': {
                    'classification_status': 'failed' if attempts >= MAX_RETRIES else 'pending',
                    'classification_attempts': attempts,
                    'last_error': str(e),
                    'last_attempt_at': datetime.utcnow()
                }
            }
        )
        
        return {'success': False, 'lead_id': lead_id, 'error': str(e)}


def get_pending_leads(batch_size: int = BATCH_SIZE) -> list:
    """
    Get pending leads that need classification.
    Prioritizes leads that haven't been attempted yet.
    """
    # First, get leads that have never been attempted
    query = {
        'classification_status': 'pending',
        '$or': [
            {'classification_attempts': {'$exists': False}},
            {'classification_attempts': 0},
            {
                'classification_attempts': {'$lt': MAX_RETRIES},
                'last_attempt_at': {'$lt': datetime.utcnow() - timedelta(seconds=RETRY_BACKOFF)}
            }
        ]
    }
    
    leads = list(leads_raw_collection.find(query).limit(batch_size))
    return leads


def process_batch() -> dict:
    """Process a batch of pending leads"""
    leads = get_pending_leads()
    
    if not leads:
        return {'processed': 0, 'success': 0, 'failed': 0}
    
    success = 0
    failed = 0
    
    for lead in leads:
        if shutdown_event.is_set():
            logger.info("Shutdown requested, stopping batch processing")
            break
        
        result = classify_lead(lead)
        
        if result['success']:
            success += 1
            logger.info(f"✅ Classified lead: {lead.get('email', lead.get('name', 'unknown'))}")
        else:
            failed += 1
            logger.warning(f"❌ Failed to classify lead: {lead.get('email', 'unknown')} - {result.get('error', 'Unknown')}")
        
        # Rate limiting per worker
        time.sleep(RATE_LIMIT_DELAY)
    
    return {'success': False, 'lead_id': lead_id, 'error': str(e)}


def get_pending_leads(batch_size: int = BATCH_SIZE) -> list:
    """
    Get pending leads that need classification.
    Uses atomic findAndModify to prevent duplicate processing.
    """
    leads = []
    
    with processing_lock:
        # Build query excluding leads already being processed
        query = {
            'classification_status': 'pending',
            '_id': {'$nin': list(processing_ids)},
            '$or': [
                {'classification_attempts': {'$exists': False}},
                {'classification_attempts': 0},
                {
                    'classification_attempts': {'$lt': MAX_RETRIES},
                    'last_attempt_at': {'$lt': datetime.utcnow() - timedelta(seconds=RETRY_BACKOFF)}
                }
            ]
        }
        
        # Fetch leads and mark as being processed
        cursor = leads_raw_collection.find(query).limit(batch_size)
        for doc in cursor:
            processing_ids.add(doc['_id'])
            leads.append(doc)
    
    return leads


def release_lead(lead_id):
    """Release a lead from the processing set"""
    with processing_lock:
        processing_ids.discard(lead_id)


def worker_classify(lead_doc: dict, worker_id: int) -> dict:
    """Worker function to classify a single lead"""
    lead_id = lead_doc['_id']
    email = lead_doc.get('email', lead_doc.get('name', 'unknown'))
    
    try:
        result = classify_lead(lead_doc, worker_id=worker_id)
        
        if result['success']:
            logger.info(f"✅ [W{worker_id}] Classified: {email}")
        else:
            logger.warning(f"❌ [W{worker_id}] Failed: {email} - {result.get('error', 'Unknown')[:50]}")
        
        return result
    finally:
        # Always release the lead from processing set
        release_lead(lead_id)
        # Rate limiting per worker
        time.sleep(RATE_LIMIT_DELAY)


def process_batch_parallel() -> dict:
    """Process a batch of pending leads using parallel workers"""
    leads = get_pending_leads()
    
    if not leads:
        return {'processed': 0, 'success': 0, 'failed': 0}
    
    success = 0
    failed = 0
    
    # Use ThreadPoolExecutor for parallel processing
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        # Submit all leads to workers
        futures = {}
        for i, lead in enumerate(leads):
            if shutdown_event.is_set():
                break
            worker_id = (i % NUM_WORKERS) + 1
            future = executor.submit(worker_classify, lead, worker_id)
            futures[future] = lead
        
        # Collect results as they complete
        for future in as_completed(futures):
            if shutdown_event.is_set():
                break
            try:
                result = future.result(timeout=60)  # 60 second timeout per lead
                if result['success']:
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                lead = futures[future]
                logger.error(f"Worker exception for {lead.get('email', 'unknown')}: {e}")
    
    return {'processed': len(leads), 'success': success, 'failed': failed}


def update_stats(stats: dict):
    """Update agent statistics in database"""
    with stats_lock:
        agent_stats_collection.update_one(
            {'agent': 'auto_classifier'},
            {
                '$set': {
                    'last_run': datetime.utcnow(),
                    'last_batch': stats,
                    'num_workers': NUM_WORKERS
                },
                '$inc': {
                    'total_processed': stats['processed'],
                    'total_success': stats['success'],
                    'total_failed': stats['failed']
                }
            },
            upsert=True
        )


def get_queue_status() -> dict:
    """Get current classification queue status"""
    pending = leads_raw_collection.count_documents({'classification_status': 'pending'})
    processing = len(processing_ids)
    classified = leads_raw_collection.count_documents({'classification_status': 'classified'})
    failed = leads_raw_collection.count_documents({'classification_status': 'failed'})
    
    return {
        'pending': pending,
        'processing': processing,
        'classified': classified,
        'failed': failed
    }


# ============== MAIN AGENT LOOP ==============

def run_agent():
    """Main agent loop - runs continuously with parallel workers"""
    logger.info("=" * 60)
    logger.info("🚀 AUTO-CLASSIFICATION AGENT STARTED (Multi-Worker)")
    logger.info("=" * 60)
    logger.info(f"Configuration:")
    logger.info(f"  - Workers: {NUM_WORKERS} parallel")
    logger.info(f"  - Batch size: {BATCH_SIZE}")
    logger.info(f"  - Poll interval: {POLL_INTERVAL}s")
    logger.info(f"  - Rate limit delay: {RATE_LIMIT_DELAY}s per worker")
    logger.info(f"  - Max retries: {MAX_RETRIES}")
    logger.info(f"  - Effective throughput: ~{NUM_WORKERS / RATE_LIMIT_DELAY:.1f} leads/sec")
    
    # Initial queue status
    status = get_queue_status()
    logger.info(f"Initial queue: {status['pending']} pending, {status['classified']} classified, {status['failed']} failed")
    
    idle_count = 0
    
    while not shutdown_event.is_set():
        try:
            # Process a batch with parallel workers
            stats = process_batch_parallel()
            
            if stats['processed'] > 0:
                idle_count = 0
                logger.info(f"📊 Batch complete: {stats['success']} success, {stats['failed']} failed (using {NUM_WORKERS} workers)")
                update_stats(stats)
                
                # Log queue status periodically
                status = get_queue_status()
                logger.info(f"📋 Queue: {status['pending']} pending, {status['classified']} classified")
            else:
                idle_count += 1
                if idle_count % 20 == 0:  # Log every minute when idle
                    status = get_queue_status()
                    logger.debug(f"💤 Idle - Queue: {status['pending']} pending")
            
            # Wait before next poll
            shutdown_event.wait(POLL_INTERVAL)
            
        except Exception as e:
            logger.error(f"Error in agent loop: {e}")
            time.sleep(10)  # Wait longer on error
    
    logger.info("🛑 AUTO-CLASSIFICATION AGENT STOPPED")


# ============== ENTRY POINT ==============

if __name__ == '__main__':
    run_agent()
