#!/usr/bin/env python3
"""analyze_incompletes.py

Analyzes recent traffic records to explain high INCOMPLETE rates.

Supports both:
- Newer records (created via backend traffic service): status like "INCOMPLETE" and datetime `createdAt`
- Legacy fallback records (created in backend/routers/traffic.py legacy path): status like "incomplete" and string `timestamp`

By default it queries the last 2 hours, but you can override via CLI args.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId


load_dotenv()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(s: str) -> datetime:
    """Parse an ISO-ish datetime string into UTC timezone-aware datetime."""
    # Accept formats like 2026-02-17T14:03:00Z or without Z
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_status(raw: Any) -> str:
    if raw is None:
        return "UNKNOWN"
    if isinstance(raw, str):
        return raw.strip().upper()
    return str(raw).strip().upper()


def _has_value(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    return True


def _safe_bool(v: Any) -> bool:
    return bool(v)


def _get_created_dt(rec: Dict[str, Any]) -> Optional[datetime]:
    """Best-effort extract a timestamp for sorting/printing."""
    created_at = rec.get("createdAt")
    if isinstance(created_at, datetime):
        if created_at.tzinfo is None:
            return created_at.replace(tzinfo=timezone.utc)
        return created_at.astimezone(timezone.utc)
    if isinstance(created_at, str) and created_at:
        try:
            return _parse_dt(created_at)
        except Exception:
            return None

    ts = rec.get("timestamp")
    if isinstance(ts, str) and ts:
        try:
            return _parse_dt(ts)
        except Exception:
            return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    return None


@dataclass(frozen=True)
class IncompleteClassification:
    kind: str
    detail: str


def classify_incomplete(rec: Dict[str, Any]) -> IncompleteClassification:
    """Heuristic classification of *why* a record is still INCOMPLETE."""
    assigned_survey = _has_value(rec.get("assignedSurveyId"))
    redirect_url = _has_value(rec.get("redirectUrl") or rec.get("redirect_url"))

    failure_reason = rec.get("allocationFailureReason")
    if isinstance(failure_reason, str) and failure_reason.strip():
        return IncompleteClassification("allocation_failed_or_blocked", failure_reason.strip())

    # Attempt history, if present
    attempts = rec.get("allocationAttempts")
    if isinstance(attempts, list) and attempts:
        last = attempts[-1] if isinstance(attempts[-1], dict) else None
        if last and isinstance(last.get("failure_reason"), str) and last.get("failure_reason").strip():
            return IncompleteClassification("allocation_failed_or_blocked", last["failure_reason"].strip())

    if not assigned_survey and not redirect_url:
        return IncompleteClassification(
            "allocation_failed_or_blocked",
            "No assignedSurveyId and no redirectUrl (allocation failed, blocked, or not attempted)",
        )

    if assigned_survey and redirect_url:
        return IncompleteClassification(
            "allocated_but_no_callback",
            "Survey allocated and redirectUrl present, but no completion/terminate callback updated status",
        )

    if assigned_survey and not redirect_url:
        return IncompleteClassification(
            "allocated_but_missing_redirect",
            "assignedSurveyId present but redirectUrl missing (assignment persisted without link)",
        )

    if redirect_url and not assigned_survey:
        return IncompleteClassification(
            "redirect_without_surveyid",
            "redirectUrl present but assignedSurveyId missing (data consistency issue)",
        )

    return IncompleteClassification("unknown", "Unclassified")


def _connect(uri: str) -> MongoClient:
    return MongoClient(uri, serverSelectionTimeoutMS=5000)


def _build_query_since(since: datetime) -> Dict[str, Any]:
    """Query by ObjectId timestamp so it works for both legacy + newer records."""
    oid_since = ObjectId.from_datetime(since)
    return {"_id": {"$gte": oid_since}}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze INCOMPLETE traffic records")
    parser.add_argument("--uri", default=os.getenv("MONGO_URI", "mongodb://localhost:27017/"), help="MongoDB URI (defaults to MONGO_URI)")
    parser.add_argument("--db", default="traffic_flow_db", help="Database name")
    parser.add_argument("--collection", default="url_parameters", help="Collection name")
    parser.add_argument("--hours", type=float, default=2.0, help="Lookback window in hours (ignored if --since is provided)")
    parser.add_argument("--since", default=None, help="UTC ISO datetime (e.g. 2026-02-17T14:00:00Z)")
    parser.add_argument("--until", default=None, help="UTC ISO datetime (optional)")
    parser.add_argument("--vendor", default=None, help="Filter by vendorId")
    parser.add_argument("--country", default=None, help="Filter by countryCode")
    args = parser.parse_args(argv)

    until = _parse_dt(args.until) if args.until else _utcnow()
    since = _parse_dt(args.since) if args.since else (until - timedelta(hours=float(args.hours)))

    print(f"🔍 Analyzing traffic since {since.isoformat()} (until {until.isoformat()})")
    print(f"   DB: {args.db}.{args.collection}")
    print(f"   URI: {args.uri.split('@')[-1]}")

    client = _connect(args.uri)
    try:
        coll = client[args.db][args.collection]
        query: Dict[str, Any] = _build_query_since(since)
        if args.vendor is not None:
            query["vendorId"] = args.vendor
        if args.country is not None:
            query["countryCode"] = args.country

        # Apply until bound in-memory (ObjectId-only query is easiest cross-schema)
        records = list(coll.find(query))
        if records:
            bounded = []
            for r in records:
                dt = _get_created_dt(r)
                if dt is None:
                    bounded.append(r)
                    continue
                if since <= dt <= until:
                    bounded.append(r)
            records = bounded

        print(f"\n📊 Total records in window: {len(records)}")
        if not records:
            print("⚠️  No traffic found in the selected window.")
            print("    If your traffic is in a remote DB, pass --uri or set MONGO_URI in .env")
            return 0

        # Status breakdown
        statuses = [_normalize_status(r.get("status")) for r in records]
        status_counts = Counter(statuses)
        print("\n📋 Status Breakdown:")
        total = len(records)
        for status, count in status_counts.most_common():
            print(f"  {status:25} {count:6} ({(count/total)*100:5.1f}%)")

        # INCOMPLETE bucket (handle both cases)
        incomplete_records = [r for r in records if _normalize_status(r.get("status")) == "INCOMPLETE"]
        print(f"\n{'='*78}")
        print(f"\n🔴 INCOMPLETE Analysis: {len(incomplete_records)} records")

        if not incomplete_records:
            return 0

        assigned = sum(1 for r in incomplete_records if _has_value(r.get("assignedSurveyId")))
        redirect = sum(1 for r in incomplete_records if _has_value(r.get("redirectUrl") or r.get("redirect_url")))
        print("\n📌 Key Fields Presence:")
        print(f"  Has assignedSurveyId:  {assigned:6} ({(assigned/len(incomplete_records))*100:5.1f}%)")
        print(f"  Has redirectUrl:       {redirect:6} ({(redirect/len(incomplete_records))*100:5.1f}%)")

        # Provider breakdown (best effort)
        source_counts = Counter([(r.get("surveySource") or "UNKNOWN") for r in incomplete_records])
        print("\n📌 surveySource Breakdown:")
        for src, count in source_counts.most_common(5):
            print(f"  {str(src):12} {count:6} ({(count/len(incomplete_records))*100:5.1f}%)")

        # Heuristic classification
        classifications = [classify_incomplete(r) for r in incomplete_records]
        kind_counts = Counter([c.kind for c in classifications])
        print("\n📌 INCOMPLETE Type Breakdown:")
        for kind, count in kind_counts.most_common():
            print(f"  {kind:28} {count:6} ({(count/len(incomplete_records))*100:5.1f}%)")

        # Failure reason breakdown (only meaningful if present)
        failure_reasons = []
        for r in incomplete_records:
            fr = r.get("allocationFailureReason")
            if isinstance(fr, str) and fr.strip():
                failure_reasons.append(fr.strip())
        if failure_reasons:
            fr_counts = Counter(failure_reasons)
            print("\n📌 allocationFailureReason Breakdown (top 10):")
            for reason, count in fr_counts.most_common(10):
                print(f"  {reason[:80]:80} {count:6}")

        # Vendor/country
        vendor_counts = Counter([r.get("vendorId", "UNKNOWN") for r in incomplete_records])
        country_counts = Counter([r.get("countryCode", "UNKNOWN") for r in incomplete_records])
        print("\n📌 Top Vendors:")
        for vendor_id, count in vendor_counts.most_common(5):
            print(f"  {str(vendor_id):12} {count:6} ({(count/len(incomplete_records))*100:5.1f}%)")
        print("\n📌 Top Countries:")
        for country, count in country_counts.most_common(5):
            print(f"  {str(country):12} {count:6} ({(count/len(incomplete_records))*100:5.1f}%)")

        # Samples
        print("\n📌 Sample INCOMPLETE Records (most recent 5):")
        def _sort_key(r: Dict[str, Any]) -> datetime:
            return _get_created_dt(r) or datetime.min.replace(tzinfo=timezone.utc)

        recent = sorted(incomplete_records, key=_sort_key, reverse=True)[:5]
        for idx, rec in enumerate(recent, 1):
            rec_id = str(rec.get("_id"))
            vendor_id = rec.get("vendorId", "N/A")
            country = rec.get("countryCode", "N/A")
            status = _normalize_status(rec.get("status"))
            survey_id = rec.get("assignedSurveyId") or "—"
            created = _get_created_dt(rec)
            created_s = created.isoformat() if created else str(rec.get("createdAt") or rec.get("timestamp") or "—")
            classification = classify_incomplete(rec)
            print(f"\n  {idx}. id={rec_id}")
            print(f"     status={status} vendor={vendor_id} country={country} survey={survey_id}")
            print(f"     created={created_s}")
            print(f"     redirectUrl={_safe_bool(rec.get('redirectUrl') or rec.get('redirect_url'))} outUrl={_safe_bool(rec.get('outUrl') or rec.get('out_url'))}")
            print(f"     type={classification.kind} detail={classification.detail}")

        print(f"\n{'='*78}")
        print("\n💡 What this usually means:")
        top_kind, top_count = kind_counts.most_common(1)[0]
        if top_kind == "allocation_failed_or_blocked":
            print("   - Most INCOMPLETE records never got a survey link (allocation failed/blocked).")
            print("   - Common causes in your code: invalid/missing client IP, WebView block, CPX entry-guard duplicate/fraud block, CPX no-inventory, CINT config missing, or CINT no surveys for country.")
        elif top_kind == "allocated_but_no_callback":
            print("   - Surveys are being allocated, but your status callbacks are not updating the record.")
            print("   - Most commonly: respondents abandon before completion, provider callback URLs misconfigured, adblock/network blocks the redirect/callback, or callback handler errors.")
        else:
            print("   - Mixed causes. Use the type breakdown + samples to pinpoint which path dominates.")

        return 0
    finally:
        try:
            client.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
