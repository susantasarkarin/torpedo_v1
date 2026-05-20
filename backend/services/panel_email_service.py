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
PANEL_TEMPLATE_VERSION = os.getenv("PANEL_TEMPLATE_VERSION", "panel-invite-v3")
PANEL_SEND_TIMEZONE = os.getenv("PANEL_SEND_TIMEZONE", "Asia/Kolkata")
PANEL_DAILY_SEND_CAP = int(os.getenv("PANEL_DAILY_SEND_CAP", "1000"))

# Rate limiting: SES sandbox = 1/sec, production = 14/sec
SES_SEND_RATE = float(os.getenv("PANEL_SES_SEND_RATE", "1"))  # emails per second


def _get_ses_client():
    """Create a boto3 SES client."""
    kwargs = {"region_name": AWS_SES_REGION}
    if AWS_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY
    return boto3.client("ses", **kwargs)


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
            <td style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 55%,#334155 100%);padding:44px 40px;text-align:center;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center">
                    <div style="width:64px;height:64px;background-color:rgba(255,255,255,0.16);border-radius:16px;display:inline-block;line-height:64px;font-size:28px;color:#ffffff;font-weight:bold;margin-bottom:16px;">CR</div>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-top:8px;">
                    <h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:700;letter-spacing:-0.4px;">Join The Cogentix Panel</h1>
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
                  <td style="padding:16px 20px;background-color:#fff7ed;border-radius:12px;border-left:4px solid #f97316;">
                    <table role="presentation" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">&#10003;</span>
                          <strong style="color:#9a3412;font-size:14px;">Paid Surveys</strong>
                          <span style="color:#4b5563;font-size:13px;"> — Cash out via PayPal, gift cards, or bank transfer</span>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">&#10003;</span>
                          <strong style="color:#9a3412;font-size:14px;">Fast Participation</strong>
                          <span style="color:#4b5563;font-size:13px;"> — Most take just 5-15 minutes to complete</span>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">&#10003;</span>
                          <strong style="color:#9a3412;font-size:14px;">Double Opt-In Protection</strong>
                          <span style="color:#4b5563;font-size:13px;"> — Only confirmed users stay active in the panel</span>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">&#10003;</span>
                          <strong style="color:#9a3412;font-size:14px;">Your Privacy Matters</strong>
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
                       style="display:inline-block;padding:16px 44px;background:linear-gradient(135deg,#f97316,#ea580c);color:#ffffff;text-decoration:none;font-size:16px;font-weight:700;border-radius:12px;letter-spacing:0.3px;box-shadow:0 8px 20px rgba(249,115,22,0.35);">
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
                      <a href="https://panel.surveyfieldwork.com/unsubscribe" style="color:#6366f1;text-decoration:underline;">Unsubscribe</a>
                      &nbsp;|&nbsp;
                      <a href="https://panel.surveyfieldwork.com/privacy" style="color:#6366f1;text-decoration:underline;">Privacy Policy</a>
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

You're invited to join the Cogentix Research Panel.

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

    panelist_cursor = panelists_collection.find(
        query,
        {"email": 1, "first_name": 1, "_id": 1},
    )

    sent = 0
    skipped = 0
    failed = 0
    seen_emails = set()
    send_interval = 1.0 / SES_SEND_RATE if SES_SEND_RATE > 0 else 1.0

    cap_value = daily_cap if daily_cap is not None else PANEL_DAILY_SEND_CAP
    capped = 0

    for panelist in panelist_cursor:
      if daily_mode and sent >= cap_value:
        capped += 1
        continue

        email = (panelist.get("email") or "").lower().strip()
        if not email:
            skipped += 1
            continue

        # Deduplicate within batch
        if email in seen_emails:
            skipped += 1
            continue
        seen_emails.add(email)

        # Stop workflow once double opt-in is complete.
        if is_double_opted_in(email):
          skipped += 1
          continue

        # Check suppression list
        if is_suppressed(email):
            skipped += 1
            continue

        # Daily campaign mode: send at most once per local day.
        if daily_mode:
          if has_been_invited_today(email, timezone_name=PANEL_SEND_TIMEZONE):
            skipped += 1
            continue
        else:
          # Legacy mode: one-time invite unless force_resend is enabled.
          if not force_resend and has_been_invited(email):
            skipped += 1
            continue

        # Send
        first_name = panelist.get("first_name", "")
        invite_token = uuid.uuid4().hex
        success, details = send_invitation_email(email, first_name, invite_token=invite_token)

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

        # Rate limiting
        time.sleep(send_interval)

    logger.info(f"Bulk invitation complete batch={batch_id}: sent={sent} skipped={skipped} failed={failed}")
    return {
        "batch_id": batch_id,
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
      "capped": capped,
      "daily_mode": daily_mode,
      "daily_cap": cap_value if daily_mode else None,
      "timezone": PANEL_SEND_TIMEZONE if daily_mode else None,
        "total_processed": sent + skipped + failed,
    }


  def get_eligible_count(
    country: Optional[str] = None,
    force_resend: bool = False,
    daily_mode: bool = False,
  ) -> int:
    """
    Count how many panelists would receive an invitation
    (excluding suppressed and already invited).
    """
    query = {"status": "active"}
    if country:
        query["country"] = {"$regex": f"^{country}$", "$options": "i"}

    count = 0
    for panelist in panelists_collection.find(query, {"email": 1}):
        email = (panelist.get("email") or "").lower().strip()
        if not email:
            continue
        if is_double_opted_in(email):
          continue
        if is_suppressed(email):
            continue
        if daily_mode:
          if has_been_invited_today(email, timezone_name=PANEL_SEND_TIMEZONE):
            continue
        elif not force_resend and has_been_invited(email):
          continue
        count += 1

    return count
