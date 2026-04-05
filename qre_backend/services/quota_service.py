"""
Atomic quota management using MongoDB findOneAndUpdate.
Prevents race conditions when many respondents hit quota checks simultaneously.
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorDatabase
from config import QUOTA_AGE, QUOTA_GENDER, QUOTA_NCCS, QUOTA_CITY, CITY_CODE_MAP

# Q3 code → age-band quota key  (codes 1 = 18-24 and 5 = 55+ both terminate)
_AGE_CODE_MAP: dict[int, str] = {
    2: "band1_25_34",
    3: "band2_35_44",
    4: "band3_45_55",
}

# Q4 code → gender quota key
_GENDER_CODE_MAP: dict[int, str] = {
    1: "female",
    2: "male",
}


async def ensure_quota_doc(db: AsyncIOMotorDatabase):
    """Create the quota counters document if it doesn't exist.
    Also adds any missing quota keys to an existing document (e.g., after city list changes).
    """
    all_keys = {**QUOTA_AGE, **QUOTA_GENDER, **QUOTA_NCCS, **QUOTA_CITY}
    existing = await db.quotas.find_one({"_id": "global"})
    if not existing:
        initial: dict = {"_id": "global"}
        for key in all_keys:
            initial[key] = 0
        await db.quotas.insert_one(initial)
    else:
        # Add any quota keys that are missing from the existing document
        # (this happens when the city list or quota config changes between deployments)
        missing = {k: 0 for k in all_keys if k not in existing}
        if missing:
            await db.quotas.update_one({"_id": "global"}, {"$set": missing})


async def ensure_study_quota_doc(db: AsyncIOMotorDatabase, study_id: str):
    """Create the per-study quota counter document if it doesn't exist.
    Called lazily on each start_survey so the doc is always present before
    any try_claim_quota call for that study.
    """
    counter_id = f"quota_{study_id}"
    all_keys = {**QUOTA_AGE, **QUOTA_GENDER, **QUOTA_NCCS, **QUOTA_CITY}
    existing = await db.quotas.find_one({"_id": counter_id})
    if not existing:
        try:
            await db.quotas.insert_one({"_id": counter_id, **{k: 0 for k in all_keys}})
        except Exception:
            pass  # duplicate key on race condition — safe to ignore
    else:
        missing = {k: 0 for k in all_keys if k not in existing}
        if missing:
            await db.quotas.update_one({"_id": counter_id}, {"$set": missing})


def _get_limit(key: str) -> int:
    """Look up the limit for a quota key (sync fallback for default)."""
    all_quotas = {**QUOTA_AGE, **QUOTA_GENDER, **QUOTA_NCCS, **QUOTA_CITY}
    return all_quotas.get(key, 999999)


async def _get_limit_async(
    db: AsyncIOMotorDatabase, key: str, study_id: str | None = None
) -> int:
    """Look up the limit for a quota key.

    Priority:
    1. Per-study limits from db.studies.quotas.cells  (when study_id is given)
    2. Admin overrides from db.quota_limits           (legacy global overrides)
    3. Hard-coded config defaults
    """
    if study_id and study_id != "default":
        study_doc = await db.studies.find_one(
            {"_id": study_id}, {"quotas.cells": 1}
        )
        if study_doc:
            cells = study_doc.get("quotas", {}).get("cells", {})
            if key in cells:
                return int(cells[key])
    # Fall back to legacy global quota_limits collection then config
    doc = await db.quota_limits.find_one({"_id": "limits"})
    if doc and key in doc:
        return doc[key]
    return _get_limit(key)


async def try_claim_quota(
    db: AsyncIOMotorDatabase, quota_key: str, study_id: str | None = None
) -> bool:
    """
    Atomically attempt to increment a quota counter.
    Returns True if the slot was claimed (counter was below limit).
    Returns False if quota is already full (no increment performed).

    When *study_id* is provided the per-study counter document
    (``_id: "quota_{study_id}"``) is used; otherwise the global doc is used.
    """
    counter_id = f"quota_{study_id}" if (study_id and study_id != "default") else "global"
    limit = await _get_limit_async(db, quota_key, study_id)

    result = await db.quotas.find_one_and_update(
        {"_id": counter_id, quota_key: {"$lt": limit}},
        {"$inc": {quota_key: 1}},
    )
    return result is not None


async def release_quota(
    db: AsyncIOMotorDatabase, quota_key: str, study_id: str | None = None
):
    """Decrement a quota counter (e.g., on termination after quota was claimed)."""
    counter_id = f"quota_{study_id}" if (study_id and study_id != "default") else "global"
    await db.quotas.update_one(
        {"_id": counter_id, quota_key: {"$gt": 0}},
        {"$inc": {quota_key: -1}},
    )


async def _aggregate_respondent_counts(
    db: AsyncIOMotorDatabase, study_id: str | None = None
) -> dict[str, int]:
    """
    Compute per-quota-key completion counts directly from raw survey responses.

    Deriving from responses.Q2/Q3/Q4 ensures accuracy for ALL respondents
    regardless of schema version — older records may lack derived fields
    (city, nccs_band, quota_claims) but the raw response answers are always
    stored at the time the question was answered.

    - City  : responses.Q2 → CITY_CODE_MAP
    - Age   : responses.Q3 → _AGE_CODE_MAP
    - Gender: responses.Q4 → _GENDER_CODE_MAP
    - NCCS  : nccs_band field (set at Q7 on new records); falls back to
              quota_claims for records that store it there
    """
    base: dict = {"status": "completed"}
    if study_id and study_id != "default":
        base["study_id"] = study_id

    counts: dict[str, int] = {}

    # ── City from responses.Q2 ────────────────────────────────────────────────
    async for doc in db.respondents.aggregate([
        {"$match": {**base, "responses.Q2": {"$exists": True}}},
        {"$group": {"_id": "$responses.Q2", "count": {"$sum": 1}}},
    ]):
        try:
            city = CITY_CODE_MAP.get(int(doc["_id"]))
            if city:
                counts[city] = counts.get(city, 0) + doc["count"]
        except (TypeError, ValueError):
            pass

    # ── Age bands from responses.Q3 ───────────────────────────────────────────
    async for doc in db.respondents.aggregate([
        {"$match": {**base, "responses.Q3": {"$in": [2, 3, 4, "2", "3", "4"]}}},
        {"$group": {"_id": "$responses.Q3", "count": {"$sum": 1}}},
    ]):
        try:
            key = _AGE_CODE_MAP.get(int(doc["_id"]))
            if key:
                counts[key] = counts.get(key, 0) + doc["count"]
        except (TypeError, ValueError):
            pass

    # ── Gender from responses.Q4 ──────────────────────────────────────────────
    async for doc in db.respondents.aggregate([
        {"$match": {**base, "responses.Q4": {"$in": [1, 2, "1", "2"]}}},
        {"$group": {"_id": "$responses.Q4", "count": {"$sum": 1}}},
    ]):
        try:
            key = _GENDER_CODE_MAP.get(int(doc["_id"]))
            if key:
                counts[key] = counts.get(key, 0) + doc["count"]
        except (TypeError, ValueError):
            pass

    # ── NCCS from nccs_band field (set on post-migration records) ─────────────
    async for doc in db.respondents.aggregate([
        {"$match": {**base, "nccs_band": {"$in": ["nccs_a", "nccs_b"]}}},
        {"$group": {"_id": "$nccs_band", "count": {"$sum": 1}}},
    ]):
        counts[doc["_id"]] = doc["count"]

    # ── NCCS fallback: quota_claims for older records without nccs_band ───────
    # Only sum records NOT already counted via nccs_band to avoid double-counting.
    if counts.get("nccs_a", 0) + counts.get("nccs_b", 0) == 0:
        nccs_keys = ["nccs_a", "nccs_b"]
        async for doc in db.respondents.aggregate([
            {"$match": {**base, "nccs_band": {"$exists": False},
                        "quota_claims": {"$in": nccs_keys}}},
            {"$unwind": "$quota_claims"},
            {"$match": {"quota_claims": {"$in": nccs_keys}}},
            {"$group": {"_id": "$quota_claims", "count": {"$sum": 1}}},
        ]):
            counts[doc["_id"]] = counts.get(doc["_id"], 0) + doc["count"]

    return counts


async def get_all_quotas(
    db: AsyncIOMotorDatabase, study_id: str | None = None
) -> list[dict]:
    """Return current quota status for admin dashboard.

    Counts are computed live from the respondents collection so they reflect
    only completed interviews and are never inflated by abandoned sessions.
    Pass *study_id* to scope counts to a single study; omit (or pass None)
    to aggregate across all studies.
    """
    all_defaults = {**QUOTA_AGE, **QUOTA_GENDER, **QUOTA_NCCS, **QUOTA_CITY}
    limits_doc, counts = await asyncio.gather(
        db.quota_limits.find_one({"_id": "limits"}),
        _aggregate_respondent_counts(db, study_id),
    )
    result = []
    for key, default_limit in all_defaults.items():
        limit = limits_doc.get(key, default_limit) if limits_doc else default_limit
        current = counts.get(key, 0)
        result.append({
            "quota_key": key,
            "current": current,
            "limit": limit,
            "is_full": current >= limit,
        })
    return result


async def check_quota_available(
    db: AsyncIOMotorDatabase, quota_key: str, study_id: str | None = None
) -> bool:
    """Check if a quota cell has room without claiming it."""
    counter_id = f"quota_{study_id}" if (study_id and study_id != "default") else "global"
    limit = await _get_limit_async(db, quota_key, study_id)
    doc = await db.quotas.find_one({"_id": counter_id})
    if not doc:
        return True
    return doc.get(quota_key, 0) < limit
