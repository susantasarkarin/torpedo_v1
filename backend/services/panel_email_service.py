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

import boto3
from botocore.exceptions import ClientError
from pymongo import MongoClient

from services.panel_bounce_handler import (
    is_suppressed,
    has_been_invited,
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
SES_FROM_EMAIL = os.getenv("PANEL_SES_FROM_EMAIL", os.getenv("SES_FROM_EMAIL", "noreply@surveyfieldwork.com"))
SES_FROM_NAME = os.getenv("PANEL_SES_FROM_NAME", "SurveyFieldwork")

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

def _build_invitation_html(first_name: str = "") -> str:
    """Build a beautiful, responsive HTML invitation email."""
    greeting = f"Hi {first_name}," if first_name else "Hello,"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>You're Invited to SurveyFieldwork</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f6f9;font-family:'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f6f9;padding:40px 20px;">
    <tr>
      <td align="center">
        <!-- Main Container -->
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background-color:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#4f46e5 0%,#7c3aed 50%,#a855f7 100%);padding:48px 40px;text-align:center;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center">
                    <div style="width:64px;height:64px;background-color:rgba(255,255,255,0.2);border-radius:16px;display:inline-block;line-height:64px;font-size:28px;color:#ffffff;font-weight:bold;margin-bottom:16px;">SF</div>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-top:8px;">
                    <h1 style="margin:0;color:#ffffff;font-size:26px;font-weight:700;letter-spacing:-0.5px;">You're Invited!</h1>
                    <p style="margin:8px 0 0;color:rgba(255,255,255,0.85);font-size:15px;font-weight:400;">Join thousands earning rewards for sharing their opinions</p>
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
              <p style="margin:0 0 24px;color:#374151;font-size:15px;line-height:1.7;">
                We'd love for you to be part of <strong>SurveyFieldwork</strong> — a premium survey panel where your opinions shape products, services, and policies around the world.
              </p>

              <!-- Benefits -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:32px;">
                <tr>
                  <td style="padding:16px 20px;background-color:#f0fdf4;border-radius:12px;border-left:4px solid #22c55e;">
                    <table role="presentation" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">&#10003;</span>
                          <strong style="color:#166534;font-size:14px;">Earn Real Rewards</strong>
                          <span style="color:#4b5563;font-size:13px;"> — Cash out via PayPal, gift cards, or bank transfer</span>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">&#10003;</span>
                          <strong style="color:#166534;font-size:14px;">Quick Surveys</strong>
                          <span style="color:#4b5563;font-size:13px;"> — Most take just 5-15 minutes to complete</span>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="color:#15803d;font-size:18px;margin-right:8px;">&#10003;</span>
                          <strong style="color:#166534;font-size:14px;">Your Privacy Matters</strong>
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
                    <a href="https://panel.surveyfieldwork.com/signup"
                       style="display:inline-block;padding:16px 48px;background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#ffffff;text-decoration:none;font-size:16px;font-weight:700;border-radius:12px;letter-spacing:0.3px;box-shadow:0 4px 16px rgba(79,70,229,0.35);">
                      Start Earning Now &rarr;
                    </a>
                  </td>
                </tr>
              </table>

              <!-- Social Proof -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #e5e7eb;padding-top:24px;">
                <tr>
                  <td align="center">
                    <p style="margin:0 0 8px;color:#6b7280;font-size:13px;font-weight:500;text-transform:uppercase;letter-spacing:1px;">Trusted by panelists worldwide</p>
                    <table role="presentation" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="padding:0 16px;text-align:center;">
                          <p style="margin:0;color:#4f46e5;font-size:24px;font-weight:800;">10K+</p>
                          <p style="margin:2px 0 0;color:#9ca3af;font-size:11px;">Active Members</p>
                        </td>
                        <td style="padding:0 16px;text-align:center;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;">
                          <p style="margin:0;color:#4f46e5;font-size:24px;font-weight:800;">$50K+</p>
                          <p style="margin:2px 0 0;color:#9ca3af;font-size:11px;">Rewards Paid</p>
                        </td>
                        <td style="padding:0 16px;text-align:center;">
                          <p style="margin:0;color:#4f46e5;font-size:24px;font-weight:800;">4.8/5</p>
                          <p style="margin:2px 0 0;color:#9ca3af;font-size:11px;">Avg Rating</p>
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


def _build_invitation_plain(first_name: str = "") -> str:
    """Build plain-text version of the invitation."""
    greeting = f"Hi {first_name}," if first_name else "Hello,"
    return f"""{greeting}

You're invited to join SurveyFieldwork — a premium survey panel where your opinions shape products, services, and policies around the world.

Why join?
- Earn Real Rewards: Cash out via PayPal, gift cards, or bank transfer
- Quick Surveys: Most take just 5-15 minutes
- Your Privacy Matters: All responses are 100% anonymous
- 100% Free: No fees, no catches

Start earning now: https://panel.surveyfieldwork.com/signup

Trusted by 10K+ panelists worldwide.

---
SurveyFieldwork
Unsubscribe: https://panel.surveyfieldwork.com/unsubscribe
Privacy: https://panel.surveyfieldwork.com/privacy
"""


# ============== SEND FUNCTIONS ==============

def send_invitation_email(
    to_email: str,
    first_name: str = "",
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
        msg["Subject"] = "You're Invited to Earn Rewards with SurveyFieldwork!"
        msg["Message-ID"] = f"<panel-{uuid.uuid4()}@surveyfieldwork.com>"

        msg.attach(MIMEText(_build_invitation_plain(first_name), "plain", "utf-8"))
        msg.attach(MIMEText(_build_invitation_html(first_name), "html", "utf-8"))

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

    for panelist in panelist_cursor:
        email = (panelist.get("email") or "").lower().strip()
        if not email:
            skipped += 1
            continue

        # Deduplicate within batch
        if email in seen_emails:
            skipped += 1
            continue
        seen_emails.add(email)

        # Check suppression list
        if is_suppressed(email):
            skipped += 1
            continue

        # Check already invited
        if not force_resend and has_been_invited(email):
            skipped += 1
            continue

        # Send
        first_name = panelist.get("first_name", "")
        success, details = send_invitation_email(email, first_name)

        if success:
            log_invitation(
                email=email,
                panelist_id=str(panelist["_id"]),
                batch_id=batch_id,
                ses_message_id=details.get("ses_message_id", ""),
                status="sent",
            )
            sent += 1
        else:
            log_invitation(
                email=email,
                panelist_id=str(panelist["_id"]),
                batch_id=batch_id,
                status="failed",
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
        "total_processed": sent + skipped + failed,
    }


def get_eligible_count(country: Optional[str] = None, force_resend: bool = False) -> int:
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
        if is_suppressed(email):
            continue
        if not force_resend and has_been_invited(email):
            continue
        count += 1

    return count
