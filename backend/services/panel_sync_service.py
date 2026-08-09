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
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

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


def _parse_dt(value: Any) -> Optional[datetime]:
    """Accept the ISO strings / epoch millis the SFW API may hand back."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value / 1000 if value > 1e11 else value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


# SFW is a Node service and hands back camelCase; accept snake_case too so this
# keeps working if the admin API is ever normalised.
_COUNTRY_KEYS = ("country", "countryCode", "country_code")
_PROFILE_KEYS = ("profileComplete", "profile_complete", "isProfileComplete")
_LOGIN_KEYS = ("lastLogin", "last_login", "lastLoginAt", "last_login_at")


def _first(row: Dict[str, Any], keys) -> Any:
    for k in keys:
        if row.get(k) not in (None, ""):
            return row[k]
    return None


def _sfw_state_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map one SFW registrant into the mirrored `sfw_*` fields on a panelist.

    Namespaced rather than written onto `country` / `last_login` directly so a
    value that came from SFW is always distinguishable from one a panelist
    entered on Torpedo itself, and so a missing field in the API response can
    never blank out local data.
    """
    fields: Dict[str, Any] = {}

    country = _first(row, _COUNTRY_KEYS)
    if country:
        fields["sfw_country"] = str(country).strip().upper()[:2] if len(str(country).strip()) == 2 else str(country).strip()

    profile_complete = _first(row, _PROFILE_KEYS)
    if profile_complete is not None:
        fields["sfw_profile_complete"] = bool(profile_complete)

    last_login = _parse_dt(_first(row, _LOGIN_KEYS))
    if last_login:
        fields["sfw_last_login"] = last_login

    if fields:
        fields["sfw_state_synced_at"] = datetime.utcnow()
    return fields


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

    # Per-email state carried over from SFW. Profile and login live only in the
    # SFW database, so without this the funnel's "Profile complete" and
    # "Logged in / active" stages — and the registrations-by-country table —
    # read against Torpedo-local fields nothing ever writes, and are pinned at
    # zero / "Unknown" no matter how the panel actually performs.
    by_email = {}
    for r in registrants:
        email = (r.get("email") or "").strip().lower()
        if email:
            by_email[email] = r

    if not emails:
        logger.info("[panel-sync] no registrants returned from SFW panel")
        return {
            "fetched": len(registrants),
            "unique_emails": 0,
            "newly_marked": 0,
            "log_confirmed": 0,
            "state_updated": 0,
            "since": since,
        }

    now = datetime.utcnow()
    newly_marked = 0
    log_confirmed = 0
    state_updated = 0

    # SFW state is per-person, so it goes out as one bulk write rather than the
    # batched update_many the opt-in flag uses.
    state_ops = []
    for email, r in by_email.items():
        state = _sfw_state_fields(r)
        if state:
            state_ops.append(UpdateOne({"email": email}, {"$set": state}))

    for start in range(0, len(state_ops), _MARK_BATCH_SIZE):
        chunk = state_ops[start:start + _MARK_BATCH_SIZE]
        try:
            res = panelists_collection.bulk_write(chunk, ordered=False)
            state_updated += res.modified_count
        except BulkWriteError as exc:
            # A partial failure still applies the rest; losing a few profile
            # mirrors is not worth failing the opt-in sync over.
            state_updated += exc.details.get("nModified", 0)
            logger.warning(f"[panel-sync] state bulk_write partial failure: {exc.details.get('writeErrors', [])[:3]}")

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
        "state_updated": state_updated,
        "since": since,
    }
    logger.info(
        f"[panel-sync] fetched={summary['fetched']} unique={summary['unique_emails']} "
        f"newly_marked={summary['newly_marked']} log_confirmed={summary['log_confirmed']} "
        f"state_updated={summary['state_updated']}"
    )
    return summary
