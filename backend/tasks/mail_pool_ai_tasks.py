"""
Mail Pool AI periodic tasks — runs the AI mail-desk pipeline
(sales/mail_pool_ai.py) over unanalyzed mail-pool emails on a schedule, so
summaries, contact extraction, RFQ logging and follow-up drafts appear
without anyone pressing a button. Routed to the ai_processing queue and kept
to small batches per run to respect AI rate limits.
"""

import logging

try:
    from backend.celery_app import celery_app
except ImportError:
    from celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="backend.tasks.mail_pool_ai_tasks.process_mail_pool_batch",
    bind=True,
    queue="ai_processing",
    max_retries=1,
    default_retry_delay=600,
    rate_limit="2/m",
)
def process_mail_pool_batch(self, limit: int = 50):
    """Analyze up to `limit` new mail-pool emails with the AI pipeline."""
    try:
        try:
            from sales.mail_pool_ai import process_batch
        except ImportError:
            from backend.sales.mail_pool_ai import process_batch
        result = process_batch(limit=limit)
        logger.info(f"[mail-ai] batch done: {result}")
        return result
    except Exception as e:
        logger.error(f"[mail-ai] batch failed: {e}", exc_info=True)
        raise self.retry(exc=e)
