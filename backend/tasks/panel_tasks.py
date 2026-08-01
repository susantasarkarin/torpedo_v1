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
    # Override the app-wide 55-min soft / 60-min hard limit (celery_app.py):
    # at the default SES_SEND_RATE this job needs ~2 hours to work through a
    # full day's SES budget instead of being killed after ~3,300 sends. The
    # per-address SES budget check inside send_bulk_invitations still stops
    # the loop on its own once the quota is used, so this is just headroom.
    soft_time_limit=10800,  # 3h
    time_limit=11100,       # 3h5m
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
    name="backend.tasks.panel_tasks.sync_ses_suppression",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    soft_time_limit=1800,  # 30m — the list can run to hundreds of pages
    time_limit=1900,
)
def sync_ses_suppression(self):
    """Mirror SES's account-level suppression list into panel_email_suppression.

    Runs before the invite crons so that day's send skips addresses SES has
    already marked dead, instead of re-bouncing them and pushing the account
    bounce rate toward the 5% review threshold.
    """
    try:
        try:
            from services.panel_bounce_handler import sync_ses_suppression_list
        except ImportError:
            from backend.services.panel_bounce_handler import sync_ses_suppression_list

        result = sync_ses_suppression_list()
        logger.info(
            f"[panel-suppression-sync] seen={result.get('seen')} "
            f"added={result.get('added')} pages={result.get('pages')} "
            f"truncated={result.get('truncated')}"
        )
        return result
    except Exception as exc:
        logger.error(f"[panel-suppression-sync] error: {exc}", exc_info=True)
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
    # See send_daily_panel_invitations above — same fix, same reasoning.
    soft_time_limit=10800,  # 3h
    time_limit=11100,       # 3h5m
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
