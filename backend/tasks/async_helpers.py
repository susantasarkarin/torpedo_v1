"""
Async Task Helpers
Convenience functions for starting background tasks from API routers
"""

import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime


def _start_task(task_func, *args, operation_type: str = 'generic', metadata: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
    """
    Generic helper to start a Celery task and register it for tracking.
    """
    from tasks.api_tasks import start_operation
    
    operation_id = str(uuid.uuid4())
    
    # Start the Celery task
    task = task_func.apply_async(args=args, kwargs=kwargs, task_id=operation_id)
    
    # Register operation for tracking
    start_operation.delay(
        operation_type=operation_type,
        operation_id=operation_id,
        metadata=metadata or {}
    )
    
    return {
        'operation_id': operation_id,
        'task_id': task.id,
        'status': 'started',
        'poll_url': f'/operations/async/{operation_id}/status'
    }


# ============== EMAIL SYNC HELPERS ==============

def start_email_sync(account_email: Optional[str] = None, since_days: int = 0) -> Dict[str, Any]:
    """Start email sync for one or all accounts."""
    from tasks.email_tasks import sync_account_emails, sync_all_accounts
    
    if account_email:
        return _start_task(
            sync_account_emails,
            account_email, since_days,
            operation_type='email_sync',
            metadata={'account_email': account_email, 'since_days': since_days}
        )
    else:
        return _start_task(
            sync_all_accounts,
            since_days,
            operation_type='email_sync_all',
            metadata={'since_days': since_days}
        )


def start_email_counts() -> Dict[str, Any]:
    """Get email counts for all accounts."""
    from tasks.email_tasks import get_email_counts
    
    return _start_task(
        get_email_counts,
        operation_type='email_counts',
        metadata={}
    )


# ============== AI PROCESSING HELPERS ==============

def start_ai_processing(account_email: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    """Start AI processing pipeline for new leads."""
    from tasks.ai_tasks import process_new_leads_pipeline
    
    return _start_task(
        process_new_leads_pipeline,
        account_email, limit,
        operation_type='ai_processing',
        metadata={'account_email': account_email, 'limit': limit}
    )


def start_ai_categorization(summary_ids: List[str], batch_name: Optional[str] = None) -> Dict[str, Any]:
    """Start AI categorization for a batch of summaries."""
    from tasks.ai_tasks import categorize_batch_with_agent2
    
    return _start_task(
        categorize_batch_with_agent2,
        summary_ids, batch_name,
        operation_type='ai_categorization',
        metadata={'summary_count': len(summary_ids), 'batch_name': batch_name}
    )


# ============== FINANCE HELPERS ==============

def start_finance_export(export_type: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    """Start a finance export task."""
    from tasks.finance_tasks import (
        export_customers_csv,
        export_invoices_csv,
        export_bills_csv
    )
    
    task_map = {
        'customers': export_customers_csv,
        'invoices': export_invoices_csv,
        'bills': export_bills_csv
    }
    
    task_func = task_map.get(export_type)
    if not task_func:
        raise ValueError(f"Unknown export type: {export_type}")
    
    if export_type == 'customers':
        return _start_task(
            task_func,
            operation_type=f'export_{export_type}',
            metadata={'export_type': export_type}
        )
    else:
        return _start_task(
            task_func,
            start_date, end_date,
            operation_type=f'export_{export_type}',
            metadata={'export_type': export_type, 'start_date': start_date, 'end_date': end_date}
        )


def start_finance_import(import_type: str, csv_content: str) -> Dict[str, Any]:
    """Start a finance import task."""
    from tasks.finance_tasks import (
        import_customers_csv,
        import_invoices_csv
    )
    
    task_map = {
        'customers': import_customers_csv,
        'invoices': import_invoices_csv
    }
    
    task_func = task_map.get(import_type)
    if not task_func:
        raise ValueError(f"Unknown import type: {import_type}")
    
    return _start_task(
        task_func,
        csv_content,
        operation_type=f'import_{import_type}',
        metadata={'import_type': import_type, 'content_length': len(csv_content)}
    )


def start_finance_summary(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    """Generate finance summary report."""
    from tasks.finance_tasks import generate_finance_summary
    
    return _start_task(
        generate_finance_summary,
        start_date, end_date,
        operation_type='finance_summary',
        metadata={'start_date': start_date, 'end_date': end_date}
    )


def start_bulk_delete_customers(customer_ids: List[str]) -> Dict[str, Any]:
    """Bulk delete customers."""
    from tasks.finance_tasks import bulk_delete_customers
    
    return _start_task(
        bulk_delete_customers,
        customer_ids,
        operation_type='bulk_delete_customers',
        metadata={'count': len(customer_ids)}
    )


# ============== SALES HELPERS ==============

def start_sales_dashboard(date_range: str = '30d', force_refresh: bool = False) -> Dict[str, Any]:
    """Generate sales dashboard data."""
    from tasks.sales_tasks import generate_sales_dashboard
    
    return _start_task(
        generate_sales_dashboard,
        date_range, force_refresh,
        operation_type='sales_dashboard',
        metadata={'date_range': date_range, 'force_refresh': force_refresh}
    )


def start_enrich_contacts(contact_ids: List[str]) -> Dict[str, Any]:
    """Batch enrich contacts."""
    from tasks.sales_tasks import enrich_contacts_batch
    
    return _start_task(
        enrich_contacts_batch,
        contact_ids,
        operation_type='enrich_contacts',
        metadata={'count': len(contact_ids)}
    )


def start_sync_account_contacts(account_id: str) -> Dict[str, Any]:
    """Sync contacts from a sales account."""
    from tasks.sales_tasks import sync_account_contacts
    
    return _start_task(
        sync_account_contacts,
        account_id,
        operation_type='sync_account_contacts',
        metadata={'account_id': account_id}
    )


def start_pipeline_report(date_range: str = '30d') -> Dict[str, Any]:
    """Generate sales pipeline report."""
    from tasks.sales_tasks import generate_pipeline_report
    
    return _start_task(
        generate_pipeline_report,
        date_range,
        operation_type='pipeline_report',
        metadata={'date_range': date_range}
    )


# ============== TRAFFIC HELPERS ==============

def start_batch_assign_surveys(traffic_ids: List[str], survey_id: Optional[str] = None) -> str:
    """Batch assign surveys to traffic records. Returns operation_id."""
    from tasks.traffic_tasks import batch_assign_surveys
    
    result = _start_task(
        batch_assign_surveys,
        traffic_ids, survey_id,
        operation_type='batch_assign_surveys',
        metadata={'count': len(traffic_ids), 'survey_id': survey_id}
    )
    return result['operation_id']


def start_bulk_delete_traffic(filter_or_ids: Any) -> str:
    """Bulk delete traffic records. Accepts filter dict or list of IDs. Returns operation_id."""
    from tasks.traffic_tasks import bulk_delete_traffic
    
    # Handle both filter dict and ID list
    if isinstance(filter_or_ids, dict):
        traffic_ids = filter_or_ids.get('ids', [])
        filter_criteria = {k: v for k, v in filter_or_ids.items() if k != 'ids'}
    else:
        traffic_ids = filter_or_ids
        filter_criteria = {}
    
    result = _start_task(
        bulk_delete_traffic,
        traffic_ids,
        operation_type='bulk_delete_traffic',
        metadata={'count': len(traffic_ids) if traffic_ids else 0, 'filter': filter_criteria}
    )
    return result['operation_id']


def start_traffic_stats_generation(date_range: Dict[str, str], group_by: List[str]) -> str:
    """Generate traffic statistics. Returns operation_id."""
    from tasks.traffic_tasks import generate_traffic_stats
    
    # Convert date_range dict to string format
    date_range_str = f"{date_range.get('start', '')}_{date_range.get('end', '')}" if date_range else '7d'
    
    result = _start_task(
        generate_traffic_stats,
        date_range_str,
        operation_type='traffic_stats',
        metadata={'date_range': date_range, 'group_by': group_by}
    )
    return result['operation_id']


def start_traffic_stats(date_range: str = '7d') -> Dict[str, Any]:
    """Generate traffic statistics."""
    from tasks.traffic_tasks import generate_traffic_stats
    
    return _start_task(
        generate_traffic_stats,
        date_range,
        operation_type='traffic_stats',
        metadata={'date_range': date_range}
    )


# ============== CAMPAIGN HELPERS ==============

def start_add_campaign_recipients(campaign_id: str, recipients: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Add recipients to a campaign."""
    from tasks.traffic_tasks import add_campaign_recipients_batch
    
    return _start_task(
        add_campaign_recipients_batch,
        campaign_id, recipients,
        operation_type='add_campaign_recipients',
        metadata={'campaign_id': campaign_id, 'count': len(recipients)}
    )


def start_campaign_recipients_add(campaign_id: str, recipients: List[Dict[str, Any]]) -> str:
    """Add recipients to a campaign. Returns operation_id."""
    from tasks.traffic_tasks import add_campaign_recipients_batch
    
    result = _start_task(
        add_campaign_recipients_batch,
        campaign_id, recipients,
        operation_type='add_campaign_recipients',
        metadata={'campaign_id': campaign_id, 'count': len(recipients)}
    )
    return result['operation_id']


def start_import_campaign_recipients(campaign_id: str, csv_content: str) -> Dict[str, Any]:
    """Import recipients from CSV."""
    from tasks.traffic_tasks import import_campaign_recipients_csv
    
    return _start_task(
        import_campaign_recipients_csv,
        campaign_id, csv_content,
        operation_type='import_campaign_recipients',
        metadata={'campaign_id': campaign_id, 'content_length': len(csv_content)}
    )


def start_campaign_csv_import(campaign_id: str, csv_data: str, column_mapping: Dict[str, str], skip_duplicates: bool = True) -> str:
    """Import recipients from CSV. Returns operation_id."""
    from tasks.traffic_tasks import import_campaign_recipients_csv
    
    result = _start_task(
        import_campaign_recipients_csv,
        campaign_id, csv_data,
        operation_type='import_campaign_recipients',
        metadata={
            'campaign_id': campaign_id,
            'column_mapping': column_mapping,
            'skip_duplicates': skip_duplicates
        }
    )
    return result['operation_id']


def start_campaign_analytics(campaign_id: str) -> Dict[str, Any]:
    """Generate campaign analytics."""
    from tasks.traffic_tasks import generate_campaign_analytics
    
    return _start_task(
        generate_campaign_analytics,
        campaign_id,
        operation_type='campaign_analytics',
        metadata={'campaign_id': campaign_id}
    )


def start_campaign_analytics_generation(campaign_id: str, include_details: bool = False, group_by_day: bool = True) -> str:
    """Generate campaign analytics. Returns operation_id."""
    from tasks.traffic_tasks import generate_campaign_analytics
    
    result = _start_task(
        generate_campaign_analytics,
        campaign_id,
        operation_type='campaign_analytics',
        metadata={
            'campaign_id': campaign_id,
            'include_details': include_details,
            'group_by_day': group_by_day
        }
    )
    return result['operation_id']


# ============== INBOX HELPERS ==============

def start_bulk_inbox_operation(email_ids: List[str], operation: str, params: Optional[Dict] = None) -> Dict[str, Any]:
    """Perform bulk inbox operation."""
    from tasks.traffic_tasks import bulk_inbox_operation
    
    return _start_task(
        bulk_inbox_operation,
        email_ids, operation, params,
        operation_type=f'inbox_{operation}',
        metadata={'count': len(email_ids), 'operation': operation}
    )
