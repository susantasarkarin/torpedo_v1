"""
API Response Celery Tasks
Tasks for tracking async operations and providing status updates
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from celery_app import celery_app, get_task_status, revoke_task
from db_pools import get_api_db, get_api_collection

logger = logging.getLogger(__name__)


# Redis-based task status storage
class TaskStatusStore:
    """Store and retrieve task status using Redis."""
    
    def __init__(self):
        import redis
        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
        self.redis_client = redis.from_url(f"{redis_url}/2")  # Use DB 2 for task status
        self.expiry = 86400  # 24 hour expiry
    
    def set_status(self, operation_id: str, status: Dict[str, Any]):
        """Set operation status."""
        status['updated_at'] = datetime.utcnow().isoformat()
        self.redis_client.setex(
            f"task_status:{operation_id}",
            self.expiry,
            json.dumps(status, default=str)
        )
    
    def get_status(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Get operation status."""
        data = self.redis_client.get(f"task_status:{operation_id}")
        if data:
            return json.loads(data)
        return None
    
    def delete_status(self, operation_id: str):
        """Delete operation status."""
        self.redis_client.delete(f"task_status:{operation_id}")
    
    def list_operations(self, prefix: str = "") -> List[Dict[str, Any]]:
        """List all operations matching prefix."""
        pattern = f"task_status:{prefix}*"
        keys = self.redis_client.keys(pattern)
        operations = []
        for key in keys:
            data = self.redis_client.get(key)
            if data:
                op = json.loads(data)
                op['operation_id'] = key.decode().replace('task_status:', '')
                operations.append(op)
        return operations


# Singleton instance
_status_store = None

def get_status_store() -> TaskStatusStore:
    """Get the singleton status store instance."""
    global _status_store
    if _status_store is None:
        _status_store = TaskStatusStore()
    return _status_store


@celery_app.task(
    name='backend.tasks.api_tasks.start_operation',
)
def start_operation(
    operation_type: str,
    operation_id: str,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Register a new long-running operation.
    
    Args:
        operation_type: Type of operation (email_sync, ai_processing, etc.)
        operation_id: Unique ID for this operation
        metadata: Additional operation metadata
        
    Returns:
        Operation registration result
    """
    store = get_status_store()
    
    status = {
        'operation_id': operation_id,
        'operation_type': operation_type,
        'status': 'started',
        'progress': 0,
        'started_at': datetime.utcnow().isoformat(),
        'metadata': metadata or {}
    }
    
    store.set_status(operation_id, status)
    
    return status


@celery_app.task(
    name='backend.tasks.api_tasks.update_operation_progress',
)
def update_operation_progress(
    operation_id: str,
    progress: int,
    message: Optional[str] = None,
    extra_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Update progress of a running operation.
    
    Args:
        operation_id: Operation ID to update
        progress: Progress percentage (0-100)
        message: Optional status message
        extra_data: Additional data to store
        
    Returns:
        Updated operation status
    """
    store = get_status_store()
    
    current = store.get_status(operation_id) or {}
    
    current['progress'] = progress
    current['status'] = 'in_progress' if progress < 100 else 'completed'
    
    if message:
        current['message'] = message
    
    if extra_data:
        current.update(extra_data)
    
    store.set_status(operation_id, current)
    
    return current


@celery_app.task(
    name='backend.tasks.api_tasks.complete_operation',
)
def complete_operation(
    operation_id: str,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None
) -> Dict[str, Any]:
    """
    Mark an operation as completed.
    
    Args:
        operation_id: Operation ID to complete
        result: Operation result data
        error: Error message if failed
        
    Returns:
        Final operation status
    """
    store = get_status_store()
    
    current = store.get_status(operation_id) or {}
    
    current['status'] = 'failed' if error else 'completed'
    current['progress'] = 100
    current['completed_at'] = datetime.utcnow().isoformat()
    
    if result:
        current['result'] = result
    
    if error:
        current['error'] = error
    
    store.set_status(operation_id, current)
    
    return current


@celery_app.task(
    name='backend.tasks.api_tasks.get_operation_status',
)
def get_operation_status(operation_id: str) -> Dict[str, Any]:
    """
    Get the status of an operation.
    
    Args:
        operation_id: Operation ID to check
        
    Returns:
        Operation status or not found message
    """
    store = get_status_store()
    
    status = store.get_status(operation_id)
    
    if status:
        return status
    
    # Try to get from Celery result backend
    celery_status = get_task_status(operation_id)
    
    return celery_status or {
        'status': 'not_found',
        'operation_id': operation_id
    }


@celery_app.task(
    name='backend.tasks.api_tasks.cancel_operation',
)
def cancel_operation(operation_id: str) -> Dict[str, Any]:
    """
    Cancel a running operation.
    
    Args:
        operation_id: Operation ID to cancel
        
    Returns:
        Cancellation result
    """
    store = get_status_store()
    
    # Update status store
    current = store.get_status(operation_id) or {}
    current['status'] = 'cancelled'
    current['cancelled_at'] = datetime.utcnow().isoformat()
    store.set_status(operation_id, current)
    
    # Revoke Celery task if it's a task ID
    try:
        revoke_task(operation_id, terminate=True)
    except Exception as e:
        logger.warning(f"Could not revoke task {operation_id}: {e}")
    
    return {
        'status': 'cancelled',
        'operation_id': operation_id
    }


@celery_app.task(
    name='backend.tasks.api_tasks.list_active_operations',
)
def list_active_operations(operation_type: Optional[str] = None) -> Dict[str, Any]:
    """
    List all active operations.
    
    Args:
        operation_type: Filter by operation type (optional)
        
    Returns:
        List of active operations
    """
    store = get_status_store()
    
    all_ops = store.list_operations()
    
    # Filter to active only
    active_ops = [
        op for op in all_ops
        if op.get('status') in ['started', 'in_progress', 'PENDING', 'STARTED', 'PROGRESS']
    ]
    
    # Filter by type if specified
    if operation_type:
        active_ops = [
            op for op in active_ops
            if op.get('operation_type') == operation_type
        ]
    
    return {
        'operations': active_ops,
        'count': len(active_ops)
    }


@celery_app.task(
    name='backend.tasks.api_tasks.cleanup_old_operations',
)
def cleanup_old_operations(max_age_hours: int = 24) -> Dict[str, Any]:
    """
    Clean up old completed operations from the status store.
    
    Args:
        max_age_hours: Max age in hours for completed operations
        
    Returns:
        Cleanup result with count of removed operations
    """
    store = get_status_store()
    
    all_ops = store.list_operations()
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
    
    removed = 0
    
    for op in all_ops:
        completed_at = op.get('completed_at')
        if completed_at:
            try:
                completed_dt = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                if completed_dt < cutoff:
                    store.delete_status(op['operation_id'])
                    removed += 1
            except (ValueError, TypeError):
                continue
    
    return {
        'status': 'completed',
        'removed': removed,
        'remaining': len(all_ops) - removed
    }


# ============== HELPER FUNCTIONS FOR API ROUTES ==============

def start_async_email_sync(
    account_email: Optional[str] = None,
    since_days: int = 0
) -> Dict[str, Any]:
    """
    Start async email sync and return operation ID for polling.
    
    This function is called from API routes.
    """
    from tasks.email_tasks import sync_account_emails, sync_all_accounts
    import uuid
    
    operation_id = str(uuid.uuid4())
    
    if account_email:
        # Single account sync
        task = sync_account_emails.apply_async(
            args=[account_email, since_days],
            task_id=operation_id
        )
    else:
        # All accounts sync
        task = sync_all_accounts.apply_async(
            args=[since_days],
            task_id=operation_id
        )
    
    # Register operation
    start_operation.delay(
        operation_type='email_sync',
        operation_id=operation_id,
        metadata={
            'account_email': account_email,
            'since_days': since_days
        }
    )
    
    return {
        'operation_id': operation_id,
        'task_id': task.id,
        'status': 'started',
        'poll_url': f'/api/operations/{operation_id}/status'
    }


def start_async_ai_processing(
    account_email: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """
    Start async AI processing pipeline and return operation ID for polling.
    
    This function is called from API routes.
    """
    from tasks.ai_tasks import process_new_leads_pipeline
    import uuid
    
    operation_id = str(uuid.uuid4())
    
    task = process_new_leads_pipeline.apply_async(
        args=[account_email, limit],
        task_id=operation_id
    )
    
    # Register operation
    start_operation.delay(
        operation_type='ai_processing',
        operation_id=operation_id,
        metadata={
            'account_email': account_email,
            'limit': limit
        }
    )
    
    return {
        'operation_id': operation_id,
        'task_id': task.id,
        'status': 'started',
        'poll_url': f'/api/operations/{operation_id}/status'
    }
