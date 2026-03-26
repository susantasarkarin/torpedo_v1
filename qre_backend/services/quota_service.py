"""
Atomic quota management using MongoDB findOneAndUpdate.
Prevents race conditions when many respondents hit quota checks simultaneously.
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorDatabase
from config import QUOTA_AGE, QUOTA_GENDER, QUOTA_NCCS, QUOTA_CITY


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


def _get_limit(key: str) -> int:
    """Look up the limit for a quota key (sync fallback for default)."""
    all_quotas = {**QUOTA_AGE, **QUOTA_GENDER, **QUOTA_NCCS, **QUOTA_CITY}
    return all_quotas.get(key, 999999)


async def _get_limit_async(db: AsyncIOMotorDatabase, key: str) -> int:
    """Look up the limit for a quota key, checking DB overrides first."""
    doc = await db.quota_limits.find_one({"_id": "limits"})
    if doc and key in doc:
        return doc[key]
    return _get_limit(key)


async def try_claim_quota(db: AsyncIOMotorDatabase, quota_key: str) -> bool:
    """
    Atomically attempt to increment a quota counter.
    Returns True if the slot was claimed (counter was below limit).
    Returns False if quota is already full (no increment performed).
    """
    limit = await _get_limit_async(db, quota_key)

    result = await db.quotas.find_one_and_update(
        {"_id": "global", quota_key: {"$lt": limit}},
        {"$inc": {quota_key: 1}},
    )
    return result is not None


async def release_quota(db: AsyncIOMotorDatabase, quota_key: str):
    """Decrement a quota counter (e.g., on termination after quota was claimed)."""
    await db.quotas.update_one(
        {"_id": "global", quota_key: {"$gt": 0}},
        {"$inc": {quota_key: -1}},
    )


async def _aggregate_respondent_counts(
    db: AsyncIOMotorDatabase, study_id: str | None = None
) -> dict[str, int]:
    """
    Compute per-quota-key completion counts directly from the respondents
    collection.  This is the ground truth: it counts only *completed*
    respondents and avoids drift caused by abandoned in-progress sessions
    whose quota claims were never released.

    - City  : stored as respondent.city  (set at Q2, hard quota)
    - NCCS  : stored as respondent.nccs_band  (set at Q7, hard quota)
    - Age   : stored in respondent.quota_claims  (set at Q3, hard quota)
    - Gender: counted from respondent.responses.Q4  (Q4 is a soft quota;
              respondents who answered when gender was already full still
              have a Q4 response but no gender entry in quota_claims)
    """
    base: dict = {"status": "completed"}
    if study_id and study_id != "default":
        base["study_id"] = study_id

    counts: dict[str, int] = {}

    # City (respondent.city field)
    async for doc in db.respondents.aggregate([
        {"$match": {**base, "city": {"$exists": True}}},
        {"$group": {"_id": "$city", "count": {"$sum": 1}}},
    ]):
        counts[doc["_id"]] = doc["count"]

    # NCCS (respondent.nccs_band field)
    async for doc in db.respondents.aggregate([
        {"$match": {**base, "nccs_band": {"$in": ["nccs_a", "nccs_b"]}}},
        {"$group": {"_id": "$nccs_band", "count": {"$sum": 1}}},
    ]):
        counts[doc["_id"]] = doc["count"]

    # Age bands (in quota_claims — all completions carry this since it is a hard quota)
    age_keys = list(QUOTA_AGE.keys())
    async for doc in db.respondents.aggregate([
        {"$match": {**base, "quota_claims": {"$elemMatch": {"$in": age_keys}}}},
        {"$unwind": "$quota_claims"},
        {"$match": {"quota_claims": {"$in": age_keys}}},
        {"$group": {"_id": "$quota_claims", "count": {"$sum": 1}}},
    ]):
        counts[doc["_id"]] = doc["count"]

    # Gender from responses.Q4 (must NOT rely on quota_claims for soft quota)
    # Frontend sends numeric codes; tolerate string form as well.
    gender_map: dict = {1: "female", 2: "male", "1": "female", "2": "male"}
    async for doc in db.respondents.aggregate([
        {"$match": {**base, "responses.Q4": {"$in": [1, 2, "1", "2"]}}},
        {"$group": {"_id": "$responses.Q4", "count": {"$sum": 1}}},
    ]):
        key = gender_map.get(doc["_id"])
        if key:
            counts[key] = counts.get(key, 0) + doc["count"]

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


async def check_quota_available(db: AsyncIOMotorDatabase, quota_key: str) -> bool:
    """Check if a quota cell has room without claiming it."""
    limit = await _get_limit_async(db, quota_key)
    doc = await db.quotas.find_one({"_id": "global"})
    if not doc:
        return True
    return doc.get(quota_key, 0) < limit
