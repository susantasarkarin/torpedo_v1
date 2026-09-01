"""
Health Router v2 — System health overview, email deliverability, and alerts.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Query
from pymongo import MongoClient, DESCENDING

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/health", tags=["health"])

MONGO_URI = os.getenv("MONGO_URI", os.getenv("MONGO_URI", "mongodb://localhost:27017"))


def _get_db():
    client = MongoClient(MONGO_URI)
    return client["email_automation"]


def _get_torpedo_db():
    """Return the torpedo DB where outreach collections (campaigns, mailboxes, sends) live."""
    client = MongoClient(MONGO_URI)
    return client["torpedo"]


@router.get("/overview")
async def health_overview(hours: int = Query(24, ge=1, le=720)):
    """High-level system health overview."""
    db = _get_db()
    torpedo_db = _get_torpedo_db()
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    sends = torpedo_db["outreach_sends_v2"]
    total = sends.count_documents({"sent_at": {"$gte": cutoff}})
    failed = sends.count_documents({"status": "failed", "sent_at": {"$gte": cutoff}})
    bounced = sends.count_documents({"status": "bounced", "sent_at": {"$gte": cutoff}})

    # Active mailboxes — schema uses is_active (bool), not status string
    active_mailboxes = torpedo_db["outreach_mailboxes"].count_documents({"is_active": True})

    # Active campaigns — schema uses is_active (bool), not status string
    active_campaigns = torpedo_db["outreach_campaigns_v2"].count_documents(
        {"is_active": True}
    )

    return {
        "window_hours": hours,
        "total_sends": total,
        "failed": failed,
        "bounced": bounced,
        "success_rate": round((total - failed - bounced) / total * 100, 2) if total else 100,
        "active_mailboxes": active_mailboxes,
        "active_campaigns": active_campaigns,
        "checked_at": datetime.utcnow().isoformat(),
    }


@router.get("/email-deliverability")
async def email_deliverability(hours: int = Query(24, ge=1, le=720)):
    """Bounce breakdown: hard vs soft."""
    db = _get_db()
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    pipeline = [
        {"$match": {"created_at": {"$gte": cutoff}, "event_type": {"$in": ["bounced", "soft_bounced"]}}},
        {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
    ]
    results = list(db["outreach_events"].aggregate(pipeline))
    breakdown = {r["_id"]: r["count"] for r in results}

    total_sends = db["outreach_sends_v2"].count_documents({"sent_at": {"$gte": cutoff}})

    return {
        "window_hours": hours,
        "total_sends": total_sends,
        "hard_bounces": breakdown.get("bounced", 0),
        "soft_bounces": breakdown.get("soft_bounced", 0),
        "bounce_rate": round(
            (breakdown.get("bounced", 0) + breakdown.get("soft_bounced", 0)) / total_sends * 100, 2
        ) if total_sends else 0,
    }


@router.get("/alerts")
async def get_alerts(
    status: Optional[str] = Query(None, regex="^(active|acknowledged|resolved)$"),
    limit: int = Query(50, ge=1, le=200),
):
    """List system alerts."""
    db = _get_db()
    query: dict = {}
    if status:
        query["status"] = status

    alerts = list(
        db["system_alerts"]
        .find(query, {"_id": 0})
        .sort("created_at", DESCENDING)
        .limit(limit)
    )
    return {"count": len(alerts), "alerts": alerts}


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str):
    """Acknowledge a system alert."""
    db = _get_db()
    result = db["system_alerts"].update_one(
        {"alert_id": alert_id},
        {"$set": {"status": "acknowledged", "acknowledged_at": datetime.utcnow()}},
    )
    if result.modified_count:
        return {"success": True, "alert_id": alert_id}
    return {"success": False, "reason": "alert_not_found"}

