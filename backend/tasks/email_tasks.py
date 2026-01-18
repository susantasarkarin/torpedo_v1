"""
Email Sync Celery Tasks
Background tasks for parallel email synchronization
"""

import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from celery import shared_task, current_task

from celery_app import celery_app
from db_pools import get_background_db, get_background_collection

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name='backend.tasks.email_tasks.sync_account_emails',
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
)
def sync_account_emails(
    self,
    account_email: str,
    since_days: int = 0,
    folders: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Sync emails for a single account in the background.
    
    Args:
        account_email: Email address of the account to sync
        since_days: Only fetch emails from last N days (0 = all)
        folders: List of folders to sync (default: INBOX + Sent)
        
    Returns:
        Sync result with counts and status
    """
    from leads.parallel_email_sync import (
        IMAPAccountConfig,
        download_all_emails_for_account,
        update_progress
    )
    
    task_id = self.request.id
    
    # Get account from database using background pool
    accounts_collection = get_background_collection('imap_accounts')
    account_doc = accounts_collection.find_one({"email": account_email})
    
    if not account_doc:
        return {
            'status': 'error',
            'error': f'Account not found: {account_email}',
            'task_id': task_id
        }
    
    account = IMAPAccountConfig(
        email=account_doc["email"],
        password=account_doc.get("password", ""),
        imap_server=account_doc.get("imap_server", "imap.gmail.com"),
        imap_port=account_doc.get("imap_port", 993),
        use_ssl=account_doc.get("use_ssl", True)
    )
    
    if not account.password:
        return {
            'status': 'error',
            'error': 'No password configured for account',
            'task_id': task_id
        }
    
    # Update task state with progress
    def progress_callback(downloaded: int, total: int):
        self.update_state(
            state='PROGRESS',
            meta={
                'account': account_email,
                'downloaded': downloaded,
                'total': total,
                'percent': round((downloaded / total) * 100, 1) if total > 0 else 0
            }
        )
        update_progress(account_email, {
            'downloaded': downloaded,
            'total_emails': total
        })
    
    try:
        # Start sync
        update_progress(account_email, {
            'status': 'started',
            'task_id': task_id,
            'started_at': datetime.utcnow()
        })
        
        emails = download_all_emails_for_account(
            account=account,
            since_days=since_days,
            progress_callback=progress_callback
        )
        
        # Update completion status
        result = {
            'status': 'success',
            'account': account_email,
            'emails_downloaded': len(emails),
            'task_id': task_id,
            'completed_at': datetime.utcnow().isoformat()
        }
        
        update_progress(account_email, {
            'status': 'completed',
            'completed_at': datetime.utcnow(),
            'emails_downloaded': len(emails)
        })
        
        return result
        
    except Exception as e:
        logger.error(f"Error syncing account {account_email}: {e}")
        update_progress(account_email, {
            'status': 'error',
            'error': str(e)
        })
        raise


@celery_app.task(
    bind=True,
    name='backend.tasks.email_tasks.sync_all_accounts',
    max_retries=1,
)
def sync_all_accounts(
    self,
    since_days: int = 0,
    max_parallel: int = 5
) -> Dict[str, Any]:
    """
    Start parallel email sync for all active accounts.
    Creates individual tasks for each account.
    
    Args:
        since_days: Only fetch emails from last N days (0 = all)
        max_parallel: Maximum accounts to sync in parallel
        
    Returns:
        Dictionary of account -> task_id mappings
    """
    from celery import group
    
    # Get all active accounts using background pool
    db = get_background_db()
    accounts_collection = db['imap_accounts']
    
    active_accounts = list(accounts_collection.find(
        {"is_active": True},
        {"email": 1}
    ))
    
    if not active_accounts:
        return {
            'status': 'no_accounts',
            'message': 'No active accounts found to sync'
        }
    
    # Create task group
    task_group = group(
        sync_account_emails.s(
            account_email=acc["email"],
            since_days=since_days
        )
        for acc in active_accounts
    )
    
    # Execute in parallel (Celery handles concurrency)
    group_result = task_group.apply_async()
    
    return {
        'status': 'started',
        'group_id': group_result.id,
        'accounts': [acc["email"] for acc in active_accounts],
        'task_count': len(active_accounts),
        'started_at': datetime.utcnow().isoformat()
    }


@celery_app.task(
    name='backend.tasks.email_tasks.get_email_counts',
    max_retries=2,
)
def get_email_counts(since_days: int = 0) -> Dict[str, Any]:
    """
    Get email counts for all active accounts.
    This is a quick task that just counts without downloading.
    
    Args:
        since_days: Only count emails from last N days (0 = all)
        
    Returns:
        Dictionary of account -> folder counts
    """
    from leads.parallel_email_sync import get_all_accounts_email_count
    
    return get_all_accounts_email_count(since_days)


@celery_app.task(
    bind=True,
    name='backend.tasks.email_tasks.stop_sync',
)
def stop_sync(self, account_email: Optional[str] = None) -> Dict[str, Any]:
    """
    Stop ongoing sync tasks.
    
    Args:
        account_email: Specific account to stop (None = stop all)
        
    Returns:
        Status of the stop operation
    """
    from celery_app import celery_app
    
    # Get running email sync tasks
    inspector = celery_app.control.inspect()
    active_tasks = inspector.active() or {}
    
    stopped_tasks = []
    
    for worker, tasks in active_tasks.items():
        for task in tasks:
            if 'email_tasks' in task.get('name', ''):
                task_args = task.get('args', [])
                
                # If specific account, check if matches
                if account_email:
                    if task_args and task_args[0] == account_email:
                        celery_app.control.revoke(task['id'], terminate=True)
                        stopped_tasks.append(task['id'])
                else:
                    # Stop all email tasks
                    celery_app.control.revoke(task['id'], terminate=True)
                    stopped_tasks.append(task['id'])
    
    return {
        'status': 'stopped',
        'stopped_tasks': stopped_tasks,
        'count': len(stopped_tasks)
    }


@celery_app.task(
    name='backend.tasks.email_tasks.get_sync_status',
)
def get_sync_status(account_email: Optional[str] = None) -> Dict[str, Any]:
    """
    Get the current sync status for accounts.
    
    Args:
        account_email: Specific account to check (None = all accounts)
        
    Returns:
        Sync status information
    """
    progress_collection = get_background_collection('parallel_sync_progress')
    
    if account_email:
        progress = progress_collection.find_one({"email": account_email})
        if progress:
            progress['_id'] = str(progress['_id'])
        return progress or {'status': 'not_found', 'email': account_email}
    else:
        # Get all progress records
        all_progress = list(progress_collection.find())
        for p in all_progress:
            p['_id'] = str(p['_id'])
        return {
            'accounts': all_progress,
            'count': len(all_progress)
        }
