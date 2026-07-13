"""
Celery Application Configuration
Uses Redis as broker for distributed task processing
"""

import os
from celery import Celery
from celery.schedules import crontab
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
        'backend.tasks.email_tasks',
        'backend.tasks.ai_tasks',
        'backend.tasks.api_tasks',
        'backend.tasks.finance_tasks',
        'backend.tasks.sales_tasks',
        'backend.tasks.traffic_tasks',
        'backend.tasks.outreach_tasks',
        'backend.tasks.lead_agent_tasks',
        'backend.tasks.enrichment_tasks',
        'backend.tasks.linkedin_tasks',
        'backend.tasks.cint_survey_scoring',
        'backend.tasks.panel_tasks',
        'backend.tasks.crm_spine_tasks',
        'backend.tasks.yield_tasks',
        'backend.tasks.mail_pool_ai_tasks',
        'backend.app.tasks.outreach_tasks',
        'backend.campaigns.send_queue',
        'backend.sales.tasks',
        'backend.sales.outreach_pipeline',
        'backend.sales.mail_pool_extractor',
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
    worker_prefetch_multiplier=4,  # Better throughput (was 1)
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
        Queue('surveys', routing_key='surveys.#'),  # Dedicated queue for CPX/CINT - never blocked by email sync
        Queue('linkedin_automation', routing_key='linkedin.#'),  # LinkedIn account automation
    ),
    
    # Task routing
    task_routes={
        'backend.tasks.email_tasks.*': {'queue': 'email_sync', 'routing_key': 'email.sync'},
        'backend.tasks.ai_tasks.*': {'queue': 'ai_processing', 'routing_key': 'ai.process'},
        'backend.tasks.api_tasks.*': {'queue': 'api_tasks', 'routing_key': 'api.task'},
        'backend.tasks.finance_tasks.*': {'queue': 'finance', 'routing_key': 'finance.task'},
        'backend.tasks.sales_tasks.*': {'queue': 'sales', 'routing_key': 'sales.task'},
        'backend.tasks.traffic_tasks.*': {'queue': 'traffic', 'routing_key': 'traffic.task'},
        'backend.tasks.outreach_tasks.*': {'queue': 'api_tasks', 'routing_key': 'outreach.#'},
        'backend.tasks.linkedin_tasks.*': {'queue': 'linkedin_automation', 'routing_key': 'linkedin.#'},
        # Route survey tasks to dedicated queue
        'backend.tasks.traffic_tasks.fetch_and_broadcast_cpx_surveys': {'queue': 'surveys', 'routing_key': 'surveys.cpx'},
        'backend.tasks.survey_tasks.*': {'queue': 'surveys', 'routing_key': 'surveys.task'},
    },
    
    # Beat scheduler (for periodic tasks)
    beat_schedule={
        'sync-all-accounts-hourly': {
            'task': 'backend.tasks.email_tasks.sync_all_accounts',
            'schedule': 3600.0,  # Every hour
            'options': {'queue': 'email_sync'}
        },
        'linkedin-daily-automation': {
            'task': 'backend.tasks.linkedin_tasks.run_daily_linkedin_automation',
            'schedule': 86400.0,  # Every 24 hours (daily)
            'options': {'queue': 'linkedin_automation'}
        },
        'linkedin-cleanup-jobs': {
            'task': 'backend.tasks.linkedin_tasks.cleanup_old_jobs',
            'schedule': 604800.0,  # Every 7 days
            'options': {'queue': 'linkedin_automation', 'kwargs': {'days': 30}}
        },
        'panel-sync-registrations': {
            # 8:30 AM IST = 03:00 UTC — pull SFW-panel signups and mark them
            # registered BEFORE the invite cron, so they drop out of the invite
            # send and into the survey-available send the same day.
            'task': 'backend.tasks.panel_tasks.sync_panel_registrations',
            'schedule': crontab(hour=3, minute=0),
            'options': {'queue': 'default'},
        },
        'panel-daily-invitations': {
            # 9:00 AM IST = 03:30 UTC — runs once per day until each lead signs up,
            # bounces, or unsubscribes
            'task': 'backend.tasks.panel_tasks.send_daily_panel_invitations',
            'schedule': crontab(hour=3, minute=30),
            'options': {'queue': 'default'},
        },
        'mail-pool-ai-batch': {
            # Every 10 min: AI-process new mail-pool emails (summary,
            # contacts, RFQ -> spine + draft estimate, follow-up drafts).
            # 200 emails/run on Haiku ≈ 28.8K/day max — clears the 361K
            # backlog in ~2 weeks. A 200-email run finishes in ~4-7 min,
            # inside the 10-min window.
            'task': 'backend.tasks.mail_pool_ai_tasks.process_mail_pool_batch',
            'schedule': 600.0,
            'kwargs': {'limit': 200},
            'options': {'queue': 'ai_processing'},
        },
        'yield-abandoned-session-sweep': {
            # Hourly: count never-returned Cint redirects as abandoned
            # entrants so conversion reflects wasted clicks and the
            # auto-deactivation can fire for callback-silent surveys.
            'task': 'backend.tasks.yield_tasks.sweep_abandoned_cint_sessions',
            'schedule': 3600.0,
            # NOTE: no running worker consumes the 'surveys' queue on prod
            # (only default / linkedin_automation / sales,ai_processing) —
            # anything routed there never executes. Keep this on 'default'.
            'options': {'queue': 'default'},
        },
        'crm-spine-nightly-reconcile': {
            # 8:00 AM IST = 02:30 UTC — re-converge crm_db against finance/
            # sales/QRE source collections (backfills, renames, deletions).
            'task': 'backend.tasks.crm_spine_tasks.reconcile_crm_spine',
            'schedule': crontab(hour=2, minute=30),
            'options': {'queue': 'default'},
        },
        'panel-daily-login-invitations': {
            # 10:00 AM IST = 04:30 UTC — daily login reminder to registered panelists
            'task': 'backend.tasks.panel_tasks.send_daily_panel_login_invitations',
            'schedule': crontab(hour=4, minute=30),
            'options': {'queue': 'default'},
        },
    },
    
    # Retry settings
    task_annotations={
        '*': {
            'rate_limit': '100/m',  # Max 100 tasks per minute
        },
        'backend.tasks.ai_tasks.*': {
            'rate_limit': '20/m',  # Increased from 10/m - AI tasks for classification
        },
        'backend.tasks.survey_tasks.*': {
            'rate_limit': '60/m',  # Survey tasks should be fast
        },
        'backend.tasks.linkedin_tasks.*': {
            'rate_limit': '50/m',  # LinkedIn tasks can run fairly often
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
