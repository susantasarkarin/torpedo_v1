"""
Mail Pool AI periodic tasks — runs the AI mail-desk pipeline
(sales/mail_pool_ai.py) over unanalyzed mail-pool emails on a schedule, so
summaries, contact extraction, RFQ logging and follow-up drafts appear
without anyone pressing a button. Routed to the ai_processing queue and kept
to small batches per run to respect AI rate limits.
"""

import logging

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
def process_mail_pool_batch(self, limit: int = None):
    """Analyze up to `limit` new mail-pool emails (oldest first). Defaults to
    MAIL_AI_MAX_PER_RUN when limit is not given.

    Kept for manual/per-email use; the scheduled path is the sender-level
    task below (one AI call per sender instead of per email).
    """
    try:
        from sales.mail_pool_ai import process_batch, MAIL_AI_MAX_PER_RUN
        result = process_batch(limit=limit or MAIL_AI_MAX_PER_RUN)
        logger.info(f"[mail-ai] batch done: {result}")
        return result
    except Exception as e:
        logger.error(f"[mail-ai] batch failed: {e}", exc_info=True)
        raise self.retry(exc=e)


@celery_app.task(
    name="backend.tasks.mail_pool_ai_tasks.process_mail_pool_sender_batch",
    bind=True,
    queue="ai_processing",
    max_retries=1,
    default_retry_delay=600,
    rate_limit="2/m",
)
def process_mail_pool_sender_batch(self, limit: int = 50):
    """Analyze up to `limit` SENDERS with unanalyzed mail-pool emails.

    One AI call per sender (sampling their newest emails) stamps every email
    from that sender — ~6.3K calls cover the whole 361K-email pool, vs 361K
    calls for per-email analysis.
    """
    try:
        from sales.mail_pool_ai import process_sender_batch
        result = process_sender_batch(limit=limit)
        logger.info(f"[mail-ai] sender batch done: {result}")
        return result
    except Exception as e:
        logger.error(f"[mail-ai] sender batch failed: {e}", exc_info=True)
        raise self.retry(exc=e)


@celery_app.task(
    name="backend.tasks.mail_pool_ai_tasks.rebuild_rfqs_all_senders_batch",
    bind=True,
    queue="ai_processing",
    max_retries=1,
    default_retry_delay=600,
    rate_limit="2/m",
)
def rebuild_rfqs_all_senders_batch(self, limit: int = 50):
    """One-time RFQ rebuild backfill (POST /rfq/resync-all): re-scan up to
    `limit` senders whose rfq_scan ledger is empty (fresh, or reset by
    scripts/clear_rfq_data.py) via deep_scan_sender_rfqs. Same rate limit as
    the regular sender batch above — call repeatedly to drain the backlog.
    """
    try:
        from sales.mail_pool_ai import rebuild_rfqs_for_all_senders
        result = rebuild_rfqs_for_all_senders(limit=limit)
        logger.info(f"[mail-ai] rebuild batch done: {result}")
        return result
    except Exception as e:
        logger.error(f"[mail-ai] rebuild batch failed: {e}", exc_info=True)
        raise self.retry(exc=e)


@celery_app.task(
    name="backend.tasks.mail_pool_ai_tasks.audit_prefiltered_mail",
    bind=True,
    queue="ai_processing",
    max_retries=1,
    default_retry_delay=600,
)
def audit_prefiltered_mail(self, sample: int = None):
    """Nightly safety net: re-check a random sample of rule-prefiltered-out
    emails with the cheap model and record any disagreements, so a too-
    aggressive rule filter silently eating client mail gets caught."""
    try:
        from sales.mail_pool_ai import audit_prefiltered_sample, MAIL_AI_PREFILTER_AUDIT_SAMPLE
        result = audit_prefiltered_sample(sample or MAIL_AI_PREFILTER_AUDIT_SAMPLE)
        logger.info(f"[mail-ai] prefilter audit done: {result}")
        return result
    except Exception as e:
        logger.error(f"[mail-ai] prefilter audit failed: {e}", exc_info=True)
        raise self.retry(exc=e)
