"""
Migration: client reconciliation reject history (traffic_flow_db)

Rejects are an outcome, kept apart from the SFW-B behaviour score so it can be
tested against them later. Written by services/respondent_quality.apply_client_rejects:

client_rejects          _id = traffic record id; latest reason (verbatim), project, vendor,
                        Meta attribution, SFW-B at reject time, history[] of every upload
client_reject_batches   one doc per upload: who, when, default reason, matched, unmatched ids

Indexes:
- client_rejects: surveyNo + lastUploadedAt, vendorId, respondentId
- client_reject_batches: surveyNo + uploadedAt
"""

import logging

from pymongo import ASCENDING, DESCENDING

logger = logging.getLogger(__name__)

TRAFFIC_DB = "traffic_flow_db"

INDEXES = [
    ("client_rejects", [("surveyNo", ASCENDING), ("lastUploadedAt", DESCENDING)], "survey_uploaded"),
    ("client_rejects", [("vendorId", ASCENDING)], "vendor"),
    ("client_rejects", [("respondentId", ASCENDING)], "respondent"),
    ("client_reject_batches", [("surveyNo", ASCENDING), ("uploadedAt", DESCENDING)], "survey_uploaded"),
]


def up(db):
    tdb = db.client[TRAFFIC_DB]
    for coll, keys, name in INDEXES:
        tdb[coll].create_index(keys, name=name)
    return {"indexes": [f"{c}.{n}" for c, _, n in INDEXES]}


def down(db):
    tdb = db.client[TRAFFIC_DB]
    for coll, _, name in INDEXES:
        try:
            tdb[coll].drop_index(name)
        except Exception as e:
            logger.warning(f"drop_index {coll}.{name}: {e}")
