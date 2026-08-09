"""
Panel conversion funnel — where people stall between "emailed" and "earning".

Single source of truth for the funnel stage definitions, used by both the
admin dashboard (GET /panel-admin/dashboard/funnel) and the re-engagement drip
sender (services/panel_drip_service.py), so a segment shown on the dashboard
is exactly the segment that gets mailed.

All counts come from campaign_platform.panelists / panel_invitation_log. The
SFW panel's own profile and survey numbers are reported alongside as context
by the router, not mixed into these stages — they are keyed differently and
would double-count.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from pymongo import MongoClient

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
_client = MongoClient(MONGO_URI)
_db = _client["campaign_platform"]

panelists_collection = _db["panelists"]
invitation_log_collection = _db["panel_invitation_log"]

# Fields that make a profile useful for survey targeting. "Profile complete"
# means all of these are present — matching the intent of
# routers/panel.py::calculate_profile_completion without recomputing a
# percentage per document (which would mean reading all ~190K records).
PROFILE_CORE_FIELDS = ["date_of_birth", "gender", "country", "city", "occupation"]

# A panelist counts as active once they have actually logged in since
# confirming — the point at which they can take a survey and earn.
ACTIVATION_STALL_DAYS = int(os.getenv("PANEL_ACTIVATION_STALL_DAYS", "7"))


def _present(field: str) -> Dict[str, Any]:
    """Match documents where `field` is set to a non-empty value."""
    return {field: {"$exists": True, "$nin": [None, ""]}}


def _absent(field: str) -> Dict[str, Any]:
    return {"$or": [{field: {"$exists": False}}, {field: {"$in": [None, ""]}}]}


# ============== SEGMENT QUERIES ==============
# Each returns a Mongo query. The drip sender adds its own cooldown/cap
# conditions on top, so these stay purely about funnel position.

def q_profile_complete() -> Dict[str, Any]:
    return {"$and": [_present(f) for f in PROFILE_CORE_FIELDS]}


def q_profile_incomplete() -> Dict[str, Any]:
    return {"$or": [_absent(f) for f in PROFILE_CORE_FIELDS]}


def q_signed_up_unverified() -> Dict[str, Any]:
    """Created an account but never completed double opt-in.

    `password_hash` is what separates a real self-signup from an imported
    lead: imported rows have no password and were never asked to verify, so
    counting them here would put ~190K cold addresses in a segment meant for
    people who actually tried to join.
    """
    return {
        "password_hash": {"$exists": True, "$ne": ""},
        "double_opt_in_completed": {"$ne": True},
        "status": {"$nin": ["dnd", "unsubscribed", "bounced"]},
    }


def q_opted_in_no_profile() -> Dict[str, Any]:
    """Confirmed the email but never filled in the targeting fields."""
    return {
        "$and": [
            {"double_opt_in_completed": True},
            {"status": {"$nin": ["dnd", "unsubscribed", "bounced"]}},
            q_profile_incomplete(),
        ]
    }


def q_profile_no_activity() -> Dict[str, Any]:
    """Profile is complete but they have never come back to take a survey."""
    stale_before = datetime.utcnow() - timedelta(days=ACTIVATION_STALL_DAYS)
    return {
        "$and": [
            {"double_opt_in_completed": True},
            {"status": {"$nin": ["dnd", "unsubscribed", "bounced"]}},
            q_profile_complete(),
            {"$or": [
                {"last_login": {"$exists": False}},
                {"last_login": None},
                {"last_login": {"$lt": stale_before}},
            ]},
        ]
    }


SEGMENTS = {
    "signed_up_unverified": {
        "label": "Registered, no double opt-in",
        "description": "Created an account but never clicked the confirmation link.",
        "query": q_signed_up_unverified,
    },
    "opted_in_no_profile": {
        "label": "Opted in, profile incomplete",
        "description": "Confirmed their email but never filled in the profile we target surveys on.",
        "query": q_opted_in_no_profile,
    },
    "profile_no_activity": {
        "label": "Profile complete, never active",
        "description": f"Profile is done but no login in the last {ACTIVATION_STALL_DAYS} days.",
        "query": q_profile_no_activity,
    },
}


# ============== FUNNEL ==============

# The funnel is expensive enough (several counts over ~190K docs, some without
# a usable index) that recomputing it on every dashboard render was never
# going to be acceptable. Ten minutes is well inside the daily cadence the
# numbers actually move on.
_funnel_cache: Dict[str, Any] = {}
_FUNNEL_TTL = int(os.getenv("PANEL_FUNNEL_CACHE_TTL", "600"))


def _distinct_clicked_emails() -> int:
    """Unique addresses that clicked an invite link.

    Counting log rows would overcount — a lead is re-invited every few days,
    so one person can own many clicked rows.
    """
    pipeline = [
        {"$match": {"clicked_at": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$email"}},
        {"$count": "total"},
    ]
    result = list(invitation_log_collection.aggregate(pipeline, allowDiskUse=True))
    return result[0]["total"] if result else 0


def compute_funnel(force: bool = False) -> Dict[str, Any]:
    """Stage counts, drop-off between stages, and stalled-segment sizes."""
    now = time.time()
    cached = _funnel_cache.get("data")
    if cached and not force and (now - _funnel_cache.get("at", 0)) < _FUNNEL_TTL:
        return {**cached, "cached": True}

    started = time.time()

    pool = panelists_collection.count_documents({})
    invited = panelists_collection.count_documents(
        {"last_invited_at": {"$exists": True, "$ne": None}}
    )
    clicked = _distinct_clicked_emails()
    opted_in = panelists_collection.count_documents({"double_opt_in_completed": True})
    profiled = panelists_collection.count_documents({
        "$and": [{"double_opt_in_completed": True}, q_profile_complete()]
    })
    active = panelists_collection.count_documents({
        "$and": [
            {"double_opt_in_completed": True},
            {"last_login": {"$exists": True, "$ne": None}},
        ]
    })

    raw_stages = [
        ("pool", "In panelist pool", pool),
        ("invited", "Invited at least once", invited),
        ("clicked", "Clicked the invite", clicked),
        ("opted_in", "Completed double opt-in", opted_in),
        ("profiled", "Profile complete", profiled),
        ("active", "Logged in / active", active),
    ]

    stages: List[Dict[str, Any]] = []
    top = raw_stages[0][2] or 0
    previous = None
    for key, label, count in raw_stages:
        stages.append({
            "key": key,
            "label": label,
            "count": count,
            "pct_of_pool": round((count / top) * 100, 2) if top else 0.0,
            # Conversion from the stage immediately above — this is the number
            # that identifies the leak, not the share of the pool.
            "pct_of_previous": (
                round((count / previous) * 100, 2) if previous else None
            ),
            "dropped_from_previous": (previous - count) if previous is not None else None,
        })
        previous = count

    segments = {}
    for key, spec in SEGMENTS.items():
        segments[key] = {
            "label": spec["label"],
            "description": spec["description"],
            "count": panelists_collection.count_documents(spec["query"]()),
        }

    data = {
        "stages": stages,
        "segments": segments,
        "generated_at": datetime.utcnow().isoformat(),
        "compute_seconds": round(time.time() - started, 2),
        "cached": False,
    }
    _funnel_cache["data"] = data
    _funnel_cache["at"] = now
    return data
