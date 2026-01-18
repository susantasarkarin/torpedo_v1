"""
AI Processing Celery Tasks
Background tasks for AI agent processing
"""

import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from backend.celery_app import celery_app
from backend.db_pools import get_ai_db, get_ai_collection

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name='backend.tasks.ai_tasks.process_email_with_agent1',
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    rate_limit='10/m',  # Rate limit for API quota
)
def process_email_with_agent1(
    self,
    lead_id: str,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Process a single email/lead with Agent 1 (Summary + Contact Extraction).
    
    Args:
        lead_id: MongoDB ObjectId of the lead to process
        force_refresh: Force re-processing even if already processed
        
    Returns:
        Processing result with summary and extracted contact info
    """
    from bson import ObjectId
    from backend.leads.ai_email_agents import (
        agent1_process_email_thread,
        email_leads_collection as default_leads_collection
    )
    
    task_id = self.request.id
    
    # Use AI pool for database operations
    leads_collection = get_ai_collection('email_leads')
    summaries_collection = get_ai_collection('ai_summaries')
    
    try:
        # Get the lead
        lead = leads_collection.find_one({"_id": ObjectId(lead_id)})
        
        if not lead:
            return {
                'status': 'error',
                'error': f'Lead not found: {lead_id}',
                'task_id': task_id
            }
        
        # Check if already processed
        if not force_refresh:
            existing = summaries_collection.find_one({"lead_id": lead_id})
            if existing:
                return {
                    'status': 'already_processed',
                    'lead_id': lead_id,
                    'summary_id': str(existing['_id']),
                    'task_id': task_id
                }
        
        # Update task state
        self.update_state(
            state='PROGRESS',
            meta={
                'lead_id': lead_id,
                'stage': 'processing_with_agent1',
                'email': lead.get('email', 'unknown')
            }
        )
        
        # Build email list for thread processing
        emails = []
        if lead.get('emails'):
            emails = lead['emails']
        else:
            # Single email format
            emails = [{
                'subject': lead.get('subject', ''),
                'body': lead.get('body', lead.get('snippet', '')),
                'from_email': lead.get('email', ''),
                'from_name': lead.get('name', ''),
                'date': lead.get('date'),
                'direction': lead.get('direction', 'received')
            }]
        
        # Process with Agent 1
        result = agent1_process_email_thread(emails, account_email=lead.get('account_email'))
        
        if result.get('success'):
            # Store the summary
            summary_doc = {
                'lead_id': lead_id,
                'account_email': lead.get('account_email'),
                'summary': result.get('summary', ''),
                'contact': result.get('contact', {}),
                'intent': result.get('intent'),
                'urgency': result.get('urgency'),
                'key_points': result.get('key_points', []),
                'action_items': result.get('action_items', []),
                'confidence_score': result.get('confidence_score', 0),
                'processed_at': datetime.utcnow(),
                'task_id': task_id,
                'model_used': result.get('model_used', 'gemini-flash')
            }
            
            # Upsert summary
            summaries_collection.update_one(
                {"lead_id": lead_id},
                {"$set": summary_doc},
                upsert=True
            )
            
            # Update lead with summary flag
            leads_collection.update_one(
                {"_id": ObjectId(lead_id)},
                {"$set": {
                    "ai_processed": True,
                    "ai_processed_at": datetime.utcnow(),
                    "ai_summary": result.get('summary', '')[:500]  # Store preview
                }}
            )
            
            return {
                'status': 'success',
                'lead_id': lead_id,
                'summary_preview': result.get('summary', '')[:200],
                'contact_extracted': bool(result.get('contact', {}).get('email')),
                'task_id': task_id
            }
        else:
            return {
                'status': 'error',
                'lead_id': lead_id,
                'error': result.get('error', 'Unknown error'),
                'task_id': task_id
            }
            
    except Exception as e:
        logger.error(f"Error processing lead {lead_id} with Agent 1: {e}")
        raise


@celery_app.task(
    bind=True,
    name='backend.tasks.ai_tasks.categorize_batch_with_agent2',
    max_retries=2,
    default_retry_delay=60,
    rate_limit='5/m',  # Fewer calls since batch processing
)
def categorize_batch_with_agent2(
    self,
    summary_ids: List[str],
    batch_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Categorize a batch of summaries with Agent 2.
    
    Args:
        summary_ids: List of summary ObjectIds to categorize
        batch_name: Optional name for this categorization run
        
    Returns:
        Categorization results with assigned buckets
    """
    from bson import ObjectId
    from backend.leads.ai_email_agents import agent2_categorize_batch
    
    task_id = self.request.id
    
    # Use AI pool
    summaries_collection = get_ai_collection('ai_summaries')
    categories_collection = get_ai_collection('ai_categories')
    runs_collection = get_ai_collection('categorization_runs')
    
    try:
        # Get summaries
        summaries = list(summaries_collection.find({
            "_id": {"$in": [ObjectId(sid) for sid in summary_ids]}
        }))
        
        if not summaries:
            return {
                'status': 'error',
                'error': 'No summaries found',
                'task_id': task_id
            }
        
        # Update task state
        self.update_state(
            state='PROGRESS',
            meta={
                'stage': 'categorizing',
                'summary_count': len(summaries)
            }
        )
        
        # Build input for Agent 2
        summary_texts = []
        for s in summaries:
            summary_texts.append({
                'id': str(s['_id']),
                'lead_id': s.get('lead_id'),
                'summary': s.get('summary', ''),
                'intent': s.get('intent'),
                'urgency': s.get('urgency'),
                'key_points': s.get('key_points', [])
            })
        
        # Process with Agent 2
        result = agent2_categorize_batch(summary_texts)
        
        if result.get('success'):
            # Store categorization run
            run_doc = {
                'batch_name': batch_name or f"batch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                'summary_count': len(summaries),
                'categories': result.get('categories', {}),
                'category_count': result.get('category_count', 0),
                'processed_at': datetime.utcnow(),
                'task_id': task_id,
                'model_used': result.get('model_used', 'gemini-flash')
            }
            
            run_result = runs_collection.insert_one(run_doc)
            run_id = str(run_result.inserted_id)
            
            # Update each summary with its category
            categorized = result.get('categorized_items', [])
            for item in categorized:
                summaries_collection.update_one(
                    {"_id": ObjectId(item['id'])},
                    {"$set": {
                        "category": item.get('category'),
                        "category_confidence": item.get('confidence', 0),
                        "categorization_run_id": run_id,
                        "categorized_at": datetime.utcnow()
                    }}
                )
            
            return {
                'status': 'success',
                'run_id': run_id,
                'summary_count': len(summaries),
                'category_count': result.get('category_count', 0),
                'categories': list(result.get('categories', {}).keys()),
                'task_id': task_id
            }
        else:
            return {
                'status': 'error',
                'error': result.get('error', 'Unknown error'),
                'task_id': task_id
            }
            
    except Exception as e:
        logger.error(f"Error categorizing batch: {e}")
        raise


@celery_app.task(
    bind=True,
    name='backend.tasks.ai_tasks.process_new_leads_pipeline',
    max_retries=1,
)
def process_new_leads_pipeline(
    self,
    account_email: Optional[str] = None,
    limit: int = 100,
    categorize_batch_size: int = 500
) -> Dict[str, Any]:
    """
    Full pipeline: Process new leads with Agent 1, then batch categorize with Agent 2.
    
    Args:
        account_email: Filter by specific account (optional)
        limit: Max leads to process in this run
        categorize_batch_size: Batch size for Agent 2 categorization
        
    Returns:
        Pipeline execution results
    """
    from celery import chain, group
    from bson import ObjectId
    
    task_id = self.request.id
    
    # Use AI pool
    leads_collection = get_ai_collection('email_leads')
    summaries_collection = get_ai_collection('ai_summaries')
    
    # Find unprocessed leads
    query = {"ai_processed": {"$ne": True}}
    if account_email:
        query["account_email"] = account_email
    
    unprocessed_leads = list(leads_collection.find(
        query,
        {"_id": 1}
    ).limit(limit))
    
    if not unprocessed_leads:
        return {
            'status': 'no_leads',
            'message': 'No unprocessed leads found',
            'task_id': task_id
        }
    
    lead_ids = [str(lead['_id']) for lead in unprocessed_leads]
    
    # Update state
    self.update_state(
        state='PROGRESS',
        meta={
            'stage': 'starting_agent1_processing',
            'lead_count': len(lead_ids)
        }
    )
    
    # Create Agent 1 task group
    agent1_group = group(
        process_email_with_agent1.s(lead_id=lid)
        for lid in lead_ids
    )
    
    # Execute Agent 1 tasks
    agent1_result = agent1_group.apply_async()
    
    return {
        'status': 'started',
        'phase': 'agent1_processing',
        'group_id': agent1_result.id,
        'lead_count': len(lead_ids),
        'message': f'Started processing {len(lead_ids)} leads with Agent 1',
        'task_id': task_id
    }


@celery_app.task(
    name='backend.tasks.ai_tasks.get_ai_processing_stats',
)
def get_ai_processing_stats() -> Dict[str, Any]:
    """
    Get statistics about AI processing.
    
    Returns:
        Statistics about processed leads, summaries, and categories
    """
    from datetime import timedelta
    
    # Use AI pool
    leads_collection = get_ai_collection('email_leads')
    summaries_collection = get_ai_collection('ai_summaries')
    runs_collection = get_ai_collection('categorization_runs')
    
    now = datetime.utcnow()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)
    
    stats = {
        'leads': {
            'total': leads_collection.count_documents({}),
            'ai_processed': leads_collection.count_documents({"ai_processed": True}),
            'pending': leads_collection.count_documents({"ai_processed": {"$ne": True}})
        },
        'summaries': {
            'total': summaries_collection.count_documents({}),
            'last_24h': summaries_collection.count_documents({
                "processed_at": {"$gte": last_24h}
            }),
            'last_7d': summaries_collection.count_documents({
                "processed_at": {"$gte": last_7d}
            }),
            'categorized': summaries_collection.count_documents({
                "category": {"$exists": True, "$ne": None}
            })
        },
        'categorization_runs': {
            'total': runs_collection.count_documents({}),
            'last_24h': runs_collection.count_documents({
                "processed_at": {"$gte": last_24h}
            })
        },
        'timestamp': now.isoformat()
    }
    
    # Get category distribution
    category_pipeline = [
        {"$match": {"category": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20}
    ]
    
    category_dist = list(summaries_collection.aggregate(category_pipeline))
    stats['category_distribution'] = {
        item['_id']: item['count'] for item in category_dist
    }
    
    return stats
