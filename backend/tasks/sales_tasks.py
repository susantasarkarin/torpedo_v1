"""
Sales Celery Tasks
Background tasks for sales dashboard, accounts, and analytics
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from backend.celery_app import celery_app
from backend.db_pools import get_background_db, get_background_collection

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name='backend.tasks.sales_tasks.generate_sales_dashboard',
    max_retries=2,
)
def generate_sales_dashboard(
    self,
    date_range: str = '30d',
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Generate comprehensive sales dashboard data.
    Heavy aggregation across multiple collections.
    """
    task_id = self.request.id
    
    try:
        db = get_background_db()
        leads_raw = db['leads_raw']
        leads_enriched = db['leads_enriched']
        email_leads = db['email_leads']
        rfqs = db['rfqs']
        
        # Calculate date range
        now = datetime.utcnow()
        if date_range == '7d':
            start_date = now - timedelta(days=7)
        elif date_range == '30d':
            start_date = now - timedelta(days=30)
        elif date_range == '90d':
            start_date = now - timedelta(days=90)
        else:
            start_date = now - timedelta(days=30)
        
        self.update_state(state='PROGRESS', meta={'stage': 'counting_leads'})
        
        # Lead counts
        raw_count = leads_raw.count_documents({})
        enriched_count = leads_enriched.count_documents({})
        email_count = email_leads.count_documents({})
        
        # Recent activity
        recent_raw = leads_raw.count_documents({'created_at': {'$gte': start_date}})
        recent_enriched = leads_enriched.count_documents({'created_at': {'$gte': start_date}})
        
        self.update_state(state='PROGRESS', meta={'stage': 'analyzing_rfqs'})
        
        # RFQ Analysis
        rfq_pipeline = [
            {'$match': {'created_at': {'$gte': start_date}}},
            {'$group': {
                '_id': '$status',
                'count': {'$sum': 1},
                'total_value': {'$sum': '$estimated_value'}
            }}
        ]
        rfq_stats = list(rfqs.aggregate(rfq_pipeline))
        
        # RFQ aging buckets
        rfq_aging = {
            '0-7_days': rfqs.count_documents({
                'created_at': {'$gte': now - timedelta(days=7)},
                'status': {'$in': ['pending', 'open']}
            }),
            '8-14_days': rfqs.count_documents({
                'created_at': {'$gte': now - timedelta(days=14), '$lt': now - timedelta(days=7)},
                'status': {'$in': ['pending', 'open']}
            }),
            '15-30_days': rfqs.count_documents({
                'created_at': {'$gte': now - timedelta(days=30), '$lt': now - timedelta(days=14)},
                'status': {'$in': ['pending', 'open']}
            }),
            '30+_days': rfqs.count_documents({
                'created_at': {'$lt': now - timedelta(days=30)},
                'status': {'$in': ['pending', 'open']}
            })
        }
        
        self.update_state(state='PROGRESS', meta={'stage': 'calculating_velocity'})
        
        # Lead velocity (leads per day)
        days_in_range = (now - start_date).days or 1
        velocity = {
            'raw_per_day': round(recent_raw / days_in_range, 2),
            'enriched_per_day': round(recent_enriched / days_in_range, 2)
        }
        
        self.update_state(state='PROGRESS', meta={'stage': 'source_analysis'})
        
        # Lead source distribution
        source_pipeline = [
            {'$match': {'created_at': {'$gte': start_date}}},
            {'$group': {
                '_id': '$source',
                'count': {'$sum': 1}
            }},
            {'$sort': {'count': -1}},
            {'$limit': 10}
        ]
        lead_sources = list(leads_enriched.aggregate(source_pipeline))
        
        # Conversion funnel
        funnel = {
            'raw_leads': raw_count,
            'enriched': enriched_count,
            'rfq_created': rfqs.count_documents({}),
            'rfq_won': rfqs.count_documents({'status': 'won'}),
            'rfq_lost': rfqs.count_documents({'status': 'lost'})
        }
        
        # Store dashboard data
        dashboards_coll = get_background_collection('sales_dashboards')
        dashboard_doc = {
            'date_range': date_range,
            'generated_at': datetime.utcnow(),
            'task_id': task_id,
            'data': {
                'lead_counts': {
                    'raw': raw_count,
                    'enriched': enriched_count,
                    'email': email_count,
                    'recent_raw': recent_raw,
                    'recent_enriched': recent_enriched
                },
                'rfq_stats': rfq_stats,
                'rfq_aging': rfq_aging,
                'velocity': velocity,
                'lead_sources': lead_sources,
                'funnel': funnel
            }
        }
        
        result = dashboards_coll.insert_one(dashboard_doc)
        
        return {
            'status': 'success',
            'dashboard_id': str(result.inserted_id),
            'summary': {
                'total_leads': raw_count + enriched_count,
                'recent_activity': recent_raw + recent_enriched,
                'open_rfqs': sum(1 for r in rfq_stats if r['_id'] in ['pending', 'open'])
            },
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error generating sales dashboard: {e}")
        raise


@celery_app.task(
    bind=True,
    name='backend.tasks.sales_tasks.enrich_contacts_batch',
    max_retries=3,
    rate_limit='5/m',  # Rate limit for external API calls
)
def enrich_contacts_batch(
    self,
    contact_ids: List[str]
) -> Dict[str, Any]:
    """
    Batch enrich contacts from sales accounts.
    May involve external API calls for data enrichment.
    """
    task_id = self.request.id
    
    try:
        from bson import ObjectId
        
        accounts_coll = get_background_collection('sales_accounts')
        leads_coll = get_background_collection('leads_enriched')
        
        total = len(contact_ids)
        enriched = 0
        skipped = 0
        errors = []
        
        for i, contact_id in enumerate(contact_ids):
            if i % 10 == 0:
                self.update_state(
                    state='PROGRESS',
                    meta={'stage': 'enriching', 'processed': i, 'total': total}
                )
            
            try:
                # Get contact from accounts
                account = accounts_coll.find_one(
                    {'contacts._id': ObjectId(contact_id)},
                    {'contacts.$': 1, 'company_name': 1, 'domain': 1}
                )
                
                if not account or not account.get('contacts'):
                    skipped += 1
                    continue
                
                contact = account['contacts'][0]
                
                # Create or update lead
                lead_data = {
                    'email': contact.get('email'),
                    'first_name': contact.get('first_name'),
                    'last_name': contact.get('last_name'),
                    'company': account.get('company_name'),
                    'domain': account.get('domain'),
                    'title': contact.get('title'),
                    'phone': contact.get('phone'),
                    'source': 'sales_account',
                    'source_id': contact_id,
                    'enriched_at': datetime.utcnow(),
                    'task_id': task_id
                }
                
                leads_coll.update_one(
                    {'email': contact.get('email')},
                    {'$set': lead_data, '$setOnInsert': {'created_at': datetime.utcnow()}},
                    upsert=True
                )
                
                enriched += 1
                
            except Exception as e:
                errors.append(f"{contact_id}: {str(e)}")
        
        return {
            'status': 'success',
            'total': total,
            'enriched': enriched,
            'skipped': skipped,
            'errors': errors[:50],
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error enriching contacts: {e}")
        raise


@celery_app.task(
    bind=True,
    name='backend.tasks.sales_tasks.sync_account_contacts',
    max_retries=2,
)
def sync_account_contacts(
    self,
    account_id: str
) -> Dict[str, Any]:
    """
    Sync contacts from a sales account to leads collection.
    """
    task_id = self.request.id
    
    try:
        from bson import ObjectId
        
        accounts_coll = get_background_collection('sales_accounts')
        leads_coll = get_background_collection('leads_enriched')
        
        account = accounts_coll.find_one({'_id': ObjectId(account_id)})
        
        if not account:
            return {
                'status': 'error',
                'error': f'Account not found: {account_id}',
                'task_id': task_id
            }
        
        contacts = account.get('contacts', [])
        total = len(contacts)
        synced = 0
        
        for i, contact in enumerate(contacts):
            if i % 20 == 0:
                self.update_state(
                    state='PROGRESS',
                    meta={'stage': 'syncing', 'processed': i, 'total': total}
                )
            
            if not contact.get('email'):
                continue
            
            lead_data = {
                'email': contact.get('email'),
                'first_name': contact.get('first_name'),
                'last_name': contact.get('last_name'),
                'company': account.get('company_name'),
                'domain': account.get('domain'),
                'title': contact.get('title'),
                'phone': contact.get('phone'),
                'source': 'sales_account',
                'account_id': account_id,
                'synced_at': datetime.utcnow()
            }
            
            leads_coll.update_one(
                {'email': contact.get('email')},
                {'$set': lead_data, '$setOnInsert': {'created_at': datetime.utcnow()}},
                upsert=True
            )
            synced += 1
        
        # Update account sync timestamp
        accounts_coll.update_one(
            {'_id': ObjectId(account_id)},
            {'$set': {'contacts_synced_at': datetime.utcnow()}}
        )
        
        return {
            'status': 'success',
            'account_id': account_id,
            'total_contacts': total,
            'synced': synced,
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error syncing account contacts: {e}")
        raise


@celery_app.task(
    bind=True,
    name='backend.tasks.sales_tasks.generate_pipeline_report',
    max_retries=2,
)
def generate_pipeline_report(
    self,
    date_range: str = '30d'
) -> Dict[str, Any]:
    """
    Generate sales pipeline report with stage analysis.
    """
    task_id = self.request.id
    
    try:
        db = get_background_db()
        rfqs = db['rfqs']
        accounts = db['sales_accounts']
        
        now = datetime.utcnow()
        if date_range == '7d':
            start_date = now - timedelta(days=7)
        elif date_range == '90d':
            start_date = now - timedelta(days=90)
        else:
            start_date = now - timedelta(days=30)
        
        self.update_state(state='PROGRESS', meta={'stage': 'analyzing_pipeline'})
        
        # Pipeline stages
        pipeline_stages = [
            {'$match': {'created_at': {'$gte': start_date}}},
            {'$group': {
                '_id': '$stage',
                'count': {'$sum': 1},
                'total_value': {'$sum': '$estimated_value'},
                'avg_value': {'$avg': '$estimated_value'}
            }},
            {'$sort': {'count': -1}}
        ]
        stages = list(rfqs.aggregate(pipeline_stages))
        
        self.update_state(state='PROGRESS', meta={'stage': 'calculating_conversion'})
        
        # Conversion rates
        total_rfqs = rfqs.count_documents({'created_at': {'$gte': start_date}})
        won_rfqs = rfqs.count_documents({'created_at': {'$gte': start_date}, 'status': 'won'})
        lost_rfqs = rfqs.count_documents({'created_at': {'$gte': start_date}, 'status': 'lost'})
        
        win_rate = round((won_rfqs / total_rfqs * 100), 2) if total_rfqs > 0 else 0
        
        self.update_state(state='PROGRESS', meta={'stage': 'time_analysis'})
        
        # Average time to close
        closed_rfqs = list(rfqs.find({
            'created_at': {'$gte': start_date},
            'closed_at': {'$exists': True},
            'status': {'$in': ['won', 'lost']}
        }, {'created_at': 1, 'closed_at': 1}))
        
        if closed_rfqs:
            total_days = sum(
                (r.get('closed_at') - r.get('created_at')).days
                for r in closed_rfqs
                if r.get('closed_at') and r.get('created_at')
            )
            avg_days_to_close = round(total_days / len(closed_rfqs), 1)
        else:
            avg_days_to_close = 0
        
        # Store report
        reports_coll = get_background_collection('sales_reports')
        report = {
            'type': 'pipeline_report',
            'date_range': date_range,
            'generated_at': datetime.utcnow(),
            'task_id': task_id,
            'data': {
                'stages': stages,
                'total_rfqs': total_rfqs,
                'won': won_rfqs,
                'lost': lost_rfqs,
                'win_rate': win_rate,
                'avg_days_to_close': avg_days_to_close
            }
        }
        
        result = reports_coll.insert_one(report)
        
        return {
            'status': 'success',
            'report_id': str(result.inserted_id),
            'summary': {
                'total_rfqs': total_rfqs,
                'win_rate': win_rate,
                'avg_days_to_close': avg_days_to_close
            },
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error generating pipeline report: {e}")
        raise
