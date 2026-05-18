"""
email_classifier.py — Task 1: Email Classification & Data Extraction
=====================================================================

Reads unprocessed emails from email_sync.emails, submits them to
the Anthropic Batch API (claude-opus-4-7) for classification and
structured data extraction, then saves results to email_crm_extractions.

Usage:
    python -m backend.email_crm_pipeline.email_classifier
    python -m backend.email_crm_pipeline.email_classifier --since 2024-01-01
    python -m backend.email_crm_pipeline.email_classifier --limit 200 --dry-run
"""

import sys
import os
import json
import logging
import argparse
import time
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId

# Ensure backend/ is importable when run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
from database import get_collection
from email_crm_pipeline.config import (
    ANTHROPIC_API_KEY, CLASSIFIER_MODEL, BATCH_SIZE, BATCH_POLL_INTERVAL,
    CLASSIFIER_MAX_TOKENS, MAX_ITEM_RETRIES, DB_EMAIL_SYNC, COL_EMAILS, DB_CRM,
    COL_EMAIL_EXTRACTIONS, COL_PIPELINE_STATE, PIPELINE_STATE_DOC_ID,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Classification System Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a B2B email CRM data extractor for a Survey Fieldwork market research company.
Analyse the provided email and extract structured data. Return ONLY a single valid JSON object — no markdown, no explanation.

=== CLASSIFICATION RULES ===
- client_rfq    : subject/body contains "RFQ", "request for quotation", "feasibility", "quote",
                  "proposal", "can you provide", "cost for", "pricing for", "methodology"
- finance       : from a bank, payment gateway, accounting system, or financial institution
- vendor        : from a vendor, supplier, freelancer, or panel partner offering services
- promotional   : newsletter, marketing blast, no-reply address, or no action required
- internal      : from a colleague at the same company domain
- client_general: general client communication not matching the above
- unknown       : cannot be classified

=== EXTRACTION RULES ===
- Extract country from: email signature address, company domain TLD (.in=India, .uk=UK, .de=Germany, etc.),
  project geography mentioned, or any location reference in the body. Infer intelligently.
- Treat the SAME company in DIFFERENT countries as SEPARATE account entities
  (e.g. "Kantar India" ≠ "Kantar UK" — different account records).
- For outbound emails (direction="outbound"), set is_outbound_pitch=true.
- If a contact appears with a DIFFERENT company domain than their known email suggests a job change,
  set job_change_signal.detected=true.
- Extract phone numbers and LinkedIn URLs only if explicitly present in the email.
- rfq_status should reflect only what can be inferred from THIS single email thread.

=== OUTPUT SCHEMA ===
{
  "email_id": "<original email _id string>",
  "email_type": "client_rfq|client_general|vendor|finance|promotional|internal|unknown",
  "contact": {
    "name": "<full name or null>",
    "email": "<sender email for inbound; key recipient for outbound>",
    "designation": "<job title from body/signature or null>",
    "company_name": "<company name>",
    "country": "<country or null>",
    "phone": "<phone number or null>",
    "linkedin": "<LinkedIn URL or null>"
  },
  "account": {
    "company_name": "<normalised company name — remove Ltd/Inc/Corp/Pvt suffixes>",
    "country": "<country of this specific office/entity>",
    "is_multi_country": true
  },
  "rfq": {
    "is_rfq": false,
    "rfq_summary": "<one-line research job description or null>",
    "rfq_status": "received|quoted|won|lost|pending|unknown",
    "project_type": "<online survey|focus group|CATI|panel recruitment|IDI|etc. or null>",
    "geography": "<target research country/market or null>",
    "received_date": "<ISO 8601 date string or null>"
  },
  "outbound_unanswered": {
    "is_outbound_pitch": false,
    "response_received": false,
    "days_since_sent": null
  },
  "job_change_signal": {
    "detected": false,
    "old_company": null,
    "new_company": null,
    "notes": null
  },
  "last_communication_date": "<ISO 8601 date string>",
  "one_line_summary": "<one sentence describing what this email is about>"
}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_collections():
    emails_col = get_collection(DB_EMAIL_SYNC, COL_EMAILS)
    extractions_col = get_collection(DB_CRM, COL_EMAIL_EXTRACTIONS)
    state_col = get_collection(DB_CRM, COL_PIPELINE_STATE)
    return emails_col, extractions_col, state_col


def get_unprocessed_emails(
    since_date: Optional[datetime],
    limit: Optional[int],
    emails_col: Any,
) -> list[dict]:
    """
    Return emails not yet processed by this pipeline.
    Excludes system emails (bounces, OOO, auto-replies).
    """
    query: dict[str, Any] = {
        "crm_pipeline_processed": {"$ne": True},
        "email_type": {"$ne": "system"},   # skip bounces/OOO
    }
    if since_date:
        query["timestamp"] = {"$gte": since_date}

    cursor = emails_col.find(query).sort("timestamp", 1)
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)


def _format_email_for_prompt(email: dict) -> str:
    """Build a human-readable email block to send to Claude."""
    from_addr = email.get("from_address", {})
    from_str = f"{from_addr.get('name', '')} <{from_addr.get('email', '')}>"

    to_list = [
        f"{a.get('name', '')} <{a.get('email', '')}>".strip()
        for a in email.get("to_addresses", [])
    ]
    cc_list = [
        f"{a.get('name', '')} <{a.get('email', '')}>".strip()
        for a in email.get("cc_addresses", [])
    ]

    direction = email.get("direction", "inbound")
    ts = email.get("timestamp") or email.get("date", "")
    if isinstance(ts, datetime):
        ts = ts.isoformat()

    body = (email.get("body_plain") or "").strip()
    # Truncate very long bodies to keep tokens reasonable
    if len(body) > 3000:
        body = body[:3000] + "\n[...truncated...]"

    attachments = email.get("attachments") or []
    attachment_names = []
    for item in attachments[:10]:
        if isinstance(item, dict):
            name = item.get("filename") or item.get("name")
            if name:
                attachment_names.append(str(name))

    lines = [
        f"EMAIL_ID: {email['_id']}",
        f"DIRECTION: {direction}",
        f"DATE: {ts}",
        f"FROM: {from_str}",
        f"TO: {', '.join(to_list)}",
    ]
    if cc_list:
        lines.append(f"CC: {', '.join(cc_list)}")
    if attachment_names:
        lines.append(f"ATTACHMENTS: {', '.join(attachment_names)}")
    lines += [
        f"SUBJECT: {email.get('subject', '')}",
        "",
        "BODY:",
        body,
    ]
    return "\n".join(lines)


def build_batch_requests(emails: list[dict]) -> list[dict]:
    """Convert a list of email docs into Anthropic batch request params."""
    requests = []
    for email in emails:
        user_content = _format_email_for_prompt(email)
        requests.append({
            "custom_id": str(email["_id"]),
            "params": {
                "model": CLASSIFIER_MODEL,
                "max_tokens": CLASSIFIER_MAX_TOKENS,
                "system": [
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},  # prompt caching
                    }
                ],
                "messages": [
                    {"role": "user", "content": user_content}
                ],
            },
        })
    return requests


def submit_batch(client: anthropic.Anthropic, requests: list[dict]) -> str:
    """Submit a batch of classification requests. Returns the batch ID."""
    batch = client.beta.messages.batches.create(requests=requests)
    log.info("Submitted batch %s (%d requests)", batch.id, len(requests))
    return batch.id


def poll_batch(client: anthropic.Anthropic, batch_id: str) -> Any:
    """Poll until the batch is no longer in_progress. Returns the final batch object."""
    while True:
        batch = client.beta.messages.batches.retrieve(batch_id)
        status = batch.processing_status
        counts = getattr(batch, "request_counts", None)
        succeeded = getattr(counts, "succeeded", 0) if counts else 0
        errored = getattr(counts, "errored", 0) if counts else 0
        processing = getattr(counts, "processing", 0) if counts else 0
        log.info(
            "Batch %s status=%s  succeeded=%s errored=%s processing=%s",
            batch_id, status,
            succeeded, errored, processing,
        )
        if status != "in_progress":
            return batch
        time.sleep(BATCH_POLL_INTERVAL)


def _parse_json_from_text(text: str) -> Optional[dict]:
    """Extract and parse the first JSON object from a Claude response."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            l for l in lines if not l.strip().startswith("```")
        ).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object boundaries
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                return None
    return None


def _retry_single_email(client: anthropic.Anthropic, email: dict) -> Optional[dict]:
    """Fall back to a regular (non-batch) API call for a failed email."""
    user_content = _format_email_for_prompt(email)
    for attempt in range(1, MAX_ITEM_RETRIES + 2):
        try:
            response = client.messages.create(
                model=CLASSIFIER_MODEL,
                max_tokens=CLASSIFIER_MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            blocks = getattr(response, "content", [])
            first = blocks[0] if blocks else None
            text = getattr(first, "text", "") if first else ""
            parsed = _parse_json_from_text(text)
            if parsed:
                return parsed
        except Exception as exc:
            log.warning(
                "Retry attempt %d failed for email %s: %s",
                attempt,
                email.get("_id"),
                exc,
            )
        time.sleep(1)
    return None


def _extract_text_from_batch_result(result_obj: Any) -> str:
    """Extract text content from Anthropic batch result objects in a tolerant way."""
    try:
        message = result_obj.result.message
        blocks = getattr(message, "content", [])
        if blocks:
            return getattr(blocks[0], "text", "") or ""
    except Exception:
        pass

    try:
        result_dict = result_obj.model_dump() if hasattr(result_obj, "model_dump") else {}
        result_node = result_dict.get("result", {})
        message = result_node.get("message", {})
        content = message.get("content", [])
        if content:
            first = content[0]
            if isinstance(first, dict):
                return first.get("text", "") or ""
    except Exception:
        pass

    return ""


def process_batch_results(
    client: anthropic.Anthropic,
    batch_id: str,
    email_map: dict[str, dict],
    extractions_col: Any,
    emails_col: Any,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Iterate batch results, parse extractions, upsert to email_crm_extractions,
    and mark source emails as processed.

    Returns counts: {saved, failed, retried}.
    """
    counts = {"saved": 0, "failed": 0, "retried": 0}
    processed_email_ids = []

    for result in client.beta.messages.batches.results(batch_id):
        email_id = str(getattr(result, "custom_id", ""))
        email_doc = email_map.get(email_id)

        result_type = ""
        try:
            result_type = getattr(result.result, "type", "")
        except Exception:
            result_type = ""

        if result_type == "succeeded":
            raw_text = _extract_text_from_batch_result(result)
            extraction = _parse_json_from_text(raw_text)
        else:
            log.warning("Batch item %s failed: %s", email_id, result.result)
            extraction = None
            counts["failed"] += 1

            # Retry individually
            if email_doc:
                log.info("Retrying email %s individually…", email_id)
                extraction = _retry_single_email(client, email_doc)
                if extraction:
                    counts["retried"] += 1
                    counts["failed"] -= 1

        if extraction is None:
            continue

        # Attach pipeline metadata
        extraction["_source_email_id"] = email_id
        extraction["_batch_id"] = batch_id
        extraction["_extracted_at"] = datetime.now(timezone.utc)
        extraction["crm_populated"] = False

        if email_doc:
            extraction["_email_direction"] = email_doc.get("direction", "inbound")
            extraction["_email_timestamp"] = email_doc.get("timestamp")
            extraction["_mailbox_id"] = str(email_doc.get("mailbox_id", ""))

        if not dry_run:
            extractions_col.update_one(
                {"_source_email_id": email_id},
                {"$set": extraction},
                upsert=True,
            )
            try:
                processed_email_ids.append(ObjectId(email_id))
            except Exception:
                log.warning("Skipping source email mark for non-ObjectId: %s", email_id)
            counts["saved"] += 1
        else:
            log.info("[DRY-RUN] Would save extraction for %s: %s",
                     email_id, extraction.get("one_line_summary", "?"))
            counts["saved"] += 1

    # Bulk-mark source emails as processed
    if processed_email_ids and not dry_run:
        emails_col.update_many(
            {"_id": {"$in": processed_email_ids}},
            {"$set": {"crm_pipeline_processed": True}},
        )
        log.info("Marked %d emails as crm_pipeline_processed=True", len(processed_email_ids))

    return counts


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_classification(
    since_date: Optional[datetime] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
) -> dict:
    """
    Full classification run:
    1. Fetch unprocessed emails (filtered by since_date if provided)
    2. Split into batches of BATCH_SIZE
    3. For each batch: submit → poll → save results
    4. Return summary counts
    """
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not set in the environment.")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    emails_col, extractions_col, state_col = _get_collections()

    emails = get_unprocessed_emails(since_date, limit, emails_col)
    total = len(emails)
    log.info("Found %d unprocessed emails to classify", total)

    if total == 0:
        return {"total": 0, "saved": 0, "failed": 0, "retried": 0, "batches": 0}

    summary = {"total": total, "saved": 0, "failed": 0, "retried": 0, "batches": 0}

    # Process in chunks of BATCH_SIZE
    for chunk_start in range(0, total, BATCH_SIZE):
        chunk = emails[chunk_start: chunk_start + BATCH_SIZE]
        email_map = {str(e["_id"]): e for e in chunk}

        log.info(
            "Processing batch %d/%d  (emails %d–%d)",
            chunk_start // BATCH_SIZE + 1,
            (total + BATCH_SIZE - 1) // BATCH_SIZE,
            chunk_start + 1,
            min(chunk_start + BATCH_SIZE, total),
        )

        requests = build_batch_requests(chunk)

        if dry_run:
            log.info("[DRY-RUN] Would submit %d requests to Anthropic Batch API", len(requests))
            counts = {"saved": len(chunk), "failed": 0, "retried": 0}
        else:
            batch_id = submit_batch(client, requests)
            # Track active batch in pipeline_state
            state_col.update_one(
                {"_id": PIPELINE_STATE_DOC_ID},
                {
                    "$addToSet": {"active_batch_ids": batch_id},
                    "$set": {"updated_at": datetime.now(timezone.utc)},
                },
                upsert=True,
            )
            poll_batch(client, batch_id)
            counts = process_batch_results(
                client, batch_id, email_map, extractions_col, emails_col
            )
            state_col.update_one(
                {"_id": PIPELINE_STATE_DOC_ID},
                {
                    "$pull": {"active_batch_ids": batch_id},
                    "$set": {"updated_at": datetime.now(timezone.utc)},
                },
                upsert=True,
            )

        summary["saved"] += counts["saved"]
        summary["failed"] += counts["failed"]
        summary["retried"] += counts["retried"]
        summary["batches"] += 1

    log.info(
        "Classification complete. batches=%d saved=%d failed=%d retried=%d",
        summary["batches"], summary["saved"], summary["failed"], summary["retried"],
    )
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Classify emails from email_sync.emails using Claude Batch API"
    )
    parser.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="Only process emails on or after this date (default: all unprocessed)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of emails to process in this run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would happen without writing to MongoDB or calling Anthropic",
    )
    args = parser.parse_args()

    since = None
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)

    result = run_classification(since_date=since, limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
