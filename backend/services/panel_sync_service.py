"""
Panel Registration Sync — reconcile SFW panel signups into Torpedo panelists.

People complete registration on panel.surveyfieldwork.com (the SFW panel app,
a separate Node service + Mongo). This service pulls the list of email-verified
registrants from the SFW admin API and marks the matching Torpedo `panelists`
records as `double_opt_in_completed=True`.

Effect of marking a panelist registered:
  - send_daily_panel_invitations stops emailing them the "register" invite
  - send_daily_panel_login_invitations starts emailing them "surveys available"

Idempotent: re-marking an already-registered panelist is a no-op. Runs daily
via the `sync_panel_registrations` Celery task, just before the invite cron.
"""

import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from services.panel_bounce_handler import (
    panelists_collection,
    invitation_log_collection,
)

logger = logging.getLogger(__name__)

# SFW admin API — same host/key the dashboard proxy uses (X-Internal-Key header,
# validated against INTERNAL_API_KEY on the sfw-api side).
SFW_PANEL_API_BASE = os.getenv("SFW_PANEL_API_BASE", "https://panel.surveyfieldwork.com/api/admin")
SFW_INTERNAL_KEY = os.getenv("SFW_INTERNAL_KEY", "")
SFW_SYNC_TIMEOUT = int(os.getenv("SFW_SYNC_TIMEOUT", "60"))
SFW_SYNC_FETCH_LIMIT = int(os.getenv("SFW_SYNC_FETCH_LIMIT", "100000"))

_MARK_BATCH_SIZE = 5000


def _fetch_registered_emails(since: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch verified registrants from the SFW panel admin API."""
    if not SFW_INTERNAL_KEY:
        raise RuntimeError("SFW_INTERNAL_KEY is not configured; cannot sync registrations")

    params: Dict[str, Any] = {"limit": SFW_SYNC_FETCH_LIMIT}
    if since:
        params["since"] = since

    resp = requests.get(
        f"{SFW_PANEL_API_BASE}/registered-emails",
        headers={"X-Internal-Key": SFW_INTERNAL_KEY},
        params=params,
        timeout=SFW_SYNC_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("registrants", []) if isinstance(data, dict) else []


def sync_registrations_from_sfw(
    since: Optional[str] = None,
    update_invitation_log: bool = True,
) -> Dict[str, Any]:
    """
    Pull registered emails from the SFW panel and mark matching Torpedo panelists
    as double-opt-in completed. Returns a summary dict.
    """
    registrants = _fetch_registered_emails(since=since)

    # Dedupe + normalize emails
    emails = sorted({
        (r.get("email") or "").strip().lower()
        for r in registrants
        if (r.get("email") or "").strip()
    })

    if not emails:
        logger.info("[panel-sync] no registrants returned from SFW panel")
        return {
            "fetched": len(registrants),
            "unique_emails": 0,
            "newly_marked": 0,
            "log_confirmed": 0,
            "since": since,
        }

    now = datetime.utcnow()
    newly_marked = 0
    log_confirmed = 0

    for start in range(0, len(emails), _MARK_BATCH_SIZE):
        batch = emails[start:start + _MARK_BATCH_SIZE]

        # Only flip records not already registered — modified_count is the count
        # of genuinely new registrations picked up this run.
        res = panelists_collection.update_many(
            {"email": {"$in": batch}, "double_opt_in_completed": {"$ne": True}},
            {
                "$set": {
                    "double_opt_in_completed": True,
                    "double_opt_in_completed_at": now,
                    "email_verified": True,
                    "status": "confirmed",
                    "updated_at": now,
                    "registration_source": "sfw_panel_sync",
                }
            },
        )
        newly_marked += res.modified_count

        if update_invitation_log:
            log_res = invitation_log_collection.update_many(
                {"email": {"$in": batch}, "status": {"$in": ["sent", "soft_bounced"]}},
                {"$set": {"status": "confirmed", "confirmed_at": now,
                          "confirmation_metadata": {"source": "sfw_panel_sync"}}},
            )
            log_confirmed += log_res.modified_count

    summary = {
        "fetched": len(registrants),
        "unique_emails": len(emails),
        "newly_marked": newly_marked,
        "log_confirmed": log_confirmed,
        "since": since,
    }
    logger.info(
        f"[panel-sync] fetched={summary['fetched']} unique={summary['unique_emails']} "
        f"newly_marked={summary['newly_marked']} log_confirmed={summary['log_confirmed']}"
    )
    return summary
