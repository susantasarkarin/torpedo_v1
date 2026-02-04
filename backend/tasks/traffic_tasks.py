"""
Traffic & Campaigns Celery Tasks
Background tasks for traffic management, survey allocation, and campaign operations
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import random

from celery_app import celery_app
from db_pools import get_background_db, get_background_collection

logger = logging.getLogger(__name__)


# ============== TRAFFIC TASKS ==============

@celery_app.task(
    bind=True,
    name='backend.tasks.traffic_tasks.batch_assign_surveys',
    max_retries=2,
)
def batch_assign_surveys(
    self,
    traffic_ids: List[str],
    survey_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Batch assign surveys to traffic records.
    Can assign a specific survey or use random allocation.
    """
    task_id = self.request.id
    
    try:
        from bson import ObjectId
        
        db = get_background_db()
        traffic_coll = db['url_parameters']
        surveys_coll = db['surveys']
        
        total = len(traffic_ids)
        assigned = 0
        skipped = 0
        errors = []
        
        # Get available surveys if no specific survey provided
        available_surveys = []
        if not survey_id:
            available_surveys = list(surveys_coll.find(
                {'status': 'active'},
                {'_id': 1, 'name': 1, 'weight': 1}
            ))
            if not available_surveys:
                return {
                    'status': 'error',
                    'error': 'No active surveys available',
                    'task_id': task_id
                }
        
        for i, traffic_id in enumerate(traffic_ids):
            if i % 20 == 0:
                self.update_state(
                    state='PROGRESS',
                    meta={'stage': 'assigning', 'processed': i, 'total': total}
                )
            
            try:
                # Get traffic record
                traffic = traffic_coll.find_one({'_id': ObjectId(traffic_id)})
                
                if not traffic:
                    skipped += 1
                    continue
                
                # Skip if already assigned
                if traffic.get('survey_id'):
                    skipped += 1
                    continue
                
                # Select survey
                if survey_id:
                    selected_survey_id = survey_id
                else:
                    # Weighted random selection
                    weights = [s.get('weight', 1) for s in available_surveys]
                    selected = random.choices(available_surveys, weights=weights, k=1)[0]
                    selected_survey_id = str(selected['_id'])
                
                # Update traffic record
                traffic_coll.update_one(
                    {'_id': ObjectId(traffic_id)},
                    {'$set': {
                        'survey_id': selected_survey_id,
                        'survey_assigned_at': datetime.utcnow(),
                        'assignment_task_id': task_id
                    }}
                )
                assigned += 1
                
            except Exception as e:
                errors.append(f"{traffic_id}: {str(e)}")
        
        return {
            'status': 'success',
            'total': total,
            'assigned': assigned,
            'skipped': skipped,
            'errors': errors[:50],
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error batch assigning surveys: {e}")
        raise


@celery_app.task(
    bind=True,
    name='backend.tasks.traffic_tasks.bulk_delete_traffic',
    max_retries=1,
)
def bulk_delete_traffic(self, traffic_ids: List[str]) -> Dict[str, Any]:
    """
    Bulk delete traffic records by IDs.
    """
    task_id = self.request.id
    
    try:
        from bson import ObjectId
        
        traffic_coll = get_background_collection('url_parameters')
        
        total = len(traffic_ids)
        deleted = 0
        
        # Convert to ObjectIds
        object_ids = []
        for tid in traffic_ids:
            try:
                object_ids.append(ObjectId(tid))
            except Exception:
                continue
        
        self.update_state(state='PROGRESS', meta={'stage': 'deleting', 'total': total})
        
        # Bulk delete
        result = traffic_coll.delete_many({'_id': {'$in': object_ids}})
        deleted = result.deleted_count
        
        return {
            'status': 'success',
            'total': total,
            'deleted': deleted,
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error bulk deleting traffic: {e}")
        raise


@celery_app.task(
    bind=True,
    name='backend.tasks.traffic_tasks.generate_traffic_stats',
    max_retries=2,
)
def generate_traffic_stats(
    self,
    date_range: str = '7d'
) -> Dict[str, Any]:
    """
    Generate comprehensive traffic statistics report.
    """
    task_id = self.request.id
    
    try:
        db = get_background_db()
        traffic_coll = db['url_parameters']
        surveys_coll = db['surveys']
        
        now = datetime.utcnow()
        if date_range == '1d':
            start_date = now - timedelta(days=1)
        elif date_range == '7d':
            start_date = now - timedelta(days=7)
        elif date_range == '30d':
            start_date = now - timedelta(days=30)
        else:
            start_date = now - timedelta(days=7)
        
        self.update_state(state='PROGRESS', meta={'stage': 'counting_traffic'})
        
        # Overall counts
        total_traffic = traffic_coll.count_documents({})
        recent_traffic = traffic_coll.count_documents({'created_at': {'$gte': start_date}})
        assigned_traffic = traffic_coll.count_documents({'survey_id': {'$exists': True, '$ne': None}})
        unassigned_traffic = traffic_coll.count_documents({
            '$or': [
                {'survey_id': {'$exists': False}},
                {'survey_id': None}
            ]
        })
        
        self.update_state(state='PROGRESS', meta={'stage': 'survey_breakdown'})
        
        # Traffic by survey
        survey_pipeline = [
            {'$match': {'created_at': {'$gte': start_date}, 'survey_id': {'$exists': True}}},
            {'$group': {
                '_id': '$survey_id',
                'count': {'$sum': 1}
            }},
            {'$sort': {'count': -1}}
        ]
        traffic_by_survey = list(traffic_coll.aggregate(survey_pipeline))
        
        self.update_state(state='PROGRESS', meta={'stage': 'source_breakdown'})
        
        # Traffic by source
        source_pipeline = [
            {'$match': {'created_at': {'$gte': start_date}}},
            {'$group': {
                '_id': '$source',
                'count': {'$sum': 1}
            }},
            {'$sort': {'count': -1}},
            {'$limit': 20}
        ]
        traffic_by_source = list(traffic_coll.aggregate(source_pipeline))
        
        self.update_state(state='PROGRESS', meta={'stage': 'daily_trend'})
        
        # Daily trend
        daily_pipeline = [
            {'$match': {'created_at': {'$gte': start_date}}},
            {'$group': {
                '_id': {
                    'year': {'$year': '$created_at'},
                    'month': {'$month': '$created_at'},
                    'day': {'$dayOfMonth': '$created_at'}
                },
                'count': {'$sum': 1}
            }},
            {'$sort': {'_id.year': 1, '_id.month': 1, '_id.day': 1}}
        ]
        daily_trend = list(traffic_coll.aggregate(daily_pipeline))
        
        # Store report
        reports_coll = get_background_collection('traffic_reports')
        report = {
            'type': 'traffic_stats',
            'date_range': date_range,
            'generated_at': datetime.utcnow(),
            'task_id': task_id,
            'data': {
                'counts': {
                    'total': total_traffic,
                    'recent': recent_traffic,
                    'assigned': assigned_traffic,
                    'unassigned': unassigned_traffic
                },
                'by_survey': traffic_by_survey,
                'by_source': traffic_by_source,
                'daily_trend': daily_trend
            }
        }
        
        result = reports_coll.insert_one(report)
        
        return {
            'status': 'success',
            'report_id': str(result.inserted_id),
            'summary': {
                'total': total_traffic,
                'recent': recent_traffic,
                'unassigned': unassigned_traffic
            },
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error generating traffic stats: {e}")
        raise


# ============== CAMPAIGN TASKS ==============

@celery_app.task(
    bind=True,
    name='backend.tasks.traffic_tasks.add_campaign_recipients_batch',
    max_retries=2,
)
def add_campaign_recipients_batch(
    self,
    campaign_id: str,
    recipients: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Add recipients to a campaign in batch with deduplication.
    """
    task_id = self.request.id
    
    try:
        from bson import ObjectId
        
        campaigns_coll = get_background_collection('campaigns')
        
        campaign = campaigns_coll.find_one({'_id': ObjectId(campaign_id)})
        if not campaign:
            return {
                'status': 'error',
                'error': f'Campaign not found: {campaign_id}',
                'task_id': task_id
            }
        
        existing_emails = set(
            r.get('email', '').lower()
            for r in campaign.get('recipients', [])
        )
        
        total = len(recipients)
        added = 0
        skipped = 0
        new_recipients = []
        
        for i, recipient in enumerate(recipients):
            if i % 100 == 0:
                self.update_state(
                    state='PROGRESS',
                    meta={'stage': 'processing', 'processed': i, 'total': total}
                )
            
            email = recipient.get('email', '').lower().strip()
            
            if not email or email in existing_emails:
                skipped += 1
                continue
            
            new_recipients.append({
                'email': email,
                'name': recipient.get('name', ''),
                'company': recipient.get('company', ''),
                'added_at': datetime.utcnow(),
                'status': 'pending',
                'task_id': task_id
            })
            existing_emails.add(email)
            added += 1
        
        # Bulk add to campaign
        if new_recipients:
            campaigns_coll.update_one(
                {'_id': ObjectId(campaign_id)},
                {
                    '$push': {'recipients': {'$each': new_recipients}},
                    '$set': {'updated_at': datetime.utcnow()}
                }
            )
        
        return {
            'status': 'success',
            'campaign_id': campaign_id,
            'total': total,
            'added': added,
            'skipped': skipped,
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error adding campaign recipients: {e}")
        raise


@celery_app.task(
    bind=True,
    name='backend.tasks.traffic_tasks.import_campaign_recipients_csv',
    max_retries=1,
)
def import_campaign_recipients_csv(
    self,
    campaign_id: str,
    csv_content: str
) -> Dict[str, Any]:
    """
    Import recipients from CSV to a campaign.
    """
    task_id = self.request.id
    
    try:
        import csv
        import io
        from bson import ObjectId
        
        campaigns_coll = get_background_collection('campaigns')
        
        campaign = campaigns_coll.find_one({'_id': ObjectId(campaign_id)})
        if not campaign:
            return {
                'status': 'error',
                'error': f'Campaign not found: {campaign_id}',
                'task_id': task_id
            }
        
        self.update_state(state='PROGRESS', meta={'stage': 'parsing_csv'})
        
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)
        
        # Convert to recipients format
        recipients = []
        for row in rows:
            email = row.get('email', row.get('Email', '')).strip()
            if email:
                recipients.append({
                    'email': email,
                    'name': row.get('name', row.get('Name', '')),
                    'company': row.get('company', row.get('Company', ''))
                })
        
        # Use batch add task
        result = add_campaign_recipients_batch(
            campaign_id=campaign_id,
            recipients=recipients
        )
        
        result['source'] = 'csv_import'
        result['task_id'] = task_id
        
        return result
        
    except Exception as e:
        logger.error(f"Error importing campaign recipients: {e}")
        raise


@celery_app.task(
    bind=True,
    name='backend.tasks.traffic_tasks.generate_campaign_analytics',
    max_retries=2,
)
def generate_campaign_analytics(
    self,
    campaign_id: str
) -> Dict[str, Any]:
    """
    Generate analytics for a campaign.
    """
    task_id = self.request.id
    
    try:
        from bson import ObjectId
        
        campaigns_coll = get_background_collection('campaigns')
        
        campaign = campaigns_coll.find_one({'_id': ObjectId(campaign_id)})
        if not campaign:
            return {
                'status': 'error',
                'error': f'Campaign not found: {campaign_id}',
                'task_id': task_id
            }
        
        self.update_state(state='PROGRESS', meta={'stage': 'analyzing_recipients'})
        
        recipients = campaign.get('recipients', [])
        total_recipients = len(recipients)
        
        # Status breakdown
        status_counts = {}
        for r in recipients:
            status = r.get('status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
        
        self.update_state(state='PROGRESS', meta={'stage': 'calculating_metrics'})
        
        # Calculate metrics
        sent = status_counts.get('sent', 0)
        delivered = status_counts.get('delivered', 0)
        opened = status_counts.get('opened', 0)
        clicked = status_counts.get('clicked', 0)
        bounced = status_counts.get('bounced', 0)
        unsubscribed = status_counts.get('unsubscribed', 0)
        
        delivery_rate = round((delivered / sent * 100), 2) if sent > 0 else 0
        open_rate = round((opened / delivered * 100), 2) if delivered > 0 else 0
        click_rate = round((clicked / opened * 100), 2) if opened > 0 else 0
        bounce_rate = round((bounced / sent * 100), 2) if sent > 0 else 0
        
        # Store analytics
        analytics_coll = get_background_collection('campaign_analytics')
        analytics = {
            'campaign_id': campaign_id,
            'campaign_name': campaign.get('name'),
            'generated_at': datetime.utcnow(),
            'task_id': task_id,
            'data': {
                'total_recipients': total_recipients,
                'status_breakdown': status_counts,
                'metrics': {
                    'delivery_rate': delivery_rate,
                    'open_rate': open_rate,
                    'click_rate': click_rate,
                    'bounce_rate': bounce_rate
                },
                'counts': {
                    'sent': sent,
                    'delivered': delivered,
                    'opened': opened,
                    'clicked': clicked,
                    'bounced': bounced,
                    'unsubscribed': unsubscribed
                }
            }
        }
        
        result = analytics_coll.insert_one(analytics)
        
        return {
            'status': 'success',
            'analytics_id': str(result.inserted_id),
            'campaign_id': campaign_id,
            'summary': {
                'total_recipients': total_recipients,
                'delivery_rate': delivery_rate,
                'open_rate': open_rate,
                'click_rate': click_rate
            },
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error generating campaign analytics: {e}")
        raise


# ============== INBOX TASKS ==============

@celery_app.task(
    bind=True,
    name='backend.tasks.traffic_tasks.bulk_inbox_operation',
    max_retries=2,
)
def bulk_inbox_operation(
    self,
    email_ids: List[str],
    operation: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Perform bulk operations on inbox emails.
    Operations: mark_read, archive, delete, categorize, move
    """
    task_id = self.request.id
    
    try:
        from bson import ObjectId
        
        inbox_coll = get_background_collection('unified_inbox')
        
        total = len(email_ids)
        processed = 0
        errors = []
        
        object_ids = []
        for eid in email_ids:
            try:
                object_ids.append(ObjectId(eid))
            except Exception:
                continue
        
        self.update_state(state='PROGRESS', meta={'stage': operation, 'total': total})
        
        update_data = {'updated_at': datetime.utcnow(), 'bulk_task_id': task_id}
        
        if operation == 'mark_read':
            update_data['is_read'] = True
        elif operation == 'mark_unread':
            update_data['is_read'] = False
        elif operation == 'archive':
            update_data['is_archived'] = True
        elif operation == 'unarchive':
            update_data['is_archived'] = False
        elif operation == 'delete':
            update_data['is_deleted'] = True
            update_data['deleted_at'] = datetime.utcnow()
        elif operation == 'categorize':
            category = params.get('category') if params else None
            if category:
                update_data['category'] = category
        elif operation == 'move':
            folder = params.get('folder') if params else None
            if folder:
                update_data['folder'] = folder
        else:
            return {
                'status': 'error',
                'error': f'Unknown operation: {operation}',
                'task_id': task_id
            }
        
        # Bulk update
        result = inbox_coll.update_many(
            {'_id': {'$in': object_ids}},
            {'$set': update_data}
        )
        processed = result.modified_count
        
        return {
            'status': 'success',
            'operation': operation,
            'total': total,
            'processed': processed,
            'errors': errors[:50],
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error performing bulk inbox operation: {e}")
        raise


# ============== CPX SURVEY FETCH TASK ==============

@celery_app.task(
    bind=True,
    name='backend.tasks.traffic_tasks.fetch_cpx_surveys',
    max_retries=0,  # No retries - this task is DISABLED
)
def fetch_cpx_surveys(
    self,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    ⛔ DISABLED - CPX CANNOT BE FETCHED IN BACKGROUND JOBS
    
    CPX Research binds survey hrefs to ext_user_id + IP + User-Agent.
    Background jobs cannot provide real client context, so any surveys
    fetched here would produce UNUSABLE hrefs that fail on click.
    
    Use fetch_and_allocate_for_respondent() from HTTP request context instead.
    
    Raises:
        RuntimeError: Always - CPX background fetching is not allowed
    """
    task_id = self.request.id
    logger.error(
        f"CPX FATAL: Task {task_id} attempted to fetch CPX surveys in background. "
        "This is architecturally invalid - CPX requires real client IP/UA."
    )
    raise RuntimeError(
        "CPX FATAL: Cannot fetch CPX surveys in background job. "
        "CPX binds hrefs to client IP/UA which background jobs cannot provide. "
        "Use fetch_and_allocate_for_respondent() from HTTP context instead."
    )