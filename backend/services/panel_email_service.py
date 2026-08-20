"""
Panel Email Service — send invitation emails via Amazon SES.

Uses boto3 SES client with credentials from environment variables.
Reuses the same AWS credentials as the outreach engine (.env.outreach.example).
"""

import os
import time
import uuid
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError
from pymongo import MongoClient

try:
    # Raised by the Celery worker ~5 min before the hard time limit. Catching
    # it lets a long bulk send stop cleanly with partial progress instead of
    # being hard-killed mid-loop (which left the daily send perpetually
    # incomplete and triggered a retry storm).
    from celery.exceptions import SoftTimeLimitExceeded
except Exception:  # pragma: no cover - celery always present in worker
    class SoftTimeLimitExceeded(Exception):
        pass

from services.panel_bounce_handler import (
    is_suppressed,
    has_been_invited,
    has_been_invited_today,
    is_double_opted_in,
    log_invitation,
    suppression_collection,
    invitation_log_collection,
)

logger = logging.getLogger(__name__)

# ============== CONFIGURATION ==============

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
_client = MongoClient(MONGO_URI)
_db = _client["campaign_platform"]
panelists_collection = _db["panelists"]

AWS_SES_REGION = os.getenv("AWS_SES_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
SES_FROM_EMAIL = os.getenv("PANEL_SES_FROM_EMAIL", "panel@surveyfieldwork.com")
SES_FROM_NAME = os.getenv("PANEL_SES_FROM_NAME", "SurveyFieldwork Panel")
PANEL_SIGNUP_URL = os.getenv("PANEL_SIGNUP_URL", "https://panel.surveyfieldwork.com/signup")
PANEL_INVITE_JOIN_URL = os.getenv("PANEL_INVITE_JOIN_URL", "https://torpedo.cogentixresearch.com/api/panel/invite/join")
PANEL_LOGO_URL = os.getenv(
  "PANEL_LOGO_URL",
  "https://surveyfieldwork.com/wp-content/uploads/2021/07/Vatsalya-Sign-1-1.png",
)
PANEL_TEMPLATE_VERSION = os.getenv("PANEL_TEMPLATE_VERSION", "panel-invite-v3")
PANEL_SEND_TIMEZONE = os.getenv("PANEL_SEND_TIMEZONE", "Asia/Kolkata")
# Minimum whole days between two "join the panel" invites to the SAME address.
# The cron still runs daily (so the day's SES budget is always spent on whoever
# IS due), but an individual lead is only re-invited every Nth day. 3 = mailed
# Monday, next eligible Thursday — a two-full-day gap. Previously this was a
# same-day dedup only, which meant a lead near the front of the rotation could
# be mailed on consecutive days.
PANEL_INVITE_MIN_GAP_DAYS = int(os.getenv("PANEL_INVITE_MIN_GAP_DAYS", "3"))

# Lifetime ceiling on register-invites per panelist. The gap above spaces sends
# out but never stops them, so a lead who never engages was mailed every few
# days indefinitely: 2.87M sends to 186K people, and 108,148 of them received
# 14 invites each for a combined 3 clicks.
#
# Measured against every clicker on record, 55% clicked by invite 3 and 66% by
# invite 8; invites 9-14 cost roughly 6,200 emails per additional clicker
# against 1,500 for the first three. The tail is not empty, so the value is a
# commercial trade-off rather than a constant — hence an env var.
#
# UNSET or a value < 1 means no lifetime cap (previous behaviour). Note this is
# deliberately NOT the cap=0 convention used for the daily batch size, where 0
# is the kill switch: here 0 would silently stop the entire invite programme,
# which is exactly the kind of surprise that convention exists to prevent.
_max_invites_raw = os.getenv("PANEL_MAX_INVITES_PER_PANELIST", "").strip()
PANEL_MAX_INVITES_PER_PANELIST = int(_max_invites_raw) if _max_invites_raw.isdigit() else 0
# Manual safety ceiling only. ses_budget_for_bulk() reads the real quota from
# AWS each run and takes whichever is lower, so this exists to stop a runaway
# blast, not to size the daily batch. Held above the live Max24HourSend
# (119,300 as of 2026-08-02) so the AWS quota is the binding limit — the
# previous 65,000 was pinned to a long-superseded 69,000/day quota and was
# silently discarding ~33K/day of available send.
PANEL_DAILY_SEND_CAP = int(os.getenv("PANEL_DAILY_SEND_CAP", "140000"))
# Daily-quota headroom kept free for transactional mail — double opt-in
# verification, password reset and survey-available notices, sent both by this
# backend (services/panel_transactional_email.py) and by the SFW panel app,
# which shares this SES account. Everything bulk (cold outreach / panel
# invitations) is bounded to whatever's left of Max24HourSend after this.
#
# Raised from 3,000 after users reported verification and password-reset mail
# not arriving: 3,000 was under 3% of a ~119K/day quota, so a bulk run that
# started before the transactional traffic did could leave SES throttling the
# mail people are actively waiting on. This is cheap insurance — the bulk send
# gives up 7K of a 119K budget, transactional mail gives up nothing.
PANEL_SES_RESERVE = int(os.getenv("PANEL_SES_RESERVE", "10000"))

# Rate limiting: confirmed max send rate for this account is 14/sec (SES
# console -> Account dashboard). The old default of 1/sec (SES sandbox rate)
# combined with the Celery task's 55-minute soft time limit (see
# celery_app.py) capped every daily run at ~3,300 sends regardless of the
# account's real ~65-69K/day quota — most of the day's budget was never
# touched.
# MaxSendRate is 18/sec as of 2026-08-02; hold just under it so a burst can't
# trip SES throttling. At 17/sec a full ~119K day needs ~2h of send time, so
# the run has to survive that long — see _collect_eligible for why it didn't.
SES_SEND_RATE = float(os.getenv("PANEL_SES_SEND_RATE", "17"))  # emails per second

# Sends were still ~2.2/sec even after caching the SES client (see
# _get_ses_client below), because a single-threaded loop is bound by each
# send's real network round trip (SES API call + Mongo log write), not by
# the SES_SEND_RATE sleep. Fan sends out across a small thread pool so the
# account can actually be driven close to its confirmed 14/sec ceiling.
SES_CONCURRENCY = int(os.getenv("PANEL_SES_CONCURRENCY", "8"))


_ses_client = None
_ses_client_lock = threading.Lock()


def _get_ses_client():
    """Return a process-wide cached boto3 SES client.

    Building a boto3 client (botocore session/service-model load + a fresh
    HTTPS connection) costs tens to hundreds of ms. The bulk-send loop used
    to call this once PER EMAIL, which dwarfed the 1/SES_SEND_RATE sleep and
    silently throttled real throughput to ~1-2/sec regardless of the rate
    setting — a 65K/day run couldn't finish inside the task's time limit.
    Reusing one client (boto3 clients are thread-safe for concurrent calls)
    keeps every send to just the actual SES API round trip.
    """
    global _ses_client
    if _ses_client is None:
        with _ses_client_lock:
            if _ses_client is None:
                kwargs = {"region_name": AWS_SES_REGION}
                if AWS_ACCESS_KEY_ID:
                    kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
                    kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY
                _ses_client = boto3.client("ses", **kwargs)
    return _ses_client


class _RateGate:
    """Thread-safe leaky-bucket limiter shared across a pool of concurrent
    senders. Admits callers at up to `rate` calls/sec in AGGREGATE (not per
    thread) by handing out reserved time slots under a lock, then sleeping
    outside the lock so the actual SES calls overlap across threads."""

    def __init__(self, rate: float):
        self._interval = 1.0 / rate if rate > 0 else 0.0
        self._lock = threading.Lock()
        self._next_time = time.monotonic()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_time)
            self._next_time = start + self._interval
        delay = start - now
        if delay > 0:
            time.sleep(delay)


def _local_day_start_utc(days_back: int = 0) -> datetime:
    """Midnight of (today - days_back) in the panel's send timezone, as naive UTC.

    Everything in panel_invitation_log / panelists is stored as naive UTC, so
    the comparison values have to be naive UTC too.
    """
    from datetime import timezone as _tz, timedelta as _td
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(PANEL_SEND_TIMEZONE)
    except Exception:
        tz = ZoneInfo("UTC")
    now_local = datetime.now(tz)
    day_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_local -= _td(days=days_back)
    return day_start_local.astimezone(_tz.utc).replace(tzinfo=None)


def invite_gap_cutoff() -> datetime:
    """Anyone invited at or after this instant is still inside their gap.

    With PANEL_INVITE_MIN_GAP_DAYS=3 the cutoff is the start of the day two
    days ago, so a lead mailed Monday is skipped Tuesday and Wednesday and
    becomes eligible again on Thursday.
    """
    return _local_day_start_utc(max(0, PANEL_INVITE_MIN_GAP_DAYS - 1))


def _apply_gap_prefilter(query: Dict[str, Any], cutoff: datetime) -> Dict[str, Any]:
    """Exclude leads whose last invite is newer than `cutoff` at the query level."""
    return {
        "$and": [
            query,
            {"$or": [
                {"last_invited_at": {"$exists": False}},
                {"last_invited_at": None},
                {"last_invited_at": {"$lt": cutoff}},
            ]},
        ]
    }


def _collect_eligible(
    query: Dict[str, Any],
    projection: Dict[str, Any],
    sort_field: str,
    limit: int,
    filter_chunk,
    chunk_size: int = 2000,
) -> Tuple[list, int, bool]:
    """Stream panelists in `sort_field` order and collect up to `limit`
    eligible docs, stopping as soon as the batch is full.

    Both bulk senders used to do `list(panelists_collection.find(...))` over
    the whole table (~190K docs) and build several parallel dicts/sets on top
    of it. That allocation alone pushed the backend past its 1000M cgroup cap
    and got it OOM-killed mid-send, so a run could never finish. Peak memory
    here is bounded by one chunk plus the dedupe set and the result list,
    none of which scale with the untouched tail of the table.

    `filter_chunk(pairs) -> list[doc]` receives a list of (email, doc) for one
    chunk and returns the eligible subset; it owns the per-chunk suppression
    and already-invited lookups so those queries stay scoped to the chunk
    rather than to every email in the collection.

    Returns (eligible, examined, scan_complete). `scan_complete` is False when
    the scan stopped early on `limit`, meaning more eligible rows remain
    beyond the ones returned.
    """
    if limit <= 0:
        return [], 0, True

    cursor = (
        panelists_collection.find(query, projection)
        .sort([(sort_field, 1)])
        .batch_size(chunk_size)
    )

    seen: set = set()
    eligible: list = []
    examined = 0
    scan_complete = True
    pending: list = []

    def _drain() -> bool:
        """Filter one chunk into `eligible`. Returns True when full."""
        nonlocal pending
        if pending:
            eligible.extend(filter_chunk(pending))
            pending = []
        return len(eligible) >= limit

    try:
        for doc in cursor:
            email = (doc.get("email") or "").lower().strip()
            if not email or email in seen:
                continue
            seen.add(email)
            examined += 1
            pending.append((email, doc))
            if len(pending) >= chunk_size and _drain():
                scan_complete = False
                break
        else:
            _drain()
    finally:
        cursor.close()

    if len(eligible) > limit:
        eligible = eligible[:limit]

    return eligible, examined, scan_complete


def _send_batch_concurrently(to_send: list, send_one) -> Tuple[int, int, bool]:
    """Run `send_one(panelist) -> bool` over `to_send` with up to
    SES_CONCURRENCY workers, paced in aggregate to SES_SEND_RATE. `send_one`
    owns its own logging/state writes; this only tallies sent/failed and
    detects a Celery soft-time-limit truncation.

    SoftTimeLimitExceeded is delivered by Celery as a signal, which Python
    only ever raises on the process's MAIN thread — so it surfaces here (in
    as_completed's wait loop), never inside a worker thread. On catching it
    we flip stop_event so in-flight/queued workers return immediately, then
    drop any not-yet-started work rather than waiting for it to run.

    Returns (sent, failed, truncated).
    """
    rate_gate = _RateGate(SES_SEND_RATE)
    stop_event = threading.Event()
    counts_lock = threading.Lock()
    sent = failed = 0

    def _worker(panelist):
        nonlocal sent, failed
        if stop_event.is_set():
            return
        rate_gate.wait()
        if stop_event.is_set():
            return
        try:
            ok = bool(send_one(panelist))
        except Exception as exc:
            logger.error(f"[panel] send_one failed for a queued panelist: {exc}")
            ok = False
        with counts_lock:
            if ok:
                sent += 1
            else:
                failed += 1

    truncated = False
    pool = ThreadPoolExecutor(max_workers=SES_CONCURRENCY)
    futures = [pool.submit(_worker, p) for p in to_send]
    try:
        for f in as_completed(futures):
            f.result()
        pool.shutdown(wait=True)
    except SoftTimeLimitExceeded:
        truncated = True
        stop_event.set()
        pool.shutdown(wait=True, cancel_futures=True)
    return sent, failed, truncated


def ses_budget_for_bulk() -> int:
    """How many bulk emails this run may send without starving transactional mail.

    The SFW panel app shares this SES account for signup verification and
    password-reset mail. A bulk invite run that drains the daily quota takes
    those down with it — SES then rejects them with TooManyRequestsException
    and users simply never receive a reset link. Hold PANEL_SES_RESERVE emails
    back for that traffic. Returns the remaining allowance (0 = send nothing).

    On any error, fall back to the configured cap rather than blocking the run.
    """
    try:
        quota = _get_ses_client().get_send_quota()
        max_24h = int(quota.get("Max24HourSend") or 0)
        sent_24h = int(quota.get("SentLast24Hours") or 0)
    except Exception as e:
        logger.warning(f"[panel] could not read SES quota ({e}); using configured cap")
        return PANEL_DAILY_SEND_CAP

    if max_24h <= 0:  # -1 means unlimited
        return PANEL_DAILY_SEND_CAP

    budget = max_24h - sent_24h - PANEL_SES_RESERVE
    # Logged every run so "the reset email never arrived" can be checked
    # against the actual headroom at the time instead of guessed at.
    logger.info(
        f"[panel] SES quota check: sent_24h={sent_24h}/{max_24h} "
        f"reserve={PANEL_SES_RESERVE} bulk_budget={max(0, budget)}"
    )
    if budget <= 0:
        logger.error(
            f"[panel] SES daily quota nearly exhausted ({sent_24h}/{max_24h}); "
            f"skipping bulk send to protect the {PANEL_SES_RESERVE} reserved for "
            f"verification/password-reset mail"
        )
        return 0

    return min(budget, PANEL_DAILY_SEND_CAP)


# ============== HTML INVITATION TEMPLATE ==============

def _build_join_link(invite_token: str) -> str:
  token = quote(invite_token.strip())
  return f"{PANEL_INVITE_JOIN_URL}?token={token}"


def _build_invitation_html(first_name: str = "", join_link: str = "", unsub_link: str = "") -> str:
    """Build a beautiful, responsive HTML invitation email."""
    greeting = f"Hi {first_name}," if first_name else "Hello,"
    cta_link = join_link or PANEL_SIGNUP_URL
    unsubscribe = unsub_link or f"{PANEL_SIGNUP_URL.rsplit('/', 1)[0]}/unsubscribe"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>You're Invited to SurveyFieldwork</title>
</head>
<body style="margin:0;padding:0;background:#f7fafc;font-family:'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f7fafc;padding:40px 20px;">
    <tr>
      <td align="center">
        <!-- Main Container -->
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background-color:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 12px 32px rgba(15,23,42,0.12);">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#071733 0%,#0c2d63 58%,#13498b 100%);padding:44px 40px;text-align:center;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center">
                    <img src="{PANEL_LOGO_URL}" alt="SurveyFieldwork" width="220" style="display:block;max-width:220px;width:100%;height:auto;margin:0 auto 18px;border:0;outline:none;text-decoration:none;-ms-interpolation-mode:bicubic;" />
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-top:8px;">
                    <h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:700;letter-spacing:-0.4px;">Join The SurveyFieldwork Panel</h1>
                    <p style="margin:10px 0 0;color:rgba(255,255,255,0.9);font-size:15px;font-weight:400;">Complete a quick double opt-in and start earning from verified surveys</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:40px;">
              <p style="margin:0 0 20px;color:#1f2937;font-size:16px;line-height:1.6;">
                {greeting}
              </p>
              <p style="margin:0 0 24px;color:#334155;font-size:15px;line-height:1.7;">
                You're one click away from joining our verified respondent community. Use your personal invite button below, complete double opt-in on the panel, and you'll start receiving quality invites.
              </p>

              <!-- Benefits -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:32px;">
                <tr>
                  <td style="padding:16px 20px;background-color:#eff6ff;border-radius:12px;border-left:4px solid #0ea5e9;">
                    <table role="presentation" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">&#10003;</span>
                          <strong style="color:#0b3a75;font-size:14px;">Paid Surveys</strong>
                          <span style="color:#4b5563;font-size:13px;"> — Cash out via PayPal, gift cards, or bank transfer</span>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">&#10003;</span>
                          <strong style="color:#0b3a75;font-size:14px;">Fast Participation</strong>
                          <span style="color:#4b5563;font-size:13px;"> — Most take just 5-15 minutes to complete</span>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">&#10003;</span>
                          <strong style="color:#0b3a75;font-size:14px;">Double Opt-In Protection</strong>
                          <span style="color:#4b5563;font-size:13px;"> — Only confirmed users stay active in the panel</span>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">&#10003;</span>
                          <strong style="color:#0b3a75;font-size:14px;">Your Privacy Matters</strong>
                          <span style="color:#4b5563;font-size:13px;"> — All responses are 100% anonymous</span>
                        </td>
                      </tr>
                      <tr>
                        <td>
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">&#10003;</span>
                          <strong style="color:#166534;font-size:14px;">100% Free</strong>
                          <span style="color:#4b5563;font-size:13px;"> — No fees, no catches, just rewards</span>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- CTA Button -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding:8px 0 32px;">
                    <a href="{cta_link}"
                       style="display:inline-block;padding:16px 44px;background:linear-gradient(135deg,#0ea5e9,#0284c7);color:#ffffff;text-decoration:none;font-size:16px;font-weight:700;border-radius:12px;letter-spacing:0.3px;box-shadow:0 8px 20px rgba(2,132,199,0.35);">
                      Join Panel & Confirm Email &rarr;
                    </a>
                  </td>
                </tr>
              </table>

              <p style="margin:0 0 18px;color:#64748b;font-size:12px;line-height:1.6;text-align:center;">
                This is your unique join link. It is tied to your invitation profile.
              </p>

              <!-- Social Proof -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #e5e7eb;padding-top:24px;">
                <tr>
                  <td align="center">
                    <p style="margin:0 0 8px;color:#6b7280;font-size:13px;font-weight:500;text-transform:uppercase;letter-spacing:1px;">Trusted by panelists worldwide</p>
                    <table role="presentation" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="padding:0 16px;text-align:center;">
                          <p style="margin:0;color:#0f172a;font-size:24px;font-weight:800;">50K+</p>
                          <p style="margin:2px 0 0;color:#9ca3af;font-size:11px;">Active Members</p>
                        </td>
                        <td style="padding:0 16px;text-align:center;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;">
                          <p style="margin:0;color:#0f172a;font-size:24px;font-weight:800;">Daily</p>
                          <p style="margin:2px 0 0;color:#9ca3af;font-size:11px;">Fresh Studies</p>
                        </td>
                        <td style="padding:0 16px;text-align:center;">
                          <p style="margin:0;color:#0f172a;font-size:24px;font-weight:800;">Secure</p>
                          <p style="margin:2px 0 0;color:#9ca3af;font-size:11px;">Double Opt-In</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color:#f9fafb;padding:24px 40px;border-top:1px solid #e5e7eb;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center">
                    <p style="margin:0 0 8px;color:#6b7280;font-size:12px;">
                      &copy; {datetime.utcnow().year} SurveyFieldwork. All rights reserved.
                    </p>
                    <p style="margin:0;color:#9ca3af;font-size:11px;line-height:1.5;">
                      You're receiving this because you signed up as a panelist.<br>
                      <a href="{unsubscribe}" style="color:#0284c7;text-decoration:underline;">Unsubscribe</a>
                      &nbsp;|&nbsp;
                      <a href="https://panel.surveyfieldwork.com/privacy" style="color:#0284c7;text-decoration:underline;">Privacy Policy</a>
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _build_invitation_plain(first_name: str = "", join_link: str = "", unsub_link: str = "") -> str:
    """Build plain-text version of the invitation."""
    greeting = f"Hi {first_name}," if first_name else "Hello,"
    cta_link = join_link or PANEL_SIGNUP_URL
    unsubscribe = unsub_link or f"{PANEL_SIGNUP_URL.rsplit('/', 1)[0]}/unsubscribe"
    return f"""{greeting}

You're invited to join the SurveyFieldwork Panel.

Use your unique link below and complete the panel double opt-in process.

Why join?
- Paid surveys with real rewards
- New opportunities added daily
- Double opt-in keeps access secure
- 100% free to join

Join now: {cta_link}

Note: this link is unique to your invitation.

---
SurveyFieldwork
Unsubscribe: {unsubscribe}
Privacy: https://panel.surveyfieldwork.com/privacy
"""


# ============== LOGIN INVITATION EMAIL TEMPLATES ==============

def _build_login_invitation_html(first_name: str = "", login_url: str = "", unsub_link: str = "") -> str:
    """Build a responsive HTML email inviting registered users to log in and take surveys."""
    greeting = f"Hi {first_name}," if first_name else "Hello,"
    cta_link = login_url or "https://panel.surveyfieldwork.com/login"
    unsubscribe = unsub_link or "https://panel.surveyfieldwork.com/unsubscribe"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ready to Earn? Log In to Your Panel</title>
</head>
<body style="margin:0;padding:0;background:#f7fafc;font-family:'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f7fafc;padding:40px 20px;">
    <tr>
      <td align="center">
        <!-- Main Container -->
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background-color:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 12px 32px rgba(15,23,42,0.12);">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#071733 0%,#0c2d63 58%,#13498b 100%);padding:44px 40px;text-align:center;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center">
                    <img src="{PANEL_LOGO_URL}" alt="SurveyFieldwork" width="220" style="display:block;max-width:220px;width:100%;height:auto;margin:0 auto 18px;border:0;outline:none;text-decoration:none;-ms-interpolation-mode:bicubic;" />
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-top:8px;">
                    <h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:700;letter-spacing:-0.4px;">Ready to Start Earning?</h1>
                    <p style="margin:10px 0 0;color:rgba(255,255,255,0.9);font-size:15px;font-weight:400;">New surveys are waiting for you</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:40px;">
              <p style="margin:0 0 20px;color:#1f2937;font-size:16px;line-height:1.6;">
                {greeting}
              </p>
              <p style="margin:0 0 24px;color:#334155;font-size:15px;line-height:1.7;">
                You're all set! Your panel account is active and ready to go. Log in now to explore available surveys and start earning rewards.
              </p>

              <!-- Benefits -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:32px;">
                <tr>
                  <td style="padding:16px 20px;background-color:#eff6ff;border-radius:12px;border-left:4px solid #0ea5e9;">
                    <table role="presentation" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">✓</span>
                          <strong style="color:#0b3a75;font-size:14px;">New Surveys Today</strong>
                          <span style="color:#4b5563;font-size:13px;"> — Fresh opportunities added daily</span>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">✓</span>
                          <strong style="color:#0b3a75;font-size:14px;">Earn Instantly</strong>
                          <span style="color:#4b5563;font-size:13px;"> — Get paid per completed survey</span>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">✓</span>
                          <strong style="color:#0b3a75;font-size:14px;">Quick & Easy</strong>
                          <span style="color:#4b5563;font-size:13px;"> — Most surveys take 5-15 minutes</span>
                        </td>
                      </tr>
                      <tr>
                        <td>
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">✓</span>
                          <strong style="color:#166534;font-size:14px;">Multiple Rewards</strong>
                          <span style="color:#4b5563;font-size:13px;"> — PayPal, gift cards, bank transfer</span>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- CTA Button -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding:8px 0 32px;">
                    <a href="{cta_link}"
                       style="display:inline-block;padding:16px 44px;background:linear-gradient(135deg,#0ea5e9,#0284c7);color:#ffffff;text-decoration:none;font-size:16px;font-weight:700;border-radius:12px;letter-spacing:0.3px;box-shadow:0 8px 20px rgba(2,132,199,0.35);">
                      Log In & View Surveys &rarr;
                    </a>
                  </td>
                </tr>
              </table>

              <p style="margin:0 0 18px;color:#64748b;font-size:12px;line-height:1.6;text-align:center;">
                Use your email address to log in to your account.
              </p>

              <!-- Stats -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #e5e7eb;padding-top:24px;">
                <tr>
                  <td align="center">
                    <p style="margin:0 0 8px;color:#6b7280;font-size:13px;font-weight:500;text-transform:uppercase;letter-spacing:1px;">Why you'll love the panel</p>
                    <table role="presentation" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="padding:0 16px;text-align:center;">
                          <p style="margin:0;color:#0f172a;font-size:24px;font-weight:800;">50K+</p>
                          <p style="margin:2px 0 0;color:#9ca3af;font-size:11px;">Members</p>
                        </td>
                        <td style="padding:0 16px;text-align:center;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;">
                          <p style="margin:0;color:#0f172a;font-size:24px;font-weight:800;">100+</p>
                          <p style="margin:2px 0 0;color:#9ca3af;font-size:11px;">Monthly</p>
                        </td>
                        <td style="padding:0 16px;text-align:center;">
                          <p style="margin:0;color:#0f172a;font-size:24px;font-weight:800;">$$$</p>
                          <p style="margin:2px 0 0;color:#9ca3af;font-size:11px;">Cash Rewards</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color:#f9fafb;padding:24px 40px;border-top:1px solid #e5e7eb;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center">
                    <p style="margin:0 0 8px;color:#6b7280;font-size:12px;">
                      &copy; {datetime.utcnow().year} SurveyFieldwork. All rights reserved.
                    </p>
                    <p style="margin:0;color:#9ca3af;font-size:11px;line-height:1.5;">
                      This is a courtesy reminder — you're receiving this because you're an active panel member.<br>
                      <a href="{unsubscribe}" style="color:#0284c7;text-decoration:underline;">Unsubscribe</a>
                      &nbsp;|&nbsp;
                      <a href="https://panel.surveyfieldwork.com/privacy" style="color:#0284c7;text-decoration:underline;">Privacy Policy</a>
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _build_login_invitation_plain(first_name: str = "", login_url: str = "", unsub_link: str = "") -> str:
    """Build plain-text version of login invitation."""
    greeting = f"Hi {first_name}," if first_name else "Hello,"
    cta_link = login_url or "https://panel.surveyfieldwork.com/login"
    unsubscribe = unsub_link or "https://panel.surveyfieldwork.com/unsubscribe"
    return f"""{greeting}

You're all set! Your panel account is active and ready to go.

New surveys are available for you right now. Log in and start earning.

Why take surveys with us?
- Paid for every completed survey
- New opportunities added daily
- Quick surveys (5-15 minutes each)
- Multiple payment options

Log in now: {cta_link}

---
SurveyFieldwork
Unsubscribe: {unsubscribe}
Privacy: https://panel.surveyfieldwork.com/privacy
"""


# ============== SEND FUNCTIONS ==============

def _apply_unsubscribe(msg, to_email: str) -> str:
    """Attach one-click unsubscribe headers and return the footer opt-out link.

    Gmail and Yahoo have required List-Unsubscribe / List-Unsubscribe-Post of
    bulk senders since Feb 2024. This mail carried neither, which at ~161K
    messages a day is on its own enough to get the whole programme filtered.
    Returns the per-recipient link so the footer matches the header.
    """
    try:
        try:
            from services.panel_unsubscribe import list_unsubscribe_headers, unsubscribe_url
        except ImportError:
            from backend.services.panel_unsubscribe import list_unsubscribe_headers, unsubscribe_url

        for header, value in list_unsubscribe_headers(to_email).items():
            msg[header] = value
        return unsubscribe_url(to_email)
    except Exception as e:
        # Never let opt-out plumbing block a send; fall back to the generic page.
        logger.warning(f"[panel] could not build unsubscribe link for {to_email}: {e}")
        return "https://panel.surveyfieldwork.com/unsubscribe"

def send_invitation_email(
    to_email: str,
    first_name: str = "",
    invite_token: str = "",
) -> Tuple[bool, Dict[str, Any]]:
    """
    Send a single invitation email via SES.
    Returns (success, details_dict).
    """
    try:
        client = _get_ses_client()

        msg = MIMEMultipart("alternative")
        msg["To"] = to_email
        msg["From"] = f"{SES_FROM_NAME} <{SES_FROM_EMAIL}>"
        msg["Subject"] = "Complete your panel signup and start earning rewards"
        msg["Message-ID"] = f"<panel-{uuid.uuid4()}@surveyfieldwork.com>"
        unsub_link = _apply_unsubscribe(msg, to_email)

        join_link = _build_join_link(invite_token) if invite_token else PANEL_SIGNUP_URL

        msg.attach(MIMEText(_build_invitation_plain(first_name, join_link, unsub_link), "plain", "utf-8"))
        msg.attach(MIMEText(_build_invitation_html(first_name, join_link, unsub_link), "html", "utf-8"))

        response = client.send_raw_email(
            Source=f"{SES_FROM_NAME} <{SES_FROM_EMAIL}>",
            Destinations=[to_email],
            RawMessage={"Data": msg.as_bytes()},
        )

        ses_message_id = response.get("MessageId", "")
        logger.info(f"Panel invitation sent → {to_email} | SES MessageId={ses_message_id}")
        return True, {"ses_message_id": ses_message_id}

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"SES error sending to {to_email}: {error_code} — {error_msg}")
        return False, {"error": error_code, "message": error_msg}
    except Exception as e:
        logger.error(f"Unexpected error sending to {to_email}: {e}")
        return False, {"error": str(e)}


def send_bulk_invitations(
    country: Optional[str] = None,
    force_resend: bool = False,
    daily_mode: bool = False,
    daily_cap: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Send invitation emails to all eligible panelists.

    Pipeline:
    1. Query panelists matching filter
    2. Deduplicate emails
    3. Check suppression list — skip suppressed
    4. Check invitation log — skip already invited (unless force_resend)
    5. Send via SES with rate limiting
    6. Log each send

    Returns summary dict with sent, skipped, failed counts.
    """
    batch_id = f"batch-{uuid.uuid4().hex[:12]}"

    # Build query
    query = {"status": "active"}
    if country:
        query["country"] = {"$regex": f"^{country}$", "$options": "i"}

    # The SES budget bounds every bulk run, manual or cron — a hand-triggered
    # blast drains the shared daily quota just as effectively as the cron did.
    # Computed up front so the eligibility scan below knows when to stop.
    budget = ses_budget_for_bulk()
    cap_value = min(daily_cap, budget) if daily_cap is not None else budget

    # Everyone invited at or after this instant is still serving their
    # PANEL_INVITE_MIN_GAP_DAYS cooldown and must be skipped this run.
    if daily_mode:
        gap_cutoff_utc = invite_gap_cutoff()
        # Prefilter in the query itself so leads still in their cooldown are
        # never even fetched. Without this the scan burns its whole chunk
        # budget on recently-mailed leads (they sort first once last_invited_at
        # is set) and the batch fills far short of the SES budget.
        query = _apply_gap_prefilter(query, gap_cutoff_utc)

    def _filter_chunk(pairs):
        """Suppression / already-invited lookups scoped to one chunk."""
        emails = [e for e, _ in pairs]

        suppressed_set = {
            doc["email"].lower().strip()
            for doc in suppression_collection.find({"email": {"$in": emails}}, {"email": 1})
        }

        # Lifetime cap. Counted from the send log rather than a counter on the
        # panelist, so it stays correct for the ~186K people already mailed
        # before this existed — a fresh counter would reset everyone to zero
        # and hand the worst offenders another full allowance.
        exhausted_set = set()
        if PANEL_MAX_INVITES_PER_PANELIST > 0:
            exhausted_set = {
                row["_id"]
                for row in invitation_log_collection.aggregate([
                    {"$match": {"email": {"$in": emails},
                                "sent_at": {"$exists": True, "$ne": None}}},
                    {"$group": {"_id": "$email", "n": {"$sum": 1}}},
                    {"$match": {"n": {"$gte": PANEL_MAX_INVITES_PER_PANELIST}}},
                ])
            }

        if daily_mode:
            # Backstop for the query-level prefilter above: records predating
            # last_invited_at only prove their cooldown through the send log.
            invited_set = {
                doc["email"].lower().strip()
                for doc in invitation_log_collection.find(
                    {"email": {"$in": emails}, "status": "sent",
                     "sent_at": {"$gte": gap_cutoff_utc}},
                    {"email": 1}
                )
            }
        elif not force_resend:
            invited_set = {
                doc["email"].lower().strip()
                for doc in invitation_log_collection.find(
                    {"email": {"$in": emails}, "status": "sent"}, {"email": 1}
                )
            }
        else:
            invited_set = set()

        out = []
        for email, panelist in pairs:
            doc_status = str(panelist.get("status") or "").strip().lower()
            if email in exhausted_set:
                continue
            # Skip double opted-in
            if panelist.get("double_opt_in_completed"):
                continue
            if panelist.get("email_verified") and doc_status in {"active", "confirmed", "double_opted_in"}:
                continue
            if email in suppressed_set:
                continue
            if email in invited_set:
                continue
            out.append(panelist)
        return out

    # Oldest-invited-or-never-invited first. Without this sort, Mongo returns
    # natural order every run; combined with each daily batch being truncated
    # partway through, the same leads near the front got re-invited every day
    # while everyone past the truncation point was never reached. Missing
    # last_invited_at sorts first, so untouched leads win.
    to_send, examined, scan_complete = _collect_eligible(
        query,
        {"email": 1, "first_name": 1, "_id": 1, "double_opt_in_completed": 1,
         "email_verified": 1, "status": 1, "last_invited_at": 1},
        "last_invited_at",
        cap_value,
        _filter_chunk,
    )
    skipped = examined - len(to_send)
    # Candidates the scan never reached because it filled up on cap_value.
    # An upper bound on what's left rather than an exact eligible count —
    # establishing the exact figure would mean the full-table scan this
    # streaming path exists to avoid. 0 means nothing was left behind.
    capped = 0 if scan_complete else max(0, panelists_collection.count_documents(query) - examined)

    def _send_one(panelist) -> bool:
        email = (panelist.get("email") or "").lower().strip()
        first_name = panelist.get("first_name", "")
        invite_token = uuid.uuid4().hex
        success, details = send_invitation_email(email, first_name, invite_token=invite_token)
        log_invitation(
            email=email,
            panelist_id=str(panelist["_id"]),
            batch_id=batch_id,
            ses_message_id=details.get("ses_message_id", "") if success else "",
            status="sent" if success else "failed",
            invite_token=invite_token,
            template_version=PANEL_TEMPLATE_VERSION,
        )
        # Push this lead to the back of tomorrow's queue regardless of outcome,
        # so a bad address can't get permanently stuck at the front and block
        # everyone behind it.
        panelists_collection.update_one(
            {"_id": panelist["_id"]},
            {"$set": {"last_invited_at": datetime.utcnow()}},
        )
        return success

    sent, failed, truncated = _send_batch_concurrently(to_send, _send_one)
    if truncated:
        logger.warning(
            f"[panel] invite batch {batch_id} hit the worker time limit "
            f"after {sent} sends — stopping cleanly; the rest go out on the "
            f"next daily run."
        )

    logger.info(f"Bulk invitation complete batch={batch_id}: sent={sent} skipped={skipped} failed={failed} truncated={truncated}")
    return {
        "batch_id": batch_id,
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "capped": capped,
        "truncated": truncated,
        "daily_mode": daily_mode,
        "daily_cap": cap_value if daily_mode else None,
        "timezone": PANEL_SEND_TIMEZONE if daily_mode else None,
        "total_processed": sent + skipped + failed,
    }


def send_login_invitation_email(
    to_email: str,
    first_name: str = "",
) -> Tuple[bool, Dict[str, Any]]:
    """
    Send a login reminder email to registered panelists via SES.
    Returns (success, details_dict).
    """
    try:
        client = _get_ses_client()

        msg = MIMEMultipart("alternative")
        msg["To"] = to_email
        msg["From"] = f"{SES_FROM_NAME} <{SES_FROM_EMAIL}>"
        msg["Subject"] = "Ready to earn? New surveys waiting for you"
        msg["Message-ID"] = f"<panel-login-{uuid.uuid4()}@surveyfieldwork.com>"
        unsub_link = _apply_unsubscribe(msg, to_email)

        login_url = "https://panel.surveyfieldwork.com/login"

        msg.attach(MIMEText(_build_login_invitation_plain(first_name, login_url, unsub_link), "plain", "utf-8"))
        msg.attach(MIMEText(_build_login_invitation_html(first_name, login_url, unsub_link), "html", "utf-8"))

        response = client.send_raw_email(
            Source=f"{SES_FROM_NAME} <{SES_FROM_EMAIL}>",
            Destinations=[to_email],
            RawMessage={"Data": msg.as_bytes()},
        )

        ses_message_id = response.get("MessageId", "")
        logger.info(f"Panel login invitation sent → {to_email} | SES MessageId={ses_message_id}")
        return True, {"ses_message_id": ses_message_id}

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error(f"SES error sending login invite to {to_email}: {error_code} — {error_msg}")
        return False, {"error": error_code, "message": error_msg}
    except Exception as e:
        logger.error(f"Unexpected error sending login invite to {to_email}: {e}")
        return False, {"error": str(e)}


def send_bulk_login_invitations(
    country: Optional[str] = None,
    daily_cap: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Send login reminder emails to all registered (double_opt_in_completed=true) panelists.

    Pipeline:
    1. Query panelists with double_opt_in_completed=true
    2. Check if already sent login email today (from invitation_log with type='login')
    3. Send via SES with rate limiting
    4. Log each send

    Returns summary dict with sent, skipped, failed counts.
    """
    batch_id = f"login-batch-{uuid.uuid4().hex[:12]}"

    # Build query for registered users.
    # The status exclusion is not optional: unlike send_bulk_invitations (which
    # filters on status "active") this sender had no status condition at all,
    # so an address that had unsubscribed or hard-bounced stayed in scope
    # forever as long as it was double-opted-in.
    query = {
        "double_opt_in_completed": True,
        "status": {"$nin": ["dnd", "unsubscribed", "bounced", "complained"]},
    }
    if country:
        query["country"] = {"$regex": f"^{country}$", "$options": "i"}

    budget = ses_budget_for_bulk()
    cap_value = min(daily_cap, budget) if daily_cap is not None else budget

    # Window for "already sent a login reminder today", in the panel's local
    # send timezone.
    from datetime import timezone as _tz
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(PANEL_SEND_TIMEZONE)
    except Exception:
        tz = ZoneInfo("UTC")
    from datetime import datetime as _dt, timedelta as _td
    now_local = _dt.now(tz)
    day_start_utc = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(_tz.utc).replace(tzinfo=None)
    next_day_utc = day_start_utc + _td(days=1)

    def _filter_chunk(pairs):
        emails = [e for e, _ in pairs]

        # This sender never consulted the suppression list. Bounced,
        # complained and unsubscribed addresses were mailed a login reminder
        # every single day for as long as they stayed double-opted-in.
        suppressed_set = {
            doc["email"].lower().strip()
            for doc in suppression_collection.find({"email": {"$in": emails}}, {"email": 1})
        }

        already_sent_today = {
            doc["email"].lower().strip()
            for doc in invitation_log_collection.find(
                {"email": {"$in": emails}, "status": "sent", "type": "login",
                 "sent_at": {"$gte": day_start_utc, "$lt": next_day_utc}},
                {"email": 1}
            )
        }
        return [
            p for e, p in pairs
            if e not in already_sent_today and e not in suppressed_set
        ]

    # Oldest-invited-or-never-invited first — same rotation fix as
    # send_bulk_invitations, tracked in its own field so the two invite types
    # don't clobber each other's ordering. Streamed for the same reason: see
    # _collect_eligible.
    to_send, examined, scan_complete = _collect_eligible(
        query,
        {"email": 1, "first_name": 1, "_id": 1, "last_login_invite_sent_at": 1},
        "last_login_invite_sent_at",
        cap_value,
        _filter_chunk,
    )
    skipped = examined - len(to_send)
    capped = 0 if scan_complete else max(0, panelists_collection.count_documents(query) - examined)

    def _send_one(panelist) -> bool:
        email = (panelist.get("email") or "").lower().strip()
        first_name = panelist.get("first_name", "")
        success, details = send_login_invitation_email(email, first_name)
        log_invitation(
            email=email,
            panelist_id=str(panelist["_id"]),
            batch_id=batch_id,
            ses_message_id=details.get("ses_message_id", "") if success else "",
            status="sent" if success else "failed",
            template_version="panel-login-v1",
            type="login",
        )
        panelists_collection.update_one(
            {"_id": panelist["_id"]},
            {"$set": {"last_login_invite_sent_at": datetime.utcnow()}},
        )
        return success

    sent, failed, truncated = _send_batch_concurrently(to_send, _send_one)
    if truncated:
        logger.warning(
            f"[panel] login batch {batch_id} hit the worker time limit "
            f"after {sent} sends — stopping cleanly; the rest go out on the "
            f"next daily run."
        )

    logger.info(f"Bulk login invitation complete batch={batch_id}: sent={sent} skipped={skipped} failed={failed} truncated={truncated}")
    return {
        "batch_id": batch_id,
        "truncated": truncated,
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "capped": capped,
        "daily_cap": cap_value,
        "timezone": PANEL_SEND_TIMEZONE,
        "total_processed": sent + skipped + failed,
    }


def get_eligible_count(
    country: Optional[str] = None,
    force_resend: bool = False,
    daily_mode: bool = False,
) -> int:
    """
    Count panelists eligible for an invitation.

    Streamed in chunks rather than loading every active panelist at once: this
    is reachable from the dashboard, and at ~190K panelists the old version
    both held the whole table in memory and issued an `$in` over every address
    on the collection, which was enough on its own to push the backend past
    its memory cap. Same eligibility rules as send_bulk_invitations.
    """
    query = {"status": "active"}
    if country:
        query["country"] = {"$regex": f"^{country}$", "$options": "i"}

    if daily_mode:
        gap_cutoff_utc = invite_gap_cutoff()
        query = _apply_gap_prefilter(query, gap_cutoff_utc)

    def _filter_chunk(pairs):
        emails = [e for e, _ in pairs]

        suppressed = {
            doc["email"].lower().strip()
            for doc in suppression_collection.find({"email": {"$in": emails}}, {"email": 1})
        }

        if daily_mode:
            # Mirrors send_bulk_invitations: still inside the invite cooldown.
            invited = {
                doc["email"].lower().strip()
                for doc in invitation_log_collection.find(
                    {"email": {"$in": emails}, "status": "sent",
                     "sent_at": {"$gte": gap_cutoff_utc}},
                    {"email": 1}
                )
            }
        elif not force_resend:
            invited = {
                doc["email"].lower().strip()
                for doc in invitation_log_collection.find(
                    {"email": {"$in": emails}, "status": "sent"}, {"email": 1}
                )
            }
        else:
            invited = set()

        out = []
        for email, doc in pairs:
            # Skip double opted-in (mirrors is_double_opted_in logic)
            if doc.get("double_opt_in_completed"):
                continue
            status = str(doc.get("status") or "").strip().lower()
            if doc.get("email_verified") and status in {"active", "confirmed", "double_opted_in"}:
                continue
            if email in suppressed:
                continue
            if email in invited:
                continue
            out.append(doc)
        return out

    count = 0
    seen: set = set()
    pending: list = []
    cursor = panelists_collection.find(
        query, {"email": 1, "double_opt_in_completed": 1, "email_verified": 1, "status": 1}
    ).batch_size(2000)

    try:
        for doc in cursor:
            email = (doc.get("email") or "").lower().strip()
            if not email or email in seen:
                continue
            seen.add(email)
            pending.append((email, doc))
            if len(pending) >= 2000:
                count += len(_filter_chunk(pending))
                pending = []
        if pending:
            count += len(_filter_chunk(pending))
    finally:
        cursor.close()

    return count
