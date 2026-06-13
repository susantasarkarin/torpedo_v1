"""
Yield Management — Startup Initialization
=========================================

Brings the Cint yield-management layer into a known-good state at boot:

1. Seeds the default yield-threshold config into torpedo_settings.app_settings
   (so PUT /yield-thresholds always has a base document to merge against, and
   get_yield_thresholds is backed by a real persisted doc rather than an
   in-memory fallback).

2. Bootstraps a stub cint_metrics doc (survey_status="testing") for every
   survey in cint_surveys that has no metrics yet, so freshly-arrived surveys
   are visible on the yield dashboard instead of silently missing.

Idempotent: safe to run on every startup. Existing threshold and metrics
documents are never overwritten.
"""

import logging
from datetime import datetime

from database import get_async_collection

logger = logging.getLogger(__name__)

# Mirrors the hardcoded fallback in routers/cint.get_yield_thresholds so the
# persisted doc and the API default never drift.
DEFAULT_YIELD_THRESHOLDS = {
    "global": {"inactive_conv_threshold": 0.05, "min_ir": 15, "min_cpi": 0.75},
    "countries": {},
}


async def _seed_thresholds() -> bool:
    """Insert the default threshold doc only if it does not already exist."""
    col = get_async_collection("torpedo_settings", "app_settings")
    existing = await col.find_one({"_id": "yield_thresholds"}, {"_id": 1})
    if existing:
        return False
    doc = {"_id": "yield_thresholds", **DEFAULT_YIELD_THRESHOLDS}
    await col.insert_one(doc)
    return True


async def _bootstrap_metrics_stubs() -> int:
    """
    Create a testing-state cint_metrics stub for every survey lacking one.

    Returns the number of stubs inserted.
    """
    surveys_col = get_async_collection("cint_research", "cint_surveys")
    metrics_col = get_async_collection("cint_research", "cint_metrics")

    existing_ids = set()
    async for m in metrics_col.find({}, {"survey_id": 1, "_id": 0}):
        existing_ids.add(str(m.get("survey_id")))

    now = datetime.utcnow()
    inserted = 0
    async for s in surveys_col.find({}, {"survey_id": 1, "_id": 0}):
        sid = str(s.get("survey_id"))
        if not sid or sid == "None" or sid in existing_ids:
            continue
        await metrics_col.update_one(
            {"survey_id": sid},
            {"$setOnInsert": {
                "survey_id": sid,
                "survey_status": "testing",
                "entrants_n": 0,
                "completions": 0,
                "quality_term_n": 0,
                "overquota_n": 0,
                "internal_conversion": None,
                "manual_override": False,
                "created_at": now,
                "last_updated": now,
            }},
            upsert=True,
        )
        existing_ids.add(sid)
        inserted += 1

    return inserted


async def initialize_yield_management() -> dict:
    """
    Run all yield-management startup tasks. Never raises — logs and returns a
    summary so a failure here cannot block application startup.
    """
    summary = {"thresholds_seeded": False, "metrics_stubs_created": 0}
    try:
        summary["thresholds_seeded"] = await _seed_thresholds()
    except Exception as e:
        logger.error(f"[YieldInit] threshold seed failed: {e}")

    try:
        summary["metrics_stubs_created"] = await _bootstrap_metrics_stubs()
    except Exception as e:
        logger.error(f"[YieldInit] metrics stub bootstrap failed: {e}")

    return summary
