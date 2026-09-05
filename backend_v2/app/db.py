"""
The single Motor client factory.

v1 had ~150 independent `MongoClient(...)`/`AsyncIOMotorClient(...)` instantiation
sites across the codebase (entity_map.md §1), each a candidate for its own connection
pool, its own timeout defaults, and its own drift from whatever the "shared" client was
supposed to be. Locked principle 2 (`v2_locked_principles.md`) forbids this outright:
"No independent MongoClient creation."

Every module that needs a database handle imports `get_database()` from here. There is
no second way to obtain one in this codebase — enforcing that is a code-review rule
this module exists to make trivially checkable (grep for `AsyncIOMotorClient(` outside
this file; any hit outside a test is a defect).
"""

from datetime import timezone
from functools import lru_cache

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings


@lru_cache
def get_client() -> AsyncIOMotorClient:
    settings = get_settings()
    # tz_aware=True + tzinfo=UTC: PyMongo/Motor's default BSON codec decodes stored
    # datetimes as *naive* UTC, silently dropping the tzinfo every write in this
    # codebase attaches (CanonicalDocument's `_utcnow()`). Read that naive value back
    # into a comparison against a tz-aware `datetime.now(timezone.utc)` and Python
    # raises `TypeError: can't compare offset-naive and offset-aware datetimes` — this
    # was caught by the auth slice's expiry tests. Left at the default, this is the
    # same defect class as v1's naive-vs-aware `created_at` (data_lineage_map.md D2/D3),
    # reintroduced by the driver rather than by application code, which is precisely
    # why it belongs fixed once here rather than worked around at every call site.
    return AsyncIOMotorClient(settings.mongo_uri, tz_aware=True, tzinfo=timezone.utc)


def get_database() -> AsyncIOMotorDatabase:
    """
    Returns the one canonical database. Takes no arguments, deliberately — a
    `db_name` parameter on this function is exactly the shape of the bug D-15/D-21
    turned into a caller-controlled write-target injection in v1's outreach router.
    """
    settings = get_settings()
    return get_client()[settings.mongo_db_name]
