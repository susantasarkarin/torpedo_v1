"""
Migration: indexes for the SFW respondent quality score (traffic_flow_db)

services/respondent_quality.py looks respondents up at entry, on the request
path, so every lookup must be indexed (url_parameters holds ~720k records).
Fields are added by /api/store and the scorer, so there is no data change:

url_parameters:
- sfwVisitorId + createdAt   (partial: has sfwVisitorId)  re-entry + visitor velocity
- adTracking.fbp             (partial: has fbp)           re-entry for Meta traffic
- respondentId + vendorId                                  re-entry by vendor id; also /adpixel lookups
- deviceFingerprint + clientIp                             weak device+IP repeat
- clientIp + createdAt                                     IP velocity
- clientRejected             (partial: true)               prior client rejects
traffic_flow_db.ip_intel     TTL on checkedAt (8 days; cache is trusted for 7)

Usage (runner targets email_automation; this reaches traffic_flow_db via the client):
    python migrations/run_migrations.py
"""

import logging

from pymongo import ASCENDING, DESCENDING

logger = logging.getLogger(__name__)

TRAFFIC_DB = "traffic_flow_db"

INDEXES = [
    ("url_parameters", [("sfwVisitorId", ASCENDING), ("createdAt", DESCENDING)], "sfw_visitor_created",
     {"partialFilterExpression": {"sfwVisitorId": {"$exists": True}}}),
    ("url_parameters", [("adTracking.fbp", ASCENDING)], "sfw_fbp",
     {"partialFilterExpression": {"adTracking.fbp": {"$exists": True}}}),
    ("url_parameters", [("respondentId", ASCENDING), ("vendorId", ASCENDING)], "sfw_respondent_vendor", {}),
    ("url_parameters", [("deviceFingerprint", ASCENDING), ("clientIp", ASCENDING)], "sfw_device_ip", {}),
    ("url_parameters", [("clientIp", ASCENDING), ("createdAt", DESCENDING)], "sfw_ip_created", {}),
    ("url_parameters", [("clientRejected", ASCENDING)], "sfw_client_rejected",
     {"partialFilterExpression": {"clientRejected": True}}),
    ("ip_intel", [("checkedAt", ASCENDING)], "ip_intel_ttl", {"expireAfterSeconds": 8 * 24 * 3600}),
]


def up(db):
    tdb = db.client[TRAFFIC_DB]
    logger.info("Running migration 007_sfw_quality_indexes")
    for coll, keys, name, opts in INDEXES:
        tdb[coll].create_index(keys, name=name, **opts)
        logger.info(f"index {coll}.{name} ready")
    return {"indexes": [name for _, _, name, _ in INDEXES]}


def down(db):
    tdb = db.client[TRAFFIC_DB]
    for coll, _, name, _ in INDEXES:
        try:
            tdb[coll].drop_index(name)
        except Exception as e:
            logger.warning(f"drop_index {coll}.{name}: {e}")
