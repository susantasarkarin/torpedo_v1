"""
Panelist lead promotion — move parsing-page email captures into `panelists`.

The "Panelist Lead" tab in /admin/panel-admin/panelists reads
traffic_flow_db.url_parameters: emails captured from survey traffic. The
invite senders in panel_email_service read campaign_platform.panelists. Those
are different collections, so **none of the parsing-page leads were ever
mailed** — only CSV/link imports, which land in `panelists` directly.

This service closes that gap by upserting deduplicated traffic leads into
`panelists` with source="traffic_lead", after which they flow through exactly
the same pipeline as an uploaded CSV row: suppression checks, the
PANEL_INVITE_MIN_GAP_DAYS cooldown, the SES budget, and the funnel report.

Upserts use $setOnInsert keyed on email, so:
  - a lead already present from a CSV upload is left completely untouched
    (its country/name from the CSV wins, and its invite history is preserved)
  - re-running is a no-op for anything already promoted

Runs daily via the `promote_panelist_leads` Celery task, just before the
registration sync and invite cron.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from pymongo import MongoClient, UpdateOne
from pymongo.errors import BulkWriteError

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
_client = MongoClient(MONGO_URI)

panelists_collection = _client["campaign_platform"]["panelists"]
traffic_collection = _client["traffic_flow_db"]["url_parameters"]

_BATCH_SIZE = 5000

# A traffic row's country is an ISO-2 code (US, IN); `panelists.country` from
# CSV uploads is usually a full name. Map the codes we actually see so the
# country filter and the by-country funnel don't split one country in two.
_COUNTRY_NAMES = {
    "US": "United States", "IN": "India", "GB": "United Kingdom",
    "AU": "Australia", "CA": "Canada", "DE": "Germany", "FR": "France",
    "SG": "Singapore", "AE": "UAE", "NZ": "New Zealand", "ZA": "South Africa",
    "IE": "Ireland", "NL": "Netherlands", "ES": "Spain", "IT": "Italy",
    "BR": "Brazil", "MX": "Mexico", "JP": "Japan", "PH": "Philippines",
}


def _country_label(code: str) -> str:
    code = (code or "").strip().upper()
    if not code or code == "XX":
        return ""
    return _COUNTRY_NAMES.get(code, code)


def _lead_pipeline(since: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Distinct traffic leads with an email, newest record per address."""
    match: Dict[str, Any] = {
        "email": {"$exists": True, "$type": "string", "$ne": ""},
    }
    if since:
        match["createdAt"] = {"$gte": since}

    return [
        {"$match": match},
        {"$addFields": {
            "normalizedEmail": {"$toLower": {"$trim": {"input": "$email"}}},
            "normalizedCountryCode": {
                "$toUpper": {"$trim": {"input": {"$ifNull": ["$countryCode", ""]}}}
            },
        }},
        {"$match": {"normalizedEmail": {"$regex": r"^[^@\s]+@[^@\s]+\.[^@\s]+$"}}},
        {"$sort": {"createdAt": -1, "_id": -1}},
        {"$group": {
            "_id": "$normalizedEmail",
            "countryCode": {"$first": "$normalizedCountryCode"},
            "createdAt": {"$first": "$createdAt"},
        }},
    ]


def promote_traffic_leads_to_panelists(
    since: Optional[datetime] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Upsert deduplicated parsing-page leads into `panelists`.

    Args:
        since: only consider traffic rows created at/after this time. Omit for
            a full backfill (the first run); the daily task passes a lookback
            window so the aggregation stays cheap.
        dry_run: count what would be inserted without writing.

    Returns a summary dict: scanned / inserted / already_present.
    """
    started = datetime.utcnow()
    now = started

    cursor = traffic_collection.aggregate(_lead_pipeline(since), allowDiskUse=True)

    scanned = 0
    inserted = 0
    pending: List[Dict[str, Any]] = []

    def _flush() -> None:
        """Upsert one batch. $setOnInsert means existing panelists are never
        overwritten — a CSV-sourced record keeps its own name/country."""
        nonlocal inserted, pending
        if not pending or dry_run:
            pending = []
            return
        ops = [
            UpdateOne({"email": doc["email"]}, {"$setOnInsert": doc}, upsert=True)
            for doc in pending
        ]
        try:
            res = panelists_collection.bulk_write(ops, ordered=False)
            inserted += res.upserted_count
        except BulkWriteError as e:
            details = e.details or {}
            inserted += int(details.get("nUpserted", 0))
            for err in (details.get("writeErrors") or [])[:3]:
                logger.warning(f"[lead-promotion] bulk write error: {err.get('errmsg')}")
        pending = []

    try:
        for row in cursor:
            email = row.get("_id")
            if not email:
                continue
            scanned += 1
            pending.append({
                "email": email,
                "first_name": "",
                "last_name": "",
                "country": _country_label(row.get("countryCode", "")),
                "language": "English",
                "status": "active",
                "rewards_balance": 0.0,
                "email_verified": False,
                "double_opt_in_completed": False,
                "source": "traffic_lead",
                "lead_captured_at": row.get("createdAt"),
                "created_at": now,
                "updated_at": now,
            })
            if len(pending) >= _BATCH_SIZE:
                _flush()
        _flush()
    finally:
        cursor.close()

    summary = {
        "scanned": scanned,
        "inserted": inserted,
        "already_present": max(0, scanned - inserted),
        "dry_run": dry_run,
        "since": since.isoformat() if since else None,
        "duration_seconds": round((datetime.utcnow() - started).total_seconds(), 1),
    }
    logger.info(
        f"[lead-promotion] scanned={summary['scanned']} inserted={summary['inserted']} "
        f"already_present={summary['already_present']} dry_run={dry_run} "
        f"took={summary['duration_seconds']}s"
    )
    return summary


def count_unpromoted_leads(sample_limit: int = 50000) -> Dict[str, Any]:
    """How many distinct traffic-lead emails are not yet in `panelists`.

    Checked against a bounded sample of the most recent leads: an exact figure
    would need an $in over every captured address, which is the kind of
    full-collection query that has previously OOM-killed this backend.
    """
    pipeline = _lead_pipeline() + [
        {"$sort": {"createdAt": -1}},
        {"$limit": sample_limit},
    ]
    cursor = traffic_collection.aggregate(pipeline, allowDiskUse=True)

    sampled = 0
    missing = 0
    chunk: List[str] = []

    def _drain() -> None:
        nonlocal missing, chunk
        if not chunk:
            return
        present = {
            d["email"]
            for d in panelists_collection.find({"email": {"$in": chunk}}, {"email": 1})
        }
        missing += len(chunk) - len(present)
        chunk = []

    try:
        for row in cursor:
            email = row.get("_id")
            if not email:
                continue
            sampled += 1
            chunk.append(email)
            if len(chunk) >= 2000:
                _drain()
        _drain()
    finally:
        cursor.close()

    return {
        "sampled": sampled,
        "not_yet_promoted": missing,
        "sample_limit": sample_limit,
        "sample_is_complete": sampled < sample_limit,
    }
