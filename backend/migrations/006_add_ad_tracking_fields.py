"""
Migration: ad-platform attribution + thank-you pixel fields (traffic_flow_db)

MongoDB is schemaless, so the new fields need no DDL — new traffic records get
them from /api/store. This migration only adds indexes and backfills records
that already arrived from ads.

traffic_flow_db.url_parameters — new fields:
- traffic_source        "meta" | "google_ads" | "tiktok" | raw utm_source | "direct"
- adTracking            {utm_source, utm_medium, utm_campaign, campaign_id, adset_id,
                         ad_id, placement, fbclid/gclid/ttclid, fbp, fbc}
                        (IP and UA are NOT duplicated: clientIp / userAgent already exist)
- ad_pixel_fired_at     set atomically when a pixel renders on the thank-you page
- ad_pixel_platform     platform whose pixel rendered

traffic_flow_db.ad_pixel_fires (new collection) — audit log
- {rid (as received), record_id, platform, survey_id, event_id, firedAt}

Indexes:
- url_parameters: partial (traffic_source, completedAt) for ad sources only — tiny
- url_parameters: partial (respondentId, traffic_source) and adTracking.fbclid,
  for /adpixel lookups by the ad-side identifier
- ad_pixel_fires: unique record_id, firedAt

Backfill: records with params.utm_source / fbclid / gclid / ttclid and no
traffic_source get traffic_source + adTracking derived the same way as entry.
Already-completed backfilled records stay pixel-eligible only if their
completion link is hit again — intended: that is a real complete we never
reported. Run with --status first and review the count if that matters.

Usage (runner targets email_automation; this reaches traffic_flow_db via the client):
    python migrations/run_migrations.py
"""

import logging
import os
import sys
from datetime import datetime

from pymongo import ASCENDING, DESCENDING, UpdateOne

logger = logging.getLogger(__name__)

TRAFFIC_DB = "traffic_flow_db"
AD_SOURCES = ["meta", "google_ads", "tiktok"]
AD_SIGNAL_QUERY = {
    "traffic_source": {"$exists": False},
    "$or": [
        {"params.utm_source": {"$exists": True, "$ne": ""}},
        {"params.fbclid": {"$exists": True, "$ne": ""}},
        {"params.gclid": {"$exists": True, "$ne": ""}},
        {"params.ttclid": {"$exists": True, "$ne": ""}},
    ],
}


def _traffic_db(db):
    return db.client[TRAFFIC_DB]


def up(db):
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from services.ad_tracking import extract_ad_tracking  # same derivation as live entry

    tdb = _traffic_db(db)
    logger.info("Running migration 006_add_ad_tracking_fields")

    tdb.url_parameters.create_index(
        [("traffic_source", ASCENDING), ("completedAt", DESCENDING)],
        name="ad_traffic_source_completed",
        partialFilterExpression={"traffic_source": {"$in": AD_SOURCES}},
    )
    # /adpixel resolves rid -> record by respondentId or fbclid; keep those lookups indexed
    tdb.url_parameters.create_index(
        [("respondentId", ASCENDING), ("traffic_source", ASCENDING)],
        name="ad_respondent_id",
        partialFilterExpression={"traffic_source": {"$in": AD_SOURCES}},
    )
    tdb.url_parameters.create_index(
        [("adTracking.fbclid", ASCENDING)],
        name="ad_fbclid",
        partialFilterExpression={"adTracking.fbclid": {"$exists": True}},
    )
    tdb.ad_pixel_fires.create_index([("record_id", ASCENDING)], name="record_id_unique", unique=True)
    tdb.ad_pixel_fires.create_index([("firedAt", DESCENDING)], name="firedAt")

    ops, updated = [], 0
    for record in tdb.url_parameters.find(AD_SIGNAL_QUERY, {"params": 1}):
        fields = extract_ad_tracking(record.get("params") or {}, {}, {})
        ops.append(UpdateOne({"_id": record["_id"], "traffic_source": {"$exists": False}}, {"$set": fields}))
        if len(ops) >= 500:
            updated += tdb.url_parameters.bulk_write(ops, ordered=False).modified_count
            ops = []
    if ops:
        updated += tdb.url_parameters.bulk_write(ops, ordered=False).modified_count

    logger.info(f"Backfilled traffic_source on {updated} records")
    return {"backfilled": updated, "at": datetime.utcnow().isoformat()}


def down(db):
    """Drops the new indexes only. Data is left in place on purpose: unsetting
    traffic_source/adTracking would also erase live entries, and removing
    ad_pixel_fired_at or the audit log could let a pixel fire twice."""
    tdb = _traffic_db(db)
    for coll, name in (("url_parameters", "ad_traffic_source_completed"),
                       ("url_parameters", "ad_respondent_id"), ("url_parameters", "ad_fbclid"),
                       ("ad_pixel_fires", "record_id_unique"), ("ad_pixel_fires", "firedAt")):
        try:
            tdb[coll].drop_index(name)
        except Exception as e:
            logger.warning(f"drop_index {coll}.{name}: {e}")
    logger.info("Rolled back 006_add_ad_tracking_fields (indexes only)")
