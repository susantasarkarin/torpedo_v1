"""
Celery Application Configuration
Uses Redis as broker for distributed task processing
"""

import os
from celery import Celery
from kombu import Queue

# Redis configuration (using existing Redis setup from session_store)
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
CELERY_BROKER_URL = f"{REDIS_URL}/0"
CELERY_RESULT_BACKEND = f"{REDIS_URL}/1"

# Create Celery application
celery_app = Celery(
    'campaign_platform',
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        'tasks.email_tasks',
        'tasks.ai_tasks',
        'tasks.api_tasks',
        'tasks.finance_tasks',
        'tasks.sales_tasks',
        'tasks.traffic_tasks',
    ]
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # Task execution settings
    task_acks_late=True,  # Acknowledge after task completion
    task_reject_on_worker_lost=True,  # Re-queue if worker dies
    task_time_limit=3600,  # 1 hour max per task
    task_soft_time_limit=3300,  # Soft limit 55 min
    
    # Worker settings
    worker_prefetch_multiplier=1,  # Fair distribution
    worker_concurrency=4,  # Number of parallel workers
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks (memory management)
    
    # Result settings
    result_expires=86400,  # Results expire after 24 hours
    result_extended=True,  # Store additional task metadata
    
    # Queue settings
    task_default_queue='default',
    task_queues=(
        Queue('default', routing_key='default'),
        Queue('email_sync', routing_key='email.#'),
        Queue('ai_processing', routing_key='ai.#'),
        Queue('api_tasks', routing_key='api.#'),
        Queue('finance', routing_key='finance.#'),
        Queue('sales', routing_key='sales.#'),
        Queue('traffic', routing_key='traffic.#'),
    ),
    
    # Task routing
    task_routes={
        'backend.tasks.email_tasks.*': {'queue': 'email_sync', 'routing_key': 'email.sync'},
        'backend.tasks.ai_tasks.*': {'queue': 'ai_processing', 'routing_key': 'ai.process'},
        'backend.tasks.api_tasks.*': {'queue': 'api_tasks', 'routing_key': 'api.task'},
        'backend.tasks.finance_tasks.*': {'queue': 'finance', 'routing_key': 'finance.task'},
        'backend.tasks.sales_tasks.*': {'queue': 'sales', 'routing_key': 'sales.task'},
        'backend.tasks.traffic_tasks.*': {'queue': 'traffic', 'routing_key': 'traffic.task'},
    },
    
    # Beat scheduler (for periodic tasks)
    beat_schedule={
        'sync-all-accounts-hourly': {
            'task': 'backend.tasks.email_tasks.sync_all_accounts',
            'schedule': 3600.0,  # Every hour
            'options': {'queue': 'email_sync'}
        },
    },
    
    # Retry settings
    task_annotations={
        '*': {
            'rate_limit': '100/m',  # Max 100 tasks per minute
        },
        'backend.tasks.ai_tasks.*': {
            'rate_limit': '10/m',  # AI tasks limited due to API quotas
        },
    },
)


# Task state tracking
class TaskStatus:
    """Helper class to track task status in Redis."""
    PENDING = 'PENDING'
    STARTED = 'STARTED'
    PROGRESS = 'PROGRESS'
    SUCCESS = 'SUCCESS'
    FAILURE = 'FAILURE'
    REVOKED = 'REVOKED'


def get_task_status(task_id: str) -> dict:
    """Get the status of a task by ID."""
    from celery.result import AsyncResult
    
    result = AsyncResult(task_id, app=celery_app)
    
    response = {
        'task_id': task_id,
        'status': result.status,
        'ready': result.ready(),
    }
    
    if result.ready():
        if result.successful():
            response['result'] = result.result
        else:
            response['error'] = str(result.result) if result.result else 'Unknown error'
    elif result.status == 'PROGRESS':
        response['progress'] = result.info
    
    return response


def revoke_task(task_id: str, terminate: bool = False):
    """Revoke (cancel) a task."""
    celery_app.control.revoke(task_id, terminate=terminate)
    return {'status': 'revoked', 'task_id': task_id}


# Startup hook
@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """Set up periodic tasks after Celery is configured."""
    pass  # Periodic tasks are defined in beat_schedule above


if __name__ == '__main__':
    celery_app.start()
