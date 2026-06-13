"""
Yield Management — Startup Initialization
=========================================

Seeds the default yield-threshold config into torpedo_settings.app_settings so
PUT /yield-thresholds always has a base document to merge against. This is a
single cheap find-or-insert — it must never do heavy per-document work, because
it runs inside the FastAPI startup event and blocks the worker from serving
requests until it returns.

NOTE: we intentionally do NOT pre-create cint_metrics stub docs here. The
yield-dashboard, buyer-stats and yield-status endpoints all treat a missing
metrics doc as survey_status="testing" (see routers/cint.get_yield_dashboard),
so stubs add no functional value. A previous version iterated every survey in
cint_surveys doing one upsert each; on a large collection that ran for minutes
inside startup, blocking the event loop and saturating Mongo (login/health
timed out). Removed — surveys without metrics are handled lazily downstream.

Idempotent: safe to run on every startup. An existing threshold doc is never
overwritten.
"""

import logging

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


async def initialize_yield_management() -> dict:
    """
    Run yield-management startup tasks. Never raises — logs and returns a
    summary so a failure here cannot block application startup.
    """
    summary = {"thresholds_seeded": False}
    try:
        summary["thresholds_seeded"] = await _seed_thresholds()
    except Exception as e:
        logger.error(f"[YieldInit] threshold seed failed: {e}")

    return summary
