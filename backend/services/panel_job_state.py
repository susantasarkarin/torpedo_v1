"""
Panel job heartbeats — shared "did this cron actually run" record.

Every panel cron (invite send, login send, suppression sync, registration
sync, drip send, lead promotion) writes one document here on successful
completion. panel_health.py reads them to detect a cron that stopped firing —
which is exactly the failure mode that let lead promotion run scanned=0 every
night for two weeks without anyone noticing (see panel_lead_promotion.py).

One collection, one document per job, upserted — not a growing log. Anything
wanting history should read panel_invitation_log or panel_job_state's own
Mongo oplog, not this.
"""

import os
from datetime import datetime
from typing import Any, Dict, Optional

from pymongo import MongoClient


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    from database import get_client
    return get_client()


MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
_client = _get_pooled_client()
job_state_collection = _client["campaign_platform"]["panel_job_state"]


def record_heartbeat(job_name: str, extra: Optional[Dict[str, Any]] = None) -> None:
    """Mark `job_name` as having completed successfully just now."""
    update: Dict[str, Any] = {"last_success_at": datetime.utcnow()}
    if extra:
        update.update(extra)
    job_state_collection.update_one(
        {"_id": job_name}, {"$set": update}, upsert=True
    )


def get_heartbeat(job_name: str) -> Optional[datetime]:
    doc = job_state_collection.find_one({"_id": job_name}) or {}
    return doc.get("last_success_at")


def get_all_heartbeats() -> Dict[str, Optional[datetime]]:
    """job_name -> last_success_at for every job that has ever reported in."""
    return {
        doc["_id"]: doc.get("last_success_at")
        for doc in job_state_collection.find({}, {"last_success_at": 1})
    }
