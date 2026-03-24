"""
Atomic quota management using MongoDB findOneAndUpdate.
Prevents race conditions when many respondents hit quota checks simultaneously.
"""
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


async def get_all_quotas(db: AsyncIOMotorDatabase) -> list[dict]:
    """Return current quota status for admin dashboard."""
    doc = await db.quotas.find_one({"_id": "global"})
    if not doc:
        return []

    all_defaults = {**QUOTA_AGE, **QUOTA_GENDER, **QUOTA_NCCS, **QUOTA_CITY}
    # Check for DB overrides
    limits_doc = await db.quota_limits.find_one({"_id": "limits"})
    result = []
    for key, default_limit in all_defaults.items():
        limit = limits_doc.get(key, default_limit) if limits_doc else default_limit
        current = doc.get(key, 0)
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
