"""
OUTREACH MAILER
===============
Generates a personalized cold email per qualified lead via Bedrock, validates
it, and either previews it (default) or sends it (explicit --send).

SAFETY POSTURE
--------------
- `--dry-run` is the DEFAULT. Sending requires an explicit `--send`.
- Sending is refused outright when: pitch copy is still a placeholder, the
  sender postal address is unset (CAN-SPAM), or the unsubscribe URL is unset.
- Every generated email is validated before it can be sent; failures are
  regenerated up to a limit, then abandoned.
- Bodies are NEVER logged at INFO. Only lead id, bucket, subject and message id.

Usage:
    python -m leads.outreach_mailer                      # dry run, writes previews
    python -m leads.outreach_mailer --bucket BIM --limit 10
    python -m leads.outreach_mailer --send               # actually sends
"""

import argparse
import logging
import os
import random
import re
import smtplib
import sys
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional, Tuple

from pymongo import MongoClient

try:
    from .outreach_config import (
        BUCKETS, PITCH_PLACEHOLDER, PREVIEW_DIR, SEND_DAILY_CAP,
        SEND_HOURLY_CAP, SEND_MAX_SPACING_SECONDS, SEND_MIN_SPACING_SECONDS,
        SEND_TRANSPORT, SENDER_EMAIL, SENDER_NAME, SENDER_POSTAL_ADDRESS,
        UNSUBSCRIBE_BASE_URL, buckets_missing_pitch,
    )
    from .outreach_qualification import qualified_leads
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from leads.outreach_config import (
        BUCKETS, PITCH_PLACEHOLDER, PREVIEW_DIR, SEND_DAILY_CAP,
        SEND_HOURLY_CAP, SEND_MAX_SPACING_SECONDS, SEND_MIN_SPACING_SECONDS,
        SEND_TRANSPORT, SENDER_EMAIL, SENDER_NAME, SENDER_POSTAL_ADDRESS,
        UNSUBSCRIBE_BASE_URL, buckets_missing_pitch,
    )
    from leads.outreach_qualification import qualified_leads

logger = logging.getLogger("outreach_mailer")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
# Shared pooled client (TOR-12): was its own MongoClient at import time.
from database import get_client as _get_client
_db = _get_client()["email_automation"]
send_log = _db["outreach_send_logs"]

MAX_SUBJECT_CHARS = 60
MIN_BODY_WORDS = 90
MAX_BODY_WORDS = 130
MAX_GENERATION_ATTEMPTS = 3

# Any of these in generated output means the model left scaffolding behind.
PLACEHOLDER_PATTERNS = [
    r"\[[^\]]{0,80}\]",            # [TODO], [Company], [insert x]
    r"\{\{.*?\}\}",                # {{name}}
    r"<insert[^>]*>", r"\blorem ipsum\b",
    r"\byour company\b",           # unpersonalized filler
    r"\bfirst[_ ]?name\b",
]

# Placeholder markers that are only meaningful in upper case. Matching these
# case-insensitively causes false positives on ordinary prose (and on runs of
# the letter x), so they are checked case-sensitively.
PLACEHOLDER_PATTERNS_CASE_SENSITIVE = [
    r"\bTODO\b", r"\bTBD\b", r"\bXXX+\b",
]

# Claims we cannot substantiate from a LinkedIn headline. Cold email that
# asserts inside knowledge is both dishonest and a deliverability risk.
FABRICATION_PATTERNS = [
    r"\bI (?:noticed|saw|read) (?:that )?your (?:team|company|firm) (?:is|has|recently)\b",
    r"\byour (?:internal|recent|upcoming) (?:project|initiative|roadmap|launch)\b",
    r"\bI (?:was|have been) (?:following|tracking) your\b",
    r"\byour Q[1-4]\b",
    r"\blast (?:quarter|month) you\b",
]

CTA_PATTERNS = [
    r"15[- ]min", r"15 minute", r"fifteen[- ]min", r"quick call", r"brief call",
]


# ============================================================
# PROMPT
# ============================================================

SYSTEM_PROMPT = (
    "You write short, specific B2B cold emails. You never invent facts about "
    "the recipient's company. You never leave placeholder text. You return "
    "only valid JSON."
)

USER_PROMPT = """Write one cold email to this person.

WHAT WE SELL ({bucket_label})
{pitch}

RECIPIENT
  First name: {first_name}
  Exact job title: {title}
  Company: {company}
  Industry: {industry}
  Country: {country}

HARD REQUIREMENTS
- Subject line: under {max_subject} characters, specific, no clickbait, no "Re:".
- Body: between {min_words} and {max_words} words.
- Address them by first name exactly as given: "{first_name}".
- Include exactly ONE relevance hook tied to their ROLE or INDUSTRY as stated
  above. Do not invent anything else about their company.
- Exactly one call to action: a 15-minute call.
- Do NOT claim you have seen their internal work, projects, roadmap, results,
  or recent announcements. You know only their title, company and industry.
- Do NOT leave any placeholder or bracketed text.
- Plain prose. No markdown, no bullet lists, no signature block (one is
  appended automatically).

Return JSON in exactly this shape:
{{"subject": "...", "body": "..."}}"""


def build_prompt(lead: Dict[str, Any], bucket: str) -> str:
    cfg = BUCKETS[bucket]

    def _f(*keys, default="unknown"):
        for k in keys:
            v = lead.get(k)
            if v:
                return str(v).strip()
        return default

    return USER_PROMPT.format(
        bucket_label=cfg["label"],
        pitch=cfg.get("pitch") or PITCH_PLACEHOLDER,
        first_name=_f("first_name", default="there"),
        title=_f("title", "job_title"),
        company=_f("company", "company_name"),
        industry=_f("company_industry", "industry"),
        country=_f("country", "location"),
        max_subject=MAX_SUBJECT_CHARS,
        min_words=MIN_BODY_WORDS,
        max_words=MAX_BODY_WORDS,
    )


# ============================================================
# VALIDATION
# ============================================================

def validate_email(subject: str, body: str, lead: Dict[str, Any]) -> List[str]:
    """Return a list of problems. Empty list means the email is sendable."""
    problems: List[str] = []

    if not subject or not subject.strip():
        problems.append("empty subject")
    elif len(subject) > MAX_SUBJECT_CHARS:
        problems.append(f"subject too long ({len(subject)} > {MAX_SUBJECT_CHARS})")

    if not body or not body.strip():
        problems.append("empty body")
        return problems

    words = len(body.split())
    if words < MIN_BODY_WORDS:
        problems.append(f"body too short ({words} < {MIN_BODY_WORDS} words)")
    elif words > MAX_BODY_WORDS:
        problems.append(f"body too long ({words} > {MAX_BODY_WORDS} words)")

    combined = f"{subject}\n{body}"

    placeholder_hit = None
    for pattern in PLACEHOLDER_PATTERNS:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            placeholder_hit = match.group()
            break
    if placeholder_hit is None:
        for pattern in PLACEHOLDER_PATTERNS_CASE_SENSITIVE:
            match = re.search(pattern, combined)
            if match:
                placeholder_hit = match.group()
                break
    if placeholder_hit is not None:
        problems.append(f"placeholder text: {placeholder_hit[:40]!r}")

    for pattern in FABRICATION_PATTERNS:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            problems.append(f"unsupportable claim: {match.group()[:50]!r}")
            break

    if not any(re.search(p, combined, re.IGNORECASE) for p in CTA_PATTERNS):
        problems.append("no 15-minute call CTA found")

    first_name = (lead.get("first_name") or "").strip()
    if first_name and first_name.lower() not in body.lower():
        problems.append(f"recipient first name {first_name!r} missing from body")

    return problems


# ============================================================
# GENERATION
# ============================================================

def generate_email(lead: Dict[str, Any], bucket: str
                   ) -> Tuple[Optional[str], Optional[str], List[str]]:
    """
    Generate and validate an email, regenerating on validation failure.
    Returns (subject, body, problems). On success problems is empty.
    """
    from leads.bedrock_client import converse_json_object

    lead_id = str(lead.get("_id", "?"))
    last_problems: List[str] = ["not attempted"]

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        try:
            # role="smart" — email copy is the one place worth the better model.
            data = converse_json_object(
                role="smart",
                system=SYSTEM_PROMPT,
                user=build_prompt(lead, bucket),
                max_tokens=800,
                temperature=0.7,
            )
        except Exception as e:
            logger.warning("lead=%s generation attempt %d failed: %s",
                           lead_id, attempt, e)
            last_problems = [f"generation error: {e}"]
            continue

        if not data:
            last_problems = ["unparseable model output"]
            continue

        subject = str(data.get("subject") or "").strip()
        body = str(data.get("body") or "").strip()

        problems = validate_email(subject, body, lead)
        if not problems:
            logger.info("lead=%s email generated attempt=%d subject=%r",
                        lead_id, attempt, subject)
            return subject, body, []

        # Body deliberately not logged, even on failure.
        logger.info("lead=%s attempt %d rejected: %s",
                    lead_id, attempt, "; ".join(problems))
        last_problems = problems

    return None, None, last_problems


# ============================================================
# ASSEMBLY
# ============================================================

def unsubscribe_url(email: str) -> str:
    from urllib.parse import quote
    base = UNSUBSCRIBE_BASE_URL.rstrip("/")
    return f"{base}?email={quote(email)}"


def build_footer(email: str) -> str:
    """CAN-SPAM / GDPR footer: opt-out plus physical postal address."""
    return (
        f"\n\n---\n"
        f"{SENDER_NAME}\n"
        f"{SENDER_POSTAL_ADDRESS}\n\n"
        f"Don't want to hear from me again? Unsubscribe: {unsubscribe_url(email)}\n"
    )


def build_message(lead: Dict[str, Any], subject: str, body: str) -> MIMEMultipart:
    """Multipart/alternative with a plain-text part and an HTML part."""
    to_email = lead["email"].strip().lower()
    footer = build_footer(to_email)

    text_part = body + footer

    html_body = "".join(f"<p>{line}</p>"
                        for line in body.split("\n") if line.strip())
    html_part = (
        f"<html><body style=\"font-family:Arial,sans-serif;font-size:14px\">"
        f"{html_body}"
        f"<hr><p style=\"font-size:12px;color:#666\">"
        f"{SENDER_NAME}<br>{SENDER_POSTAL_ADDRESS}<br><br>"
        f"<a href=\"{unsubscribe_url(to_email)}\">Unsubscribe</a>"
        f"</p></body></html>"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>" if SENDER_NAME else SENDER_EMAIL
    msg["To"] = to_email
    msg["List-Unsubscribe"] = f"<{unsubscribe_url(to_email)}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.attach(MIMEText(text_part, "plain", "utf-8"))
    msg.attach(MIMEText(html_part, "html", "utf-8"))
    return msg


# ============================================================
# SEND CAPS
# ============================================================

def sends_since(delta: timedelta) -> int:
    return send_log.count_documents({"sent_at": {"$gte": datetime.utcnow() - delta}})


def cap_status() -> Dict[str, Any]:
    day = sends_since(timedelta(days=1))
    hour = sends_since(timedelta(hours=1))
    return {
        "sent_today": day, "daily_cap": SEND_DAILY_CAP,
        "sent_this_hour": hour, "hourly_cap": SEND_HOURLY_CAP,
        "daily_remaining": max(0, SEND_DAILY_CAP - day),
        "hourly_remaining": max(0, SEND_HOURLY_CAP - hour),
    }


def _facade_send(**kwargs):
    """Thin indirection so tests can patch the facade at this module's level."""
    from messaging import send as _send
    return _send(**kwargs)


def cap_blocked() -> Optional[str]:
    status = cap_status()
    if status["daily_remaining"] <= 0:
        return f"daily cap reached ({status['sent_today']}/{SEND_DAILY_CAP})"
    if status["hourly_remaining"] <= 0:
        return f"hourly cap reached ({status['sent_this_hour']}/{SEND_HOURLY_CAP})"
    return None


# ============================================================
# TRANSPORTS
# ============================================================

def send_via_ses(msg: MIMEMultipart) -> str:
    import boto3
    client = boto3.client("ses", region_name=os.getenv("AWS_REGION", "us-east-1"))
    response = client.send_raw_email(
        Source=msg["From"],
        Destinations=[msg["To"]],
        RawMessage={"Data": msg.as_string()},
    )
    return response["MessageId"]


def send_via_smtp(msg: MIMEMultipart) -> str:
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    if not host:
        raise RuntimeError("SMTP_HOST not configured")

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        if user:
            server.login(user, password)
        server.send_message(msg)
    return msg.get("Message-ID") or f"smtp-{datetime.utcnow().timestamp()}"


def dispatch(msg: MIMEMultipart) -> str:
    if SEND_TRANSPORT == "ses":
        return send_via_ses(msg)
    if SEND_TRANSPORT == "smtp":
        return send_via_smtp(msg)
    raise RuntimeError(f"unknown transport {SEND_TRANSPORT!r}")


# ============================================================
# SUPPRESSION HOOKS
# ============================================================

def record_bounce(email: str, campaign_id: Optional[str] = None) -> None:
    """Add a bounced address to the shared suppression list."""
    _suppress(email, "bounced", campaign_id)


def record_unsubscribe(email: str, campaign_id: Optional[str] = None) -> None:
    """Add an unsubscribed address to the shared suppression list."""
    _suppress(email, "unsubscribed", campaign_id)


def _suppress(email: str, reason: str, campaign_id: Optional[str]) -> None:
    from leads.outreach_qualification import _get_suppression_manager
    try:
        _get_suppression_manager().add(email, reason, source_campaign_id=campaign_id)
        logger.info("suppressed %s reason=%s", email.lower().strip(), reason)
    except Exception as e:
        logger.error("failed to suppress %s: %s", email, e)


# ============================================================
# PREVIEW
# ============================================================

def write_preview(lead: Dict[str, Any], bucket: str,
                  subject: str, body: str) -> str:
    directory = os.path.join(PREVIEW_DIR, bucket)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{lead.get('_id', 'unknown')}.txt")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"To:      {lead.get('email')}\n")
        fh.write(f"Bucket:  {bucket}\n")
        fh.write(f"Lead:    {lead.get('_id')}\n")
        fh.write(f"Name:    {lead.get('first_name')} {lead.get('last_name') or ''}\n")
        fh.write(f"Title:   {lead.get('title')}\n")
        fh.write(f"Company: {lead.get('company') or lead.get('company_name')}\n")
        fh.write(f"\nSubject: {subject}\n")
        fh.write(f"{'-' * 60}\n")
        fh.write(body)
        fh.write(build_footer(lead.get("email", "")))
    return path


# ============================================================
# PRE-FLIGHT
# ============================================================

def preflight(send: bool) -> List[str]:
    """Reasons sending must not proceed. Empty list means clear to send."""
    if not send:
        return []

    blockers = []
    missing = buckets_missing_pitch()
    if missing:
        blockers.append(
            f"pitch copy is still a placeholder for: {', '.join(missing)}")
    if not SENDER_POSTAL_ADDRESS.strip():
        blockers.append("OUTREACH_SENDER_POSTAL_ADDRESS unset (required by CAN-SPAM)")
    if not SENDER_EMAIL.strip():
        blockers.append("OUTREACH_SENDER_EMAIL unset")
    if not UNSUBSCRIBE_BASE_URL.strip():
        blockers.append("OUTREACH_UNSUBSCRIBE_URL unset (unsubscribe must work)")
    return blockers


# ============================================================
# MAIN RUN
# ============================================================

def run(send: bool = False, bucket: Optional[str] = None,
        limit: Optional[int] = None) -> Dict[str, int]:

    stats = {"considered": 0, "generated": 0, "failed_validation": 0,
             "previewed": 0, "sent": 0, "send_errors": 0, "cap_stopped": 0}

    blockers = preflight(send)
    if blockers:
        for b in blockers:
            logger.error("SEND BLOCKED: %s", b)
        logger.error("Refusing to send. Fix the above, or run without --send.")
        return stats

    leads = qualified_leads(bucket=bucket, limit=limit)
    logger.info("qualified leads: %d", len(leads))

    for lead in leads:
        stats["considered"] += 1
        lead_bucket = (lead.get("outreach_bucket") or "").upper()
        lead_id = str(lead.get("_id"))

        if send:
            blocked = cap_blocked()
            if blocked:
                logger.warning("stopping: %s", blocked)
                stats["cap_stopped"] += 1
                break

        subject, body, problems = generate_email(lead, lead_bucket)
        if not subject:
            stats["failed_validation"] += 1
            logger.warning("lead=%s abandoned after %d attempts: %s",
                           lead_id, MAX_GENERATION_ATTEMPTS, "; ".join(problems))
            continue
        stats["generated"] += 1

        if not send:
            path = write_preview(lead, lead_bucket, subject, body)
            stats["previewed"] += 1
            logger.info("lead=%s bucket=%s preview=%s", lead_id, lead_bucket, path)
            continue

        # Every send goes through the shared facade (TOR-06): one suppression
        # list, one budget spanning all thirteen send paths, one log. The
        # module-local cap_blocked() above is now a fast pre-check only — the
        # facade is what actually enforces, because it can see the panel and
        # campaign senders' volume too, which cap_blocked() never could.
        result = _facade_send(
            to_email=lead["email"],
            subject=subject,
            message=build_message(lead, subject, body),
            transport=dispatch,
            identity=SENDER_EMAIL,
            channel="cold_outreach",
            metadata={"lead_id": lead_id, "bucket": lead_bucket,
                      "transport": SEND_TRANSPORT},
        )
        if result.delivered:
            # Keep writing outreach_send_logs as well: it is this module's
            # historical record and cap_status()/the ops reports still read it.
            send_log.insert_one({
                "sent_at": datetime.utcnow(),
                "lead_id": lead_id,
                "email": lead["email"].lower().strip(),
                "bucket": lead_bucket,
                "subject": subject,
                "message_id": result.provider_message_id,
                "transport": SEND_TRANSPORT,
            })
            stats["sent"] += 1
            logger.info("lead=%s bucket=%s subject=%r message_id=%s SENT",
                        lead_id, lead_bucket, subject, result.provider_message_id)
        elif result.category in ("budget", "disabled", "config"):
            # A global stop, not a per-lead problem — everything after this
            # would be refused too, so stop rather than burn the queue.
            logger.warning("stopping: %s", result.reason)
            stats["cap_stopped"] += 1
            break
        elif result.category == "suppressed":
            stats.setdefault("suppressed", 0)
            stats["suppressed"] += 1
            logger.info("lead=%s skipped: %s", lead_id, result.reason)
            continue
        else:
            stats["send_errors"] += 1
            logger.error("lead=%s send failed: %s", lead_id, result.reason)
            continue

        delay = random.uniform(SEND_MIN_SPACING_SECONDS, SEND_MAX_SPACING_SECONDS)
        logger.info("pacing %.0fs before next send", delay)
        time.sleep(delay)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and send cold outreach")
    parser.add_argument("--send", action="store_true",
                        help="actually send; without this, previews are written")
    parser.add_argument("--dry-run", action="store_true",
                        help="explicit dry run (the default behaviour)")
    parser.add_argument("--bucket", choices=sorted(BUCKETS.keys()))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.send and args.dry_run:
        logger.error("--send and --dry-run are mutually exclusive")
        return 2

    if not args.send:
        logger.info("DRY RUN — previews only, nothing will be sent")

    stats = run(send=args.send, bucket=args.bucket, limit=args.limit)

    logger.info("=== mailer complete ===")
    for key in sorted(stats):
        logger.info("  %-18s %d", key, stats[key])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
