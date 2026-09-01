"""
Panel re-engagement drips — mail the people who stalled in the funnel.

Before this, someone who registered and never confirmed, or confirmed and
never filled in a profile, simply sat in the database forever: the join-invite
cron skipped them (they are already opted in, or already registered) and
nothing else ever went out. These three sequences pick up each of those
segments.

Segment definitions come from services/panel_funnel.py, so what the dashboard
shows as "Registered, no double opt-in" is exactly who gets mailed.

Stop rules, applied to every stage:
  - suppression list (bounced / complained)   -> never mailed
  - status dnd / unsubscribed / bounced       -> excluded by the segment query
  - MAX_SENDS per stage                       -> the sequence ends, permanently
  - GAP_DAYS between sends within a stage     -> no consecutive-day mail
  - the panelist leaves the segment           -> the query stops matching them
  - SES bulk budget (ses_budget_for_bulk)     -> transactional mail is protected

Per-panelist state lives on the panelist document as drip_<stage>_count and
drip_<stage>_last_sent_at; every send is also written to panel_invitation_log
with type="drip_<stage>" so it shows up in the existing dashboards.
"""

import logging
import os
import uuid
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional, Tuple

from botocore.exceptions import ClientError

from services.panel_bounce_handler import log_invitation, panelists_collection, suppression_collection, invitation_log_collection
from services.panel_email_service import _apply_unsubscribe, _get_ses_client, _send_batch_concurrently, ses_budget_for_bulk, PANEL_LOGO_URL, SES_FROM_EMAIL, SES_FROM_NAME, PANEL_MAX_TOTAL_EMAILS_PER_PANELIST
from services.panel_funnel import SEGMENTS

logger = logging.getLogger(__name__)

PANEL_PUBLIC_BASE_URL = os.getenv(
    "PANEL_PUBLIC_BASE_URL", "https://torpedo.cogentixresearch.com"
).rstrip("/")

# Hard ceiling on any one drip run, independent of the SES budget. A drip is
# never urgent, and a runaway sequence is far more damaging to sender
# reputation than a slow one.
DRIP_RUN_CAP = int(os.getenv("PANEL_DRIP_RUN_CAP", "5000"))


# ============== STAGE CONFIG ==============
# max_sends is deliberately small. These people did not ask for a reminder
# series; after this many nudges, silence is the correct product decision and
# the sequence never restarts.

STAGES: Dict[str, Dict[str, Any]] = {
    "verify": {
        "segment": "signed_up_unverified",
        "max_sends": 2,
        "gap_days": 3,
        "subject": "Confirm your email to finish joining the panel",
        "heading": "One Step Left",
        "subheading": "Confirm your email to activate your account",
        "lead": (
            "You created a panel account but haven't confirmed your email address yet. "
            "Confirm it now and we'll start sending you paid surveys."
        ),
        "cta_label": "Confirm My Email",
        "cta_path": "/panel/login?resend=1",
    },
    "profile": {
        "segment": "opted_in_no_profile",
        "max_sends": 3,
        "gap_days": 4,
        "subject": "Add a few details and unlock more surveys",
        "heading": "Unlock More Surveys",
        "subheading": "A complete profile means better matches",
        "lead": (
            "Your account is confirmed — nice work. Surveys are matched on your profile, "
            "so the more of it you fill in, the more invitations you'll qualify for. "
            "It takes about two minutes."
        ),
        "cta_label": "Complete My Profile",
        "cta_path": "/panel/profile",
    },
    "activate": {
        "segment": "profile_no_activity",
        "max_sends": 3,
        "gap_days": 7,
        "subject": "Your first paid survey is waiting",
        "heading": "Ready When You Are",
        "subheading": "Your profile is complete — start earning",
        "lead": (
            "Your profile is all set, but you haven't taken a survey yet. "
            "Log in to see what's currently available for you and start earning rewards."
        ),
        "cta_label": "See My Surveys",
        "cta_path": "/panel/dashboard",
    },
}


# ============== TEMPLATE ==============

def _render(stage: Dict[str, Any], first_name: str, unsubscribe: str) -> Tuple[str, str]:
    """(html, plain) for one drip stage."""
    greeting = f"Hi {first_name}," if first_name else "Hello,"
    link = f"{PANEL_PUBLIC_BASE_URL}{stage['cta_path']}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{stage['heading']}</title>
</head>
<body style="margin:0;padding:0;background:#f7fafc;font-family:'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f7fafc;padding:40px 20px;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background-color:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 12px 32px rgba(15,23,42,0.12);">
        <tr>
          <td style="background:linear-gradient(135deg,#071733 0%,#0c2d63 58%,#13498b 100%);padding:40px;text-align:center;">
            <img src="{PANEL_LOGO_URL}" alt="SurveyFieldwork" width="200" style="display:block;max-width:200px;width:100%;height:auto;margin:0 auto 16px;border:0;outline:none;text-decoration:none;" />
            <h1 style="margin:0;color:#ffffff;font-size:25px;font-weight:700;letter-spacing:-0.3px;">{stage['heading']}</h1>
            <p style="margin:10px 0 0;color:rgba(255,255,255,0.9);font-size:14px;">{stage['subheading']}</p>
          </td>
        </tr>
        <tr>
          <td style="padding:36px 40px;">
            <p style="margin:0 0 18px;color:#1f2937;font-size:16px;line-height:1.6;">{greeting}</p>
            <p style="margin:0 0 26px;color:#334155;font-size:15px;line-height:1.7;">{stage['lead']}</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              <tr><td align="center" style="padding:4px 0 26px;">
                <a href="{link}" style="display:inline-block;padding:15px 42px;background:linear-gradient(135deg,#0ea5e9,#0284c7);color:#ffffff;text-decoration:none;font-size:16px;font-weight:700;border-radius:12px;letter-spacing:0.3px;box-shadow:0 8px 20px rgba(2,132,199,0.35);">
                  {stage['cta_label']} &rarr;
                </a>
              </td></tr>
            </table>
            <p style="margin:0;color:#64748b;font-size:12px;line-height:1.6;text-align:center;">
              If the button doesn't work, open: <a href="{link}" style="color:#0284c7;">{link}</a>
            </p>
          </td>
        </tr>
        <tr>
          <td style="background-color:#f9fafb;padding:22px 40px;border-top:1px solid #e5e7eb;text-align:center;">
            <p style="margin:0 0 6px;color:#6b7280;font-size:12px;">
              &copy; {datetime.utcnow().year} SurveyFieldwork. All rights reserved.
            </p>
            <p style="margin:0;color:#9ca3af;font-size:11px;line-height:1.5;">
              You're receiving this because you started signing up for our panel.<br>
              <a href="{unsubscribe}" style="color:#0284c7;text-decoration:underline;">Unsubscribe</a>
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    plain = f"""{greeting}

{stage['lead']}

{stage['cta_label']}: {link}

---
SurveyFieldwork
Unsubscribe: {unsubscribe}
"""
    return html, plain


def _send_one_drip(stage_key: str, to_email: str, first_name: str) -> Tuple[bool, Dict[str, Any]]:
    stage = STAGES[stage_key]

    try:
        msg = MIMEMultipart("alternative")
        msg["To"] = to_email
        msg["From"] = f"{SES_FROM_NAME} <{SES_FROM_EMAIL}>"
        msg["Subject"] = stage["subject"]
        msg["Message-ID"] = f"<panel-drip-{stage_key}-{uuid.uuid4()}@surveyfieldwork.com>"
        # Per-recipient signed opt-out, so the header control and the footer
        # link resolve to the same address without a lookup.
        unsub_link = _apply_unsubscribe(msg, to_email)
        html, plain = _render(stage, first_name, unsub_link)

        msg.attach(MIMEText(plain, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        response = _get_ses_client().send_raw_email(
            Source=f"{SES_FROM_NAME} <{SES_FROM_EMAIL}>",
            Destinations=[to_email],
            RawMessage={"Data": msg.as_bytes()},
        )
        return True, {"ses_message_id": response.get("MessageId", "")}
    except ClientError as e:
        code = e.response["Error"]["Code"]
        logger.error(f"[drip-{stage_key}] SES error to {to_email}: {code}")
        return False, {"error": code, "message": e.response["Error"]["Message"]}
    except Exception as e:
        logger.error(f"[drip-{stage_key}] unexpected error to {to_email}: {e}")
        return False, {"error": str(e)}


# ============== RUNNER ==============

def _eligible_query(stage_key: str) -> Dict[str, Any]:
    """Segment membership + this stage's cap and cooldown."""
    stage = STAGES[stage_key]
    segment_query = SEGMENTS[stage["segment"]]["query"]()
    count_field = f"drip_{stage_key}_count"
    sent_field = f"drip_{stage_key}_last_sent_at"
    cooldown_start = datetime.utcnow() - timedelta(days=stage["gap_days"])

    return {
        "$and": [
            segment_query,
            {"email": {"$exists": True, "$nin": [None, ""]}},
            # Under the per-stage send cap.
            {"$or": [
                {count_field: {"$exists": False}},
                {count_field: {"$lt": stage["max_sends"]}},
            ]},
            # Outside the per-stage cooldown.
            {"$or": [
                {sent_field: {"$exists": False}},
                {sent_field: None},
                {sent_field: {"$lt": cooldown_start}},
            ]},
        ]
    }


def run_drip_stage(
    stage_key: str,
    limit: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Send one batch of the named drip stage."""
    if stage_key not in STAGES:
        raise ValueError(f"unknown drip stage: {stage_key}")

    stage = STAGES[stage_key]
    batch_id = f"drip-{stage_key}-{uuid.uuid4().hex[:10]}"

    budget = ses_budget_for_bulk()
    cap = min(limit or DRIP_RUN_CAP, DRIP_RUN_CAP, budget)
    if cap <= 0:
        logger.warning(f"[drip-{stage_key}] no SES budget available; skipping run")
        return {"stage": stage_key, "batch_id": batch_id, "sent": 0, "skipped": 0,
                "failed": 0, "eligible_examined": 0, "reason": "no_ses_budget"}

    candidates = list(
        panelists_collection.find(
            _eligible_query(stage_key),
            {"email": 1, "first_name": 1, "_id": 1},
        ).limit(cap)
    )

    # The suppression list is checked here rather than in the query: it lives
    # in a separate collection, so it cannot be joined, and it is the one stop
    # rule that must never be skipped.
    emails = [(p.get("email") or "").lower().strip() for p in candidates]
    suppressed = set()
    for start in range(0, len(emails), 2000):
        chunk = emails[start:start + 2000]
        suppressed |= {
            d["email"].lower().strip()
            for d in suppression_collection.find({"email": {"$in": chunk}}, {"email": 1})
        }

    # Global lifetime ceiling across every panel email type. Each stage already
    # caps its own sequence, but nothing bounded the sum, so a panelist could
    # absorb register invites, login reminders and three separate drip
    # sequences in turn. An audit found drip mail still going to people on
    # 14-30 lifetime emails.
    over_ceiling = set()
    if PANEL_MAX_TOTAL_EMAILS_PER_PANELIST > 0:
        for start in range(0, len(emails), 2000):
            chunk = emails[start:start + 2000]
            over_ceiling |= {
                r["_id"]
                for r in invitation_log_collection.aggregate([
                    {"$match": {"email": {"$in": chunk},
                                "sent_at": {"$exists": True, "$ne": None}}},
                    {"$group": {"_id": "$email", "n": {"$sum": 1}}},
                    {"$match": {"n": {"$gte": PANEL_MAX_TOTAL_EMAILS_PER_PANELIST}}},
                ])
            }

    to_send = [
        p for p in candidates
        if (p.get("email") or "").lower().strip() not in suppressed
        and (p.get("email") or "").lower().strip() not in over_ceiling
    ]
    skipped = len(candidates) - len(to_send)

    if dry_run:
        return {
            "stage": stage_key, "batch_id": batch_id, "dry_run": True,
            "would_send": len(to_send), "skipped_suppressed": skipped,
            "eligible_examined": len(candidates),
        }

    count_field = f"drip_{stage_key}_count"
    sent_field = f"drip_{stage_key}_last_sent_at"

    def _worker(panelist) -> bool:
        email = (panelist.get("email") or "").lower().strip()
        first_name = panelist.get("first_name", "")
        ok, details = _send_one_drip(stage_key, email, first_name)

        log_invitation(
            email=email,
            panelist_id=str(panelist["_id"]),
            batch_id=batch_id,
            ses_message_id=details.get("ses_message_id", "") if ok else "",
            status="sent" if ok else "failed",
            template_version=f"panel-drip-{stage_key}-v1",
            type=f"drip_{stage_key}",
            error_code="" if ok else str(details.get("error", "")),
            error_message="" if ok else str(details.get("message", "")),
        )
        # Counted on attempt, not on success: a repeatedly failing address must
        # still exhaust its cap rather than be retried forever.
        panelists_collection.update_one(
            {"_id": panelist["_id"]},
            {"$inc": {count_field: 1}, "$set": {sent_field: datetime.utcnow()}},
        )
        return ok

    sent, failed, truncated = _send_batch_concurrently(to_send, _worker)

    result = {
        "stage": stage_key,
        "segment": stage["segment"],
        "batch_id": batch_id,
        "sent": sent,
        "failed": failed,
        "skipped_suppressed": skipped,
        "eligible_examined": len(candidates),
        "truncated": truncated,
        "cap": cap,
    }
    logger.info(
        f"[drip-{stage_key}] batch={batch_id} sent={sent} failed={failed} "
        f"skipped_suppressed={skipped} cap={cap} truncated={truncated}"
    )
    return result


def run_all_drip_stages(dry_run: bool = False) -> Dict[str, Any]:
    """Run every stage in funnel order, earliest leak first.

    Order matters: someone who confirms after the verify nudge should get the
    profile nudge from a later run, not both in the same pass.
    """
    results: List[Dict[str, Any]] = []
    for stage_key in ("verify", "profile", "activate"):
        try:
            results.append(run_drip_stage(stage_key, dry_run=dry_run))
        except Exception as e:
            logger.error(f"[drip] stage {stage_key} failed: {e}", exc_info=True)
            results.append({"stage": stage_key, "error": str(e)})

    return {
        "stages": results,
        "total_sent": sum(r.get("sent", 0) for r in results),
        "dry_run": dry_run,
    }
