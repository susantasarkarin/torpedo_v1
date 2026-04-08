"""
One-time migration: purge stale quota keys from qre_health_survey.quotas
and reseed with only the 8 Tier-2 cities defined in the current config.
"""
import asyncio, sys
sys.path.insert(0, "/var/www/campaign_platform/qre_backend")
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "qre_health_survey"

# Current valid quota keys  (must match qre_backend/config.py)
VALID_QUOTA_KEYS = {
    # Age
    "band1_25_34", "band2_35_44", "band3_45_55",
    # Gender
    "male", "female",
    # NCCS
    "nccs_a", "nccs_b",
    # 8 Tier-2 cities
    "lucknow", "jaipur", "indore", "surat",
    "pune", "coimbatore", "warangal", "bhubaneswar",
}

async def main():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]

    existing = await db.quotas.find_one({"_id": "global"}) or {}
    stale = [k for k in existing if k != "_id" and k not in VALID_QUOTA_KEYS]
    print(f"Stale keys to remove: {stale}")

    if not stale:
        print("No stale keys found. Nothing to do.")
        return

    # Remove stale keys, leave current keys untouched
    await db.quotas.update_one(
        {"_id": "global"},
        {"$unset": {k: "" for k in stale}},
    )
    print("Done – stale keys removed.")
    final = await db.quotas.find_one({"_id": "global"})
    del final["_id"]
    print(f"Remaining quota document: {final}")

asyncio.run(main())
