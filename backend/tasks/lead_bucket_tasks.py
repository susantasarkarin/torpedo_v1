"""
Lead bucket classification periodic task — runs bucket_classifier.py
(leads/bucket_classifier.py) over newly-generated leads on a schedule, so the
SFW/COGENTIX_RESEARCH/BIM/REJECT profile classification keeps pace with the
lead-gen pipeline instead of only running when someone invokes the script by
hand. Routed to the ai_processing queue.
"""

import logging

from celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="backend.tasks.lead_bucket_tasks.classify_lead_bucket_batch",
    bind=True,
    queue="ai_processing",
    max_retries=1,
    default_retry_delay=600,
    rate_limit="2/m",
)
def classify_lead_bucket_batch(self, limit: int = None):
    """Classify up to `limit` unclassified leads (newest first). Defaults to
    CLASSIFY_DAILY_CAP when limit is not given."""
    try:
        from leads.bucket_classifier import run, CLASSIFY_DAILY_CAP
        result = run(limit=limit or CLASSIFY_DAILY_CAP)
        logger.info(f"[bucket-classifier] batch done: {result}")
        return result
    except Exception as e:
        logger.error(f"[bucket-classifier] batch failed: {e}", exc_info=True)
        raise self.retry(exc=e)
