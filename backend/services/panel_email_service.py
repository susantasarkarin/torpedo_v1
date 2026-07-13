"""
Panel Email Service — send invitation emails via Amazon SES.

Uses boto3 SES client with credentials from environment variables.
Reuses the same AWS credentials as the outreach engine (.env.outreach.example).
"""

import os
import time
import uuid
import logging
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
PANEL_DAILY_SEND_CAP = int(os.getenv("PANEL_DAILY_SEND_CAP", "50000"))  # 50K daily SES limit
# Daily-quota headroom kept free for the SFW panel's transactional mail
# (signup verification, password reset), which shares this SES account.
PANEL_SES_RESERVE = int(os.getenv("PANEL_SES_RESERVE", "2000"))

# Rate limiting: SES sandbox = 1/sec, production = 14/sec
SES_SEND_RATE = float(os.getenv("PANEL_SES_SEND_RATE", "1"))  # emails per second


def _get_ses_client():
    """Create a boto3 SES client."""
    kwargs = {"region_name": AWS_SES_REGION}
    if AWS_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY
    return boto3.client("ses", **kwargs)


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


def _build_invitation_html(first_name: str = "", join_link: str = "") -> str:
    """Build a beautiful, responsive HTML invitation email."""
    greeting = f"Hi {first_name}," if first_name else "Hello,"
    cta_link = join_link or PANEL_SIGNUP_URL

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
                      <a href="https://panel.surveyfieldwork.com/unsubscribe" style="color:#0284c7;text-decoration:underline;">Unsubscribe</a>
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


def _build_invitation_plain(first_name: str = "", join_link: str = "") -> str:
    """Build plain-text version of the invitation."""
    greeting = f"Hi {first_name}," if first_name else "Hello,"
    cta_link = join_link or PANEL_SIGNUP_URL
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
Unsubscribe: https://panel.surveyfieldwork.com/unsubscribe
Privacy: https://panel.surveyfieldwork.com/privacy
"""


# ============== LOGIN INVITATION EMAIL TEMPLATES ==============

def _build_login_invitation_html(first_name: str = "", login_url: str = "") -> str:
    """Build a responsive HTML email inviting registered users to log in and take surveys."""
    greeting = f"Hi {first_name}," if first_name else "Hello,"
    cta_link = login_url or "https://panel.surveyfieldwork.com/login"

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
                      <a href="https://panel.surveyfieldwork.com/unsubscribe" style="color:#0284c7;text-decoration:underline;">Unsubscribe</a>
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


def _build_login_invitation_plain(first_name: str = "", login_url: str = "") -> str:
    """Build plain-text version of login invitation."""
    greeting = f"Hi {first_name}," if first_name else "Hello,"
    cta_link = login_url or "https://panel.surveyfieldwork.com/login"
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
Unsubscribe: https://panel.surveyfieldwork.com/unsubscribe
Privacy: https://panel.surveyfieldwork.com/privacy
"""


# ============== SEND FUNCTIONS ==============

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

        join_link = _build_join_link(invite_token) if invite_token else PANEL_SIGNUP_URL

        msg.attach(MIMEText(_build_invitation_plain(first_name, join_link), "plain", "utf-8"))
        msg.attach(MIMEText(_build_invitation_html(first_name, join_link), "html", "utf-8"))

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

    # Bulk pre-fetch all panelists, oldest-invited-or-never-invited first. Without
    # this sort, Mongo returns natural order every run; combined with the SES rate
    # limit truncating each daily batch partway through, the same leads near the
    # front got re-invited every day while everyone past the truncation point was
    # never reached. Missing last_invited_at sorts first, so untouched leads win.
    all_panelists = list(panelists_collection.find(
        query,
        {"email": 1, "first_name": 1, "_id": 1, "double_opt_in_completed": 1,
         "email_verified": 1, "last_invited_at": 1},
    ).sort([("last_invited_at", 1)]))

    # Deduplicate and build email→doc map
    email_map: Dict[str, Any] = {}
    for p in all_panelists:
        email = (p.get("email") or "").lower().strip()
        if email and email not in email_map:
            email_map[email] = p

    email_list = list(email_map.keys())

    # Bulk fetch suppressed emails
    suppressed_set: set = {
        doc["email"].lower().strip()
        for doc in suppression_collection.find({"email": {"$in": email_list}}, {"email": 1})
    }

    # Bulk fetch already-invited / invited-today emails
    if daily_mode:
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
        invited_set: set = {
            doc["email"].lower().strip()
            for doc in invitation_log_collection.find(
                {"email": {"$in": email_list}, "status": "sent",
                 "sent_at": {"$gte": day_start_utc, "$lt": next_day_utc}},
                {"email": 1}
            )
        }
    elif not force_resend:
        invited_set = {
            doc["email"].lower().strip()
            for doc in invitation_log_collection.find(
                {"email": {"$in": email_list}, "status": "sent"}, {"email": 1}
            )
        }
    else:
        invited_set = set()

    # Build eligible list
    eligible = []
    for email, panelist in email_map.items():
        doc_status = str(panelist.get("status") or "").strip().lower()
        # Skip double opted-in
        if panelist.get("double_opt_in_completed"):
            continue
        if panelist.get("email_verified") and doc_status in {"active", "confirmed", "double_opted_in"}:
            continue
        if email in suppressed_set:
            continue
        if email in invited_set:
            continue
        eligible.append(panelist)

    sent = 0
    skipped = len(email_map) - len(eligible)
    failed = 0
    send_interval = 1.0 / SES_SEND_RATE if SES_SEND_RATE > 0 else 1.0

    # The SES budget bounds every bulk run, manual or cron — a hand-triggered
    # blast drains the shared daily quota just as effectively as the cron did.
    budget = ses_budget_for_bulk()
    cap_value = min(daily_cap, budget) if daily_cap is not None else budget
    capped = 0

    truncated = False
    for panelist in eligible:
        if sent >= cap_value:
            capped += 1
            continue

        email = (panelist.get("email") or "").lower().strip()

        # Send
        first_name = panelist.get("first_name", "")
        invite_token = uuid.uuid4().hex
        try:
            success, details = send_invitation_email(email, first_name, invite_token=invite_token)
        except SoftTimeLimitExceeded:
            truncated = True
            logger.warning(
                f"[panel] invite batch {batch_id} hit the worker time limit "
                f"after {sent} sends — stopping cleanly; the rest go out on the "
                f"next daily run. Raise PANEL_SES_SEND_RATE to send more per day."
            )
            break

        if success:
            log_invitation(
                email=email,
                panelist_id=str(panelist["_id"]),
                batch_id=batch_id,
                ses_message_id=details.get("ses_message_id", ""),
                status="sent",
                invite_token=invite_token,
                template_version=PANEL_TEMPLATE_VERSION,
            )
            sent += 1
        else:
            log_invitation(
                email=email,
                panelist_id=str(panelist["_id"]),
                batch_id=batch_id,
                status="failed",
                invite_token=invite_token,
                template_version=PANEL_TEMPLATE_VERSION,
            )
            failed += 1

        # Push this lead to the back of tomorrow's queue regardless of outcome,
        # so a bad address can't get permanently stuck at the front and block
        # everyone behind it.
        panelists_collection.update_one(
            {"_id": panelist["_id"]},
            {"$set": {"last_invited_at": datetime.utcnow()}},
        )

        # Rate limiting
        time.sleep(send_interval)

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

        login_url = "https://panel.surveyfieldwork.com/login"

        msg.attach(MIMEText(_build_login_invitation_plain(first_name, login_url), "plain", "utf-8"))
        msg.attach(MIMEText(_build_login_invitation_html(first_name, login_url), "html", "utf-8"))

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

    # Build query for registered users
    query = {"double_opt_in_completed": True}
    if country:
        query["country"] = {"$regex": f"^{country}$", "$options": "i"}

    # Bulk pre-fetch all registered panelists, oldest-invited-or-never-invited
    # first — same rotation fix as send_bulk_invitations, tracked in its own
    # field so the two invite types don't clobber each other's ordering.
    all_panelists = list(panelists_collection.find(
        query,
        {"email": 1, "first_name": 1, "_id": 1, "last_login_invite_sent_at": 1},
    ).sort([("last_login_invite_sent_at", 1)]))

    # Deduplicate and build email→doc map
    email_map: Dict[str, Any] = {}
    for p in all_panelists:
        email = (p.get("email") or "").lower().strip()
        if email and email not in email_map:
            email_map[email] = p

    email_list = list(email_map.keys())

    # Check if already sent login email today
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

    already_sent_today: set = {
        doc["email"].lower().strip()
        for doc in invitation_log_collection.find(
            {"email": {"$in": email_list}, "status": "sent", "type": "login",
             "sent_at": {"$gte": day_start_utc, "$lt": next_day_utc}},
            {"email": 1}
        )
    }

    # Build eligible list (not sent today)
    eligible = []
    for email, panelist in email_map.items():
        if email in already_sent_today:
            continue
        eligible.append(panelist)

    sent = 0
    skipped = len(email_map) - len(eligible)
    failed = 0
    send_interval = 1.0 / SES_SEND_RATE if SES_SEND_RATE > 0 else 1.0

    budget = ses_budget_for_bulk()
    cap_value = min(daily_cap, budget) if daily_cap is not None else budget
    capped = 0

    truncated = False
    for panelist in eligible:
        if sent >= cap_value:
            capped += 1
            continue

        email = (panelist.get("email") or "").lower().strip()

        # Send
        first_name = panelist.get("first_name", "")
        try:
            success, details = send_login_invitation_email(email, first_name)
        except SoftTimeLimitExceeded:
            truncated = True
            logger.warning(
                f"[panel] login batch {batch_id} hit the worker time limit "
                f"after {sent} sends — stopping cleanly; the rest go out on the "
                f"next daily run."
            )
            break

        if success:
            log_invitation(
                email=email,
                panelist_id=str(panelist["_id"]),
                batch_id=batch_id,
                ses_message_id=details.get("ses_message_id", ""),
                status="sent",
                template_version="panel-login-v1",
                type="login",
            )
            sent += 1
        else:
            log_invitation(
                email=email,
                panelist_id=str(panelist["_id"]),
                batch_id=batch_id,
                status="failed",
                template_version="panel-login-v1",
                type="login",
            )
            failed += 1

        panelists_collection.update_one(
            {"_id": panelist["_id"]},
            {"$set": {"last_login_invite_sent_at": datetime.utcnow()}},
        )

        # Rate limiting
        time.sleep(send_interval)

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
    Count panelists eligible for an invitation using bulk set queries
    (3 DB round-trips total instead of N×3).
    """
    query = {"status": "active"}
    if country:
        query["country"] = {"$regex": f"^{country}$", "$options": "i"}

    # 1. Fetch all active panelists with fields needed for double-opt-in check
    panelist_docs = list(panelists_collection.find(
        query, {"email": 1, "double_opt_in_completed": 1, "email_verified": 1, "status": 1}
    ))

    email_map: dict = {}
    for doc in panelist_docs:
        email = (doc.get("email") or "").lower().strip()
        if email:
            email_map[email] = doc

    if not email_map:
        return 0

    email_list = list(email_map.keys())

    # 2. Bulk fetch suppressed emails
    suppressed: set = {
        doc["email"].lower().strip()
        for doc in suppression_collection.find({"email": {"$in": email_list}}, {"email": 1})
    }

    # 3. Bulk fetch already-invited emails
    if daily_mode:
        from datetime import timezone as _tz
        from zoneinfo import ZoneInfo
        try:
            tz = ZoneInfo(PANEL_SEND_TIMEZONE)
        except Exception:
            tz = ZoneInfo("UTC")
        from datetime import datetime as _dt, timedelta as _td
        now_local = _dt.now(tz)
        day_start_utc = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(_tz.utc).replace(tzinfo=None)
        next_day_utc = (day_start_utc + _td(days=1))
        invited: set = {
            doc["email"].lower().strip()
            for doc in invitation_log_collection.find(
                {"email": {"$in": email_list}, "status": "sent",
                 "sent_at": {"$gte": day_start_utc, "$lt": next_day_utc}},
                {"email": 1}
            )
        }
    elif not force_resend:
        invited = {
            doc["email"].lower().strip()
            for doc in invitation_log_collection.find(
                {"email": {"$in": email_list}, "status": "sent"}, {"email": 1}
            )
        }
    else:
        invited = set()

    count = 0
    for email, doc in email_map.items():
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
        count += 1

    return count
