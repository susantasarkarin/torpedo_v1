"""
Panel invitation periodic tasks.

send_daily_panel_invitations runs once per day (via Celery Beat) and sends
invitation emails to every eligible panelist lead.  Per-address it stops when:
  - the panelist completes double opt-in (signed up)
  - their address bounces or they unsubscribe (suppression list)
  - they are still inside their invite cooldown (daily_mode enforces
    PANEL_INVITE_MIN_GAP_DAYS, default 3 — i.e. mailed Monday, next eligible
    Thursday)

The cron stays daily on purpose: each run mails whoever is due that day, so
the SES budget is spread evenly instead of arriving in every-third-day spikes.
"""

import logging
from backend.celery_app import celery_app

logger = logging.getLogger(__name__)


def _heartbeat(job_name: str, **extra) -> None:
    """Record that `job_name` completed. Never allowed to fail the task —
    losing the heartbeat write must not be worse than not writing it."""
    try:
        try:
            from services.panel_job_state import record_heartbeat
        except ImportError:
            from backend.services.panel_job_state import record_heartbeat
        record_heartbeat(job_name, extra or None)
    except Exception as e:
        logger.warning(f"[panel-heartbeat] failed to record {job_name}: {e}")


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
        _heartbeat("invite_cron", sent=result.get("sent"), failed=result.get("failed"))
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
        _heartbeat("suppression_sync", added=result.get("added"))
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
        _heartbeat("registration_sync", newly_marked=result.get("newly_marked"))
        return result
    except Exception as exc:
        logger.error(f"[panel-sync-registrations] error: {exc}", exc_info=True)
        raise self.retry(exc=exc)


@celery_app.task(
    name="backend.tasks.panel_tasks.promote_panelist_leads",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    soft_time_limit=3600,  # 1h — the dedup aggregation spans the traffic table
    time_limit=3700,
)
def promote_panelist_leads(self, limit: int = None):
    """Upsert parsing-page email captures into `panelists` so they get invited.

    Resumes from a stored watermark rather than a rolling lookback window. The
    original 7-day window was permanently inert: traffic stopped carrying email
    addresses on 2026-04-22, so the window matched nothing every night while
    ~37K never-contacted addresses sat unprocessed.

    Each run is capped (PANEL_LEAD_PROMOTION_MAX_PER_RUN, default 5000) so the
    backlog joins the mailable pool gradually and its bounce behaviour stays
    observable rather than arriving as one 37K spike.
    """
    try:
        try:
            from services.panel_lead_promotion import promote_traffic_leads_to_panelists
        except ImportError:
            from backend.services.panel_lead_promotion import promote_traffic_leads_to_panelists

        result = promote_traffic_leads_to_panelists(use_watermark=True, limit=limit)
        logger.info(
            f"[panel-lead-promotion] scanned={result.get('scanned')} "
            f"inserted={result.get('inserted')} "
            f"already_present={result.get('already_present')} "
            f"capped={result.get('capped')} "
            f"watermark={result.get('watermark_advanced_to')}"
        )
        _heartbeat("lead_promotion", scanned=result.get("scanned"), inserted=result.get("inserted"))
        return result
    except Exception as exc:
        logger.error(f"[panel-lead-promotion] error: {exc}", exc_info=True)
        raise self.retry(exc=exc)


@celery_app.task(
    name="backend.tasks.panel_tasks.run_panel_reengagement_drips",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    soft_time_limit=3600,  # 1h — drip batches are capped well below an SES day
    time_limit=3700,
)
def run_panel_reengagement_drips(self):
    """Nudge the three stalled funnel segments once per day.

    Per-stage caps (2-3 sends) and cooldowns (3-7 days) live in
    panel_drip_service.STAGES, so a daily cron does NOT mean daily mail: an
    individual receives at most a handful of reminders ever, then the sequence
    ends permanently.
    """
    try:
        try:
            from services.panel_drip_service import run_all_drip_stages
        except ImportError:
            from backend.services.panel_drip_service import run_all_drip_stages

        result = run_all_drip_stages()
        logger.info(f"[panel-drips] total_sent={result.get('total_sent')} stages={result.get('stages')}")
        _heartbeat("drip_cron", total_sent=result.get("total_sent"))
        return result
    except Exception as exc:
        logger.error(f"[panel-drips] error: {exc}", exc_info=True)
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
        _heartbeat("login_cron", sent=result.get("sent"), failed=result.get("failed"))
        return result
    except Exception as exc:
        logger.error(f"[daily-panel-login-invite] error: {exc}", exc_info=True)
        raise self.retry(exc=exc)


@celery_app.task(
    name="backend.tasks.panel_tasks.check_panel_health",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
    soft_time_limit=120,
    time_limit=150,
)
def check_panel_health(self):
    """Hourly health snapshot: stale crons, send failure rate, SES quota.

    Logs ERROR/WARNING on threshold breach so it is visible in
    journalctl -u torpedo-backend and picked up by any future log shipper.
    This is what would have caught lead_promotion scanning 0 leads every
    night for two weeks, and is the reason it now can not happen silently
    again.
    """
    try:
        try:
            from services.panel_health import check_panel_health as run_check
        except ImportError:
            from backend.services.panel_health import check_panel_health as run_check

        result = run_check()
        logger.info(
            f"[panel-health] healthy={result.get('healthy')} "
            f"problems={len(result.get('problems') or [])}"
        )
        return result
    except Exception as exc:
        logger.error(f"[panel-health] check itself failed: {exc}", exc_info=True)
        raise self.retry(exc=exc)
