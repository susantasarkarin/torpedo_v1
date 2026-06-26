"""
Panel invitation periodic tasks.

send_daily_panel_invitations runs once per day (via Celery Beat) and sends
invitation emails to every eligible panelist lead.  Per-address it stops when:
  - the panelist completes double opt-in (signed up)
  - their address bounces or they unsubscribe (suppression list)
  - they were already invited today (daily_mode dedup)
"""

import logging
from backend.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="backend.tasks.panel_tasks.send_daily_panel_invitations",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def send_daily_panel_invitations(self):
    """Send one invitation email per eligible lead per day."""
    try:
        try:
            from services.panel_email_service import send_bulk_invitations
        except ImportError:
            from backend.services.panel_email_service import send_bulk_invitations

        result = send_bulk_invitations(daily_mode=True)
        logger.info(
            f"[daily-panel-invite] sent={result.get('sent')} "
            f"skipped={result.get('skipped')} failed={result.get('failed')} "
            f"capped={result.get('capped')} batch={result.get('batch_id')}"
        )
        return result
    except Exception as exc:
        logger.error(f"[daily-panel-invite] error: {exc}", exc_info=True)
        raise self.retry(exc=exc)


@celery_app.task(
    name="backend.tasks.panel_tasks.sync_panel_registrations",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def sync_panel_registrations(self):
    """Mark Torpedo panelists who completed registration on the SFW panel.

    Runs before the daily invite cron so freshly-registered users are excluded
    from that day's "register" invites and included in the survey-available send.
    """
    try:
        try:
            from services.panel_sync_service import sync_registrations_from_sfw
        except ImportError:
            from backend.services.panel_sync_service import sync_registrations_from_sfw

        result = sync_registrations_from_sfw()
        logger.info(
            f"[panel-sync-registrations] fetched={result.get('fetched')} "
            f"unique={result.get('unique_emails')} newly_marked={result.get('newly_marked')} "
            f"log_confirmed={result.get('log_confirmed')}"
        )
        return result
    except Exception as exc:
        logger.error(f"[panel-sync-registrations] error: {exc}", exc_info=True)
        raise self.retry(exc=exc)


@celery_app.task(
    name="backend.tasks.panel_tasks.send_daily_panel_login_invitations",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def send_daily_panel_login_invitations(self):
    """Send one login reminder email per registered panelist per day."""
    try:
        try:
            from services.panel_email_service import send_bulk_login_invitations
        except ImportError:
            from backend.services.panel_email_service import send_bulk_login_invitations

        result = send_bulk_login_invitations()
        logger.info(
            f"[daily-panel-login-invite] sent={result.get('sent')} "
            f"skipped={result.get('skipped')} failed={result.get('failed')} "
            f"capped={result.get('capped')} batch={result.get('batch_id')}"
        )
        return result
    except Exception as exc:
        logger.error(f"[daily-panel-login-invite] error: {exc}", exc_info=True)
        raise self.retry(exc=exc)
