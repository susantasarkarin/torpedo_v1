"""
Panel transactional email — double opt-in verification and password reset.

These are the two mails a panelist expects to arrive within seconds of an
action they just took, and until now neither was ever sent by this backend:
`/panel/signup` created the account without any verification mail, and
`/panel/forgot-password` generated a reset token and then dropped it on the
floor behind a `# TODO: Send email` comment. Both are wired up here.

Transactional mail deliberately does NOT go through the bulk-invite path:
  - no suppression-list check (a hard bounce on a marketing blast must not
    block someone's password reset)
  - no daily cap or rotation
  - no SES budget gate — ses_budget_for_bulk() exists to hold quota back FOR
    this traffic, so gating it on the same budget would be circular

Sends reuse the cached SES client from panel_email_service.
"""

import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Tuple
from urllib.parse import quote

from botocore.exceptions import ClientError

from services.panel_email_service import _get_ses_client, PANEL_LOGO_URL, SES_FROM_EMAIL, SES_FROM_NAME

logger = logging.getLogger(__name__)

# Public base for links inside transactional mail. Must be the host the
# panelist actually browses, not the API host.
PANEL_PUBLIC_BASE_URL = os.getenv(
    "PANEL_PUBLIC_BASE_URL", "https://torpedo.cogentixresearch.com"
).rstrip("/")
# Verification is confirmed server-side then redirected, so it points at the
# API; the reset link needs a form, so it points at the SPA route.
PANEL_VERIFY_URL = f"{PANEL_PUBLIC_BASE_URL}/api/panel/verify-email"
PANEL_RESET_URL = f"{PANEL_PUBLIC_BASE_URL}/panel/reset-password"

VERIFICATION_TOKEN_TTL_HOURS = int(os.getenv("PANEL_VERIFY_TOKEN_TTL_HOURS", "72"))
RESET_TOKEN_TTL_HOURS = int(os.getenv("PANEL_RESET_TOKEN_TTL_HOURS", "1"))


# ============== TOKENS ==============

def new_token() -> str:
    """URL-safe, unguessable single-use token."""
    return secrets.token_urlsafe(32)


def verification_expiry() -> datetime:
    return datetime.utcnow() + timedelta(hours=VERIFICATION_TOKEN_TTL_HOURS)


def reset_expiry() -> datetime:
    return datetime.utcnow() + timedelta(hours=RESET_TOKEN_TTL_HOURS)


# ============== TEMPLATE ==============

def _shell(title: str, heading: str, subheading: str, body_html: str) -> str:
    """Shared transactional layout — same visual language as the invite mail,
    minus the marketing benefits block, so these read as account mail."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#f7fafc;font-family:'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f7fafc;padding:40px 20px;">
    <tr>
      <td align="center">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background-color:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 12px 32px rgba(15,23,42,0.12);">
          <tr>
            <td style="background:linear-gradient(135deg,#071733 0%,#0c2d63 58%,#13498b 100%);padding:40px;text-align:center;">
              <img src="{PANEL_LOGO_URL}" alt="SurveyFieldwork" width="200" style="display:block;max-width:200px;width:100%;height:auto;margin:0 auto 16px;border:0;outline:none;text-decoration:none;" />
              <h1 style="margin:0;color:#ffffff;font-size:25px;font-weight:700;letter-spacing:-0.3px;">{heading}</h1>
              <p style="margin:10px 0 0;color:rgba(255,255,255,0.9);font-size:14px;">{subheading}</p>
            </td>
          </tr>
          <tr>
            <td style="padding:36px 40px;">
              {body_html}
            </td>
          </tr>
          <tr>
            <td style="background-color:#f9fafb;padding:22px 40px;border-top:1px solid #e5e7eb;text-align:center;">
              <p style="margin:0 0 6px;color:#6b7280;font-size:12px;">
                &copy; {datetime.utcnow().year} SurveyFieldwork. All rights reserved.
              </p>
              <p style="margin:0;color:#9ca3af;font-size:11px;line-height:1.5;">
                This is an automated account message — please do not reply.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _cta(link: str, label: str) -> str:
    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td align="center" style="padding:8px 0 26px;">
            <a href="{link}" style="display:inline-block;padding:15px 42px;background:linear-gradient(135deg,#0ea5e9,#0284c7);color:#ffffff;text-decoration:none;font-size:16px;font-weight:700;border-radius:12px;letter-spacing:0.3px;box-shadow:0 8px 20px rgba(2,132,199,0.35);">
              {label}
            </a>
          </td>
        </tr>
      </table>
      <p style="margin:0 0 6px;color:#64748b;font-size:12px;line-height:1.6;">
        If the button doesn't work, copy this link into your browser:
      </p>
      <p style="margin:0 0 4px;word-break:break-all;">
        <a href="{link}" style="color:#0284c7;font-size:12px;">{link}</a>
      </p>"""


# ============== SEND ==============

def _send(to_email: str, subject: str, html: str, plain: str, tag: str) -> Tuple[bool, Dict[str, Any]]:
    """Send one transactional message via SES."""
    try:
        msg = MIMEMultipart("alternative")
        msg["To"] = to_email
        msg["From"] = f"{SES_FROM_NAME} <{SES_FROM_EMAIL}>"
        msg["Subject"] = subject
        msg["Message-ID"] = f"<panel-{tag}-{uuid.uuid4()}@surveyfieldwork.com>"
        # Transactional mail must never be filed as a bulk blast by receivers,
        # and must not carry List-Unsubscribe — unsubscribing from a password
        # reset is meaningless and hurts placement.
        msg["Auto-Submitted"] = "auto-generated"

        msg.attach(MIMEText(plain, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        response = _get_ses_client().send_raw_email(
            Source=f"{SES_FROM_NAME} <{SES_FROM_EMAIL}>",
            Destinations=[to_email],
            RawMessage={"Data": msg.as_bytes()},
        )
        message_id = response.get("MessageId", "")
        logger.info(f"[panel-transactional] {tag} sent -> {to_email} | SES MessageId={message_id}")
        return True, {"ses_message_id": message_id}

    except ClientError as e:
        code = e.response["Error"]["Code"]
        message = e.response["Error"]["Message"]
        # Throttling here means the bulk invite run has eaten the daily quota
        # that PANEL_SES_RESERVE is supposed to protect — loud, because the
        # user-visible symptom is "the reset email never arrived".
        if code in {"Throttling", "TooManyRequestsException", "LimitExceededException"}:
            logger.error(
                f"[panel-transactional] SES QUOTA EXHAUSTED sending {tag} to {to_email}: "
                f"{code} — {message}. Raise PANEL_SES_RESERVE; bulk sending has "
                f"consumed the headroom reserved for transactional mail."
            )
        else:
            logger.error(f"[panel-transactional] SES error sending {tag} to {to_email}: {code} — {message}")
        return False, {"error": code, "message": message}
    except Exception as e:
        logger.error(f"[panel-transactional] unexpected error sending {tag} to {to_email}: {e}")
        return False, {"error": str(e)}


def send_verification_email(to_email: str, first_name: str, token: str) -> Tuple[bool, Dict[str, Any]]:
    """Double opt-in: confirm the address actually belongs to the signup."""
    link = f"{PANEL_VERIFY_URL}?token={quote(token)}"
    greeting = f"Hi {first_name}," if first_name else "Hello,"

    body = f"""
      <p style="margin:0 0 18px;color:#1f2937;font-size:16px;line-height:1.6;">{greeting}</p>
      <p style="margin:0 0 24px;color:#334155;font-size:15px;line-height:1.7;">
        Thanks for signing up. Confirm this email address to activate your panel
        account and start receiving survey invitations.
      </p>
      {_cta(link, "Confirm My Email &rarr;")}
      <p style="margin:18px 0 0;color:#64748b;font-size:12px;line-height:1.6;">
        This link expires in {VERIFICATION_TOKEN_TTL_HOURS} hours. If you didn't
        create this account, you can safely ignore this email.
      </p>"""

    plain = f"""{greeting}

Thanks for signing up. Confirm this email address to activate your panel
account and start receiving survey invitations.

Confirm your email: {link}

This link expires in {VERIFICATION_TOKEN_TTL_HOURS} hours. If you didn't create
this account, you can safely ignore this email.

---
SurveyFieldwork
"""

    return _send(
        to_email,
        "Confirm your email to activate your panel account",
        _shell(
            "Confirm your email",
            "Confirm Your Email",
            "One click activates your panel account",
            body,
        ),
        plain,
        "verify",
    )


def send_password_reset_email(to_email: str, first_name: str, token: str) -> Tuple[bool, Dict[str, Any]]:
    """Password reset link, valid for RESET_TOKEN_TTL_HOURS."""
    link = f"{PANEL_RESET_URL}?token={quote(token)}"
    greeting = f"Hi {first_name}," if first_name else "Hello,"

    body = f"""
      <p style="margin:0 0 18px;color:#1f2937;font-size:16px;line-height:1.6;">{greeting}</p>
      <p style="margin:0 0 24px;color:#334155;font-size:15px;line-height:1.7;">
        We received a request to reset the password for your panel account.
        Choose a new password using the button below.
      </p>
      {_cta(link, "Reset My Password &rarr;")}
      <p style="margin:18px 0 0;color:#64748b;font-size:12px;line-height:1.6;">
        This link expires in {RESET_TOKEN_TTL_HOURS} hour(s) and can only be used
        once. If you didn't request a reset, ignore this email — your password
        stays unchanged.
      </p>"""

    plain = f"""{greeting}

We received a request to reset the password for your panel account.

Reset your password: {link}

This link expires in {RESET_TOKEN_TTL_HOURS} hour(s) and can only be used once.
If you didn't request a reset, ignore this email — your password stays unchanged.

---
SurveyFieldwork
"""

    return _send(
        to_email,
        "Reset your panel password",
        _shell(
            "Reset your password",
            "Reset Your Password",
            "Choose a new password for your panel account",
            body,
        ),
        plain,
        "reset",
    )
