"""
MODULE 2 — EMAIL EXTRACTION FROM MAIL POOL (CODE/REGEX ONLY — NO AI)
======================================================================
Scans the Gmail mail pool (email_metadata collection) and extracts structured
lead records using regex and code-based parsing ONLY. No LLMs used here.

Extracted fields per email:
- Full name (from display name in From header)
- Email address
- Domain (from email address)
- Company name (derived from domain)
- Any additional metadata available in headers

Records are stored in the 'leads' collection and deduplicated against existing entries.

Celery task: extract_leads_from_mail_pool
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from celery_app import celery_app
from db_pools import get_background_db
from pymongo import MongoClient

logger = logging.getLogger(__name__)

# Canonical ingestion — the ONLY way leads should enter the system
def _ingest_via_canonical(lead_data: Dict[str, Any]) -> Dict[str, Any]:
    """Route a mail-pool lead through canonical ingestion into email_automation.leads_enriched."""
    try:
        from leads.canonical_ingestion import ingest_lead
    except ImportError:
        from backend.leads.canonical_ingestion import ingest_lead

    payload = {
        "email": lead_data.get("email"),
        "first_name": lead_data.get("first_name"),
        "last_name": lead_data.get("last_name"),
        "name": lead_data.get("name"),
        "company": lead_data.get("company"),
        "company_domain": lead_data.get("domain"),
        "subject": lead_data.get("subject"),  # Email subject - passed to enriched collection
        "notes": lead_data.get("notes"),  # Email body - passed as lead notes
    }
    result = ingest_lead(payload, source="gmail", source_detail="mail_pool_extraction") or {}
    return {
        "success": bool(result.get("success")),
        "action": result.get("action"),
        "lead_id": result.get("lead_id"),
        "error": result.get("error"),
    }


def _is_duplicate_in_enriched(email: str) -> bool:
    """Check if a lead with this email already exists in leads_enriched (the canonical collection)."""
    try:
        from leads.canonical_ingestion import leads_enriched
    except ImportError:
        from backend.leads.canonical_ingestion import leads_enriched
    return leads_enriched.count_documents({"email": email}, limit=1) > 0

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  REGEX PATTERNS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Matches: "John Smith <john@example.com>" or "john@example.com"
_FROM_WITH_NAME = re.compile(
    r'^"?([^"<@\n]+?)"?\s*<([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})>',
    re.IGNORECASE,
)
_EMAIL_ONLY = re.compile(
    r'^([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
    re.IGNORECASE,
)
# Bare email anywhere in a string
_EMAIL_ANYWHERE = re.compile(
    r'([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
    re.IGNORECASE,
)

# Own domains — emails FROM these addresses are internal/operational, never leads.
_OWN_DOMAINS = frozenset({
    "cogentixresearch.com",
    "surveyfieldwork.com",
})

# Domains to exclude (transactional, system, no-reply addresses, infra/SaaS notifications).
_EXCLUDED_DOMAINS = frozenset({
    # Personal freemail
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "live.com", "icloud.com", "me.com", "aol.com", "protonmail.com", "zoho.com",
    # Transactional / bounce infrastructure
    "noreply.com", "mailer.com", "bounce.com", "amazonses.com", "sendgrid.net",
    "mailchimp.com", "mandrillapp.com", "postmarkapp.com", "sparkpostmail.com",
    "mailgun.org", "mg.com", "constantcontact.com", "hubspotemail.net",
    # Cloud/infra vendors — not B2B prospects
    "digitalocean.com", "linode.com", "vultr.com",
    # SaaS platforms sending automated notifications
    "salesforce.com", "force.com",
    "google.com", "googlegroups.com",
    "quora.com",
    # Zoho sub-service senders (not human contacts)
    "zohocrm.in", "zohocorp.com", "zoho-books.in",
})

# Prefixes that indicate system/transactional senders (NOT real people).
# NOTE: keep this list narrow — for a B2B platform, "sales", "info", "contact",
# "hello" etc. are real humans we want as leads.
_EXCLUDED_EMAIL_PREFIXES = frozenset({
    "noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon",
    "postmaster", "bounce", "notifications", "newsletter",
    "digest", "unsubscribe", "autoresponder",
    # "alerts" removed — too broad; some B2B tools use alerts@company.com for real contacts
})

# Common TLD + SLD suffixes to strip when deriving company name from domain
_DOMAIN_STRIP_SUFFIXES = re.compile(
    r'\.(com|co\.uk|org|net|io|ai|tech|app|biz|info|co|ltd|inc|llc|plc)$',
    re.IGNORECASE,
)
# Common sub-domain prefixes to strip
_SUBDOMAIN_STRIP = re.compile(r'^(mail|smtp|email|send|auto|mx|reply)\.')


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  PARSING HELPERS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _parse_from_header(from_header: str) -> Tuple[str, str]:
    """
    Parse a From: header value into (full_name, email_address).
    Returns ("", "") if no valid email found.
    """
    from_header = (from_header or "").strip()

    m = _FROM_WITH_NAME.match(from_header)
    if m:
        name = m.group(1).strip().strip('"').strip("'")
        email = m.group(2).strip().lower()
        return name, email

    m = _EMAIL_ONLY.match(from_header)
    if m:
        email = m.group(1).strip().lower()
        return "", email

    # Last resort: find any email address in the string
    m = _EMAIL_ANYWHERE.search(from_header)
    if m:
        return "", m.group(1).strip().lower()

    return "", ""


def _derive_domain(email: str) -> str:
    """Extract domain from email address."""
    if "@" in email:
        return email.split("@", 1)[1].strip().lower()
    return ""


def _derive_company(domain: str) -> str:
    """
    Derive a human-readable company name from a domain using string ops only.
    e.g. "research-now.com" â†’ "Research Now"
         "ipsos.co.uk"      â†’ "Ipsos"
    """
    if not domain:
        return ""

    # Strip sub-domain prefixes
    d = _SUBDOMAIN_STRIP.sub("", domain)
    # Strip TLD suffixes
    d = _DOMAIN_STRIP_SUFFIXES.sub("", d)
    # Replace separators with spaces
    d = d.replace("-", " ").replace("_", " ").replace(".", " ")
    # Title-case
    return d.strip().title()


def _infer_name_from_email(email: str) -> str:
    """
    Fallback: infer a plausible name from the email local-part.
    e.g. "john.smith@..."  â†’ "John Smith"
         "jsmith@..."      â†’ "J Smith"  (attempt first-initial + last split)
         "john_doe123@..." â†’ "John Doe"
    """
    local = email.split("@")[0] if "@" in email else email
    # Strip trailing digits (john.smith2 â†’ john.smith)
    local = re.sub(r'\d+$', '', local)
    # Replace separators
    parts = re.split(r'[\.\-_\+]', local)
    # Filter empty and pure-digit tokens
    parts = [p for p in parts if p and not p.isdigit()]
    if not parts:
        return ""
    if len(parts) >= 2:
        return " ".join(p.capitalize() for p in parts[:2])
    # Single token: try to split camelCase (e.g. "johnSmith" â†’ ["john","Smith"])
    token = parts[0]
    camel = re.split(r'(?<=[a-z])(?=[A-Z])', token)
    if len(camel) >= 2:
        return " ".join(p.capitalize() for p in camel[:2])
    # Single lowercase token: if len>3, try first-initial + rest (e.g. "jsmith" â†’ "J Smith")
    if len(token) > 3 and token[0].isalpha() and token[1:].isalpha():
        return f"{token[0].upper()} {token[1:].capitalize()}"
    return token.capitalize()


def _is_excluded(email: str, domain: str) -> bool:
    """Return True if this sender should be skipped (transactional, system, generic, own-domain)."""
    # Own-domain emails are internal/operational — not B2B leads
    if domain in _OWN_DOMAINS:
        return True
    if domain in _EXCLUDED_DOMAINS:
        return True
    local = email.split("@")[0].lower() if "@" in email else email.lower()
    # Check prefix — only exact match or starts-with against known transactional prefixes
    if any(local == prefix or local.startswith(prefix) for prefix in _EXCLUDED_EMAIL_PREFIXES):
        return True
    return False


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  EXTRACTION CORE
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def extract_lead_from_email_record(email_record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract a structured lead dict from a single email_metadata document.
    Returns None if the sender is excluded or no valid email found.

    Args:
        email_record: A document from the email_metadata MongoDB collection.
    """
    # Use pre-existing classifier verdict — no new AI call needed.
    # ai_is_sales_lead=False means the email classifier already determined this
    # is not a B2B lead (e.g. automated alert, vendor invoice, bounce).
    if email_record.get("ai_is_sales_lead") is False:
        return None

    # Use direct fields (torpedo_gmail schema: from_email, from_name)
    email_address = (email_record.get("from_email") or "").strip().lower()
    full_name = (email_record.get("from_name") or "").strip()

    # Fallback: parse from legacy/combined header if direct fields absent
    if not email_address:
        from_header = (
            email_record.get("from")
            or email_record.get("sender")
            or email_record.get("headers", {}).get("From", "")
            or ""
        )
        full_name, email_address = _parse_from_header(from_header)
    if not email_address:
        return None

    domain = _derive_domain(email_address)
    if not domain:
        return None

    if _is_excluded(email_address, domain):
        return None

    # Fallback name from email if display name missing
    if not full_name:
        full_name = _infer_name_from_email(email_address)

    company = _derive_company(domain)

    # Split name into first/last (best effort)
    name_parts = full_name.strip().split(" ", 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    # Pull any extra metadata available without AI
    subject = email_record.get("subject", "")
    body = (email_record.get("body_plain") or email_record.get("body") or "").strip()[:2000]  # Cap at 2000 chars
    received_at = email_record.get("timestamp") or email_record.get("date") or email_record.get("received_at") or email_record.get("synced_at") or email_record.get("internalDate")

    return {
        "name": full_name,
        "first_name": first_name,
        "last_name": last_name,
        "email": email_address,
        "domain": domain,
        "company": company,
        "source": "mail_pool",
        "stage": "new",
        "email_status": "pending",
        "track": "cold",
        "enrichment": {"status": "pending"},
        "subject": subject,  # Email subject line
        "notes": body,  # Email body text - store in notes field for lead display
        "metadata": {
            "source_email_id": str(email_record.get("_id", "")),
            "source_subject": subject,
            "source_body": body,
            "received_at": str(received_at) if received_at else None,
        },
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  DEDUPLICATION HELPERS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _is_duplicate(leads_col, email: str) -> bool:
    """Check if a lead with this email already exists in leads_enriched (canonical collection)."""
    return _is_duplicate_in_enriched(email)


def _mark_email_processed(mail_col, email_id) -> None:
    """Mark a mail pool record as having been extracted for lead generation."""
    try:
        from bson import ObjectId
        mail_col.update_one(
            {"_id": ObjectId(str(email_id))},
            {"$set": {"lead_extracted": True, "lead_extracted_at": datetime.utcnow()}},
        )
    except Exception as e:
        logger.warning(f"Could not mark email {email_id} as processed: {e}")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  BATCH EXTRACTION
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_mail_db():
    """Return the torpedo_gmail database where email_metadata lives.
    Uses the shared background DB pool instead of creating a raw MongoClient.
    """
    try:
        # Reuse the shared pool managed by db_pools to avoid connection proliferation
        client = get_background_db().client
        return client["torpedo_gmail"]
    except Exception:
        # Fallback to direct connection if pool is unavailable
        import os
        uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        return MongoClient(uri, serverSelectionTimeoutMS=10000)["torpedo_gmail"]


def extract_leads_from_mail_pool_batch(
    since_hours: int = 24,
    limit: int = 500,
) -> Dict[str, Any]:
    """
    Scan the email_metadata collection for emails received in the last `since_hours` hours,
    extract structured leads using regex/code only, and insert new ones via canonical ingestion.

    Args:
        since_hours: How far back to look in the mail pool.
        limit: Max number of emails to process per run.

    Returns:
        Summary dict with counts and errors.
    """
    mail_col = _get_mail_db()["email_metadata"]

    since = datetime.utcnow() - timedelta(hours=since_hours)

    # Fetch unprocessed INBOUND emails received since the cutoff.
    # Only process inbound emails — outbound (sent) emails are OUR emails,
    # not leads.
    cursor = mail_col.find(
        {
            "lead_extracted": {"$ne": True},
            "direction": "inbound",
            "$or": [
                {"timestamp": {"$gte": since}},
                {"synced_at": {"$gte": since}},
                {"date": {"$gte": since}},
            ],
        },
        limit=limit,
        sort=[("timestamp", -1)],
    )

    inserted = 0
    skipped_excluded = 0
    skipped_duplicate = 0
    errors = 0
    error_details: List[str] = []

    for record in cursor:
        try:
            lead = extract_lead_from_email_record(record)
            if lead is None:
                skipped_excluded += 1
                _mark_email_processed(mail_col, record.get("_id"))  # prevent churn
                continue

            if _is_duplicate_in_enriched(lead["email"]):
                skipped_duplicate += 1
                _mark_email_processed(mail_col, record.get("_id"))
                continue

            ingest_result = _ingest_via_canonical(lead)
            lead_id = ingest_result.get("lead_id")
            action = ingest_result.get("action")
            if lead_id:
                _mark_email_processed(mail_col, record.get("_id"))
                inserted += 1

                logger.info(
                    f"[MailPool] Extracted lead via canonical ingestion: {lead['name']} <{lead['email']}> "
                    f"@ {lead['company']} (lead_id={lead_id})"
                )
            elif ingest_result.get("success") and action == "skipped":
                skipped_duplicate += 1
                _mark_email_processed(mail_col, record.get("_id"))
            else:
                errors += 1
                error_details.append(
                    f"Canonical ingestion failed for {lead['email']} "
                    f"(action={action}, error={ingest_result.get('error')})"
                )
                _mark_email_processed(mail_col, record.get("_id"))

        except Exception as e:
            errors += 1
            msg = f"Error on email {record.get('_id')}: {e}"
            error_details.append(msg)
            logger.error(f"[MailPool] {msg}")

    summary = {
        "inserted": inserted,
        "skipped_excluded": skipped_excluded,
        "skipped_duplicate": skipped_duplicate,
        "errors": errors,
        "error_details": error_details[:10],  # cap to avoid log bloat
        "processed_at": datetime.utcnow().isoformat(),
    }
    logger.info(f"[MailPool] Extraction complete: {summary}")
    return summary


def extract_leads_from_existing_pool(limit: int = 2000) -> Dict[str, Any]:
    """
    One-time backfill: scan ALL existing email_metadata records (not just recent ones)
    and extract leads that have not yet been processed.

    Same logic as the batch extraction but without a time filter.
    """
    mail_col = _get_mail_db()["email_metadata"]

    cursor = mail_col.find(
        {
            "lead_extracted": {"$ne": True},
            # Skip emails that the classifier has already determined are not B2B leads.
            # This avoids processing bounces, invoices, automated alerts etc.
            # ai_is_sales_lead=False is set by the email classifier agent (no new AI call here).
            "ai_is_sales_lead": {"$ne": False},
        },
        limit=limit,
        sort=[("timestamp", -1)],
    )

    inserted = 0
    skipped_excluded = 0
    skipped_duplicate = 0
    errors = 0
    error_details: List[str] = []

    for record in cursor:
        try:
            lead = extract_lead_from_email_record(record)
            if lead is None:
                skipped_excluded += 1
                _mark_email_processed(mail_col, record.get("_id"))  # prevent churn
                continue

            if _is_duplicate_in_enriched(lead["email"]):
                skipped_duplicate += 1
                _mark_email_processed(mail_col, record.get("_id"))
                continue

            ingest_result = _ingest_via_canonical(lead)
            lead_id = ingest_result.get("lead_id")
            action = ingest_result.get("action")
            if lead_id:
                _mark_email_processed(mail_col, record.get("_id"))
                inserted += 1
            elif ingest_result.get("success") and action == "skipped":
                skipped_duplicate += 1
                _mark_email_processed(mail_col, record.get("_id"))
            else:
                errors += 1
                error_details.append(
                    f"Canonical ingestion failed for {lead['email']} "
                    f"(action={action}, error={ingest_result.get('error')})"
                )
                _mark_email_processed(mail_col, record.get("_id"))

        except Exception as e:
            errors += 1
            error_details.append(f"{record.get('_id')}: {e}")
            logger.error(f"[MailPool Backfill] Error: {e}")

    summary = {
        "inserted": inserted,
        "skipped_excluded": skipped_excluded,
        "skipped_duplicate": skipped_duplicate,
        "errors": errors,
        "error_details": error_details[:10],
        "processed_at": datetime.utcnow().isoformat(),
    }
    logger.info(f"[MailPool Backfill] Complete: {summary}")
    return summary


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  CELERY TASKS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@celery_app.task(
    name="backend.sales.mail_pool_extractor.extract_leads_from_mail_pool",
    queue="sales",
    max_retries=1,
    rate_limit="2/h",
)
def extract_leads_from_mail_pool(since_hours: int = 24, limit: int = 500) -> Dict[str, Any]:
    """
    Celery task: extract leads from recent mail pool emails.
    Scheduled hourly by the background job scheduler.
    """
    return extract_leads_from_mail_pool_batch(since_hours=since_hours, limit=limit)


@celery_app.task(
    name="backend.sales.mail_pool_extractor.backfill_leads_from_mail_pool",
    queue="sales",
    max_retries=1,
)
def backfill_leads_from_mail_pool(limit: int = 2000) -> Dict[str, Any]:
    """
    Celery task: one-time backfill of all existing mail pool emails.
    Trigger manually from the API when needed.
    """
    return extract_leads_from_existing_pool(limit=limit)

