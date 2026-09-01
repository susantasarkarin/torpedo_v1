"""
Audit Router — Query logs and outreach event data for monitoring.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from pymongo import MongoClient, DESCENDING
import os

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/audit", tags=["audit"])

MONGO_URI = os.getenv("MONGO_URI", os.getenv("MONGO_URI", "mongodb://localhost:27017"))


def _get_db():
    client = MongoClient(MONGO_URI)
    return client["email_automation"]


@router.get("/logs")
async def get_audit_logs(
    event_type: Optional[str] = None,
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(100, ge=1, le=1000),
):
    """Query audit / decision logs."""
    db = _get_db()
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    query: dict = {"created_at": {"$gte": cutoff}}
    if event_type:
        query["event_type"] = event_type

    logs = list(
        db["audit_logs"]
        .find(query, {"_id": 0})
        .sort("created_at", DESCENDING)
        .limit(limit)
    )
    return {"count": len(logs), "logs": logs}


@router.get("/outreach/sends")
async def get_outreach_sends(
    status: Optional[str] = None,
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(100, ge=1, le=1000),
):
    """Query outreach send records."""
    db = _get_db()
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    query: dict = {"sent_at": {"$gte": cutoff}}
    if status:
        query["status"] = status

    sends = list(
        db["outreach_sends_v2"]
        .find(query, {"_id": 0, "body_html": 0, "body_plain": 0})
        .sort("sent_at", DESCENDING)
        .limit(limit)
    )
    return {"count": len(sends), "sends": sends}


@router.get("/outreach/errors")
async def get_outreach_errors(
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(50, ge=1, le=500),
):
    """List recent send failures."""
    db = _get_db()
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    errors = list(
        db["outreach_sends_v2"]
        .find(
            {"status": "failed", "sent_at": {"$gte": cutoff}},
            {"_id": 0, "body_html": 0, "body_plain": 0},
        )
        .sort("sent_at", DESCENDING)
        .limit(limit)
    )
    return {"count": len(errors), "errors": errors}


@router.get("/outreach/metrics")
async def get_outreach_metrics(hours: int = Query(24, ge=1, le=720)):
    """Aggregate outreach metrics for the given window."""
    db = _get_db()
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    pipeline = [
        {"$match": {"sent_at": {"$gte": cutoff}}},
        {
            "$group": {
                "_id": "$status",
                "count": {"$sum": 1},
            }
        },
    ]
    results = list(db["outreach_sends_v2"].aggregate(pipeline))
    metrics = {r["_id"]: r["count"] for r in results}
    total = sum(metrics.values())
    return {
        "window_hours": hours,
        "total": total,
        "by_status": metrics,
        "bounce_rate": round(metrics.get("bounced", 0) / total * 100, 2) if total else 0,
    }

