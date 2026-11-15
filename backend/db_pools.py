"""
Compatibility shim over db.py.

The three per-workload connection pools (api / background / ai) were retired.
Every handle now comes from db.py, which shares the one process-wide client
pair owned by database.py, so no extra pool is created here.

The get_api_* / get_background_* / get_ai_* helpers are kept so existing
callers keep working. They all resolve to the same default database,
campaign_platform (panel()), which is where these callers' collections have
always resolved (MONGODB_DATABASE was never set, so the old default applied).
New code should import from db directly and name its database explicitly.
"""

try:
    from db import by_name, panel
except ImportError:  # imported as backend.db_pools from the repo root
    from backend.db import by_name, panel  # type: ignore


def get_api_db():
    """Default database for former API-pool callers (campaign_platform)."""
    return panel()


def get_background_db():
    """Default database for former background-pool callers (campaign_platform)."""
    return panel()


def get_ai_db():
    """Default database for former AI-pool callers (campaign_platform)."""
    return panel()


def get_db(db_name: str):
    """Get a specific database by name, via db.by_name."""
    return by_name(db_name)


def get_api_collection(name: str):
    return panel()[name]


def get_background_collection(name: str):
    return panel()[name]


def get_ai_collection(name: str):
    return panel()[name]


def get_pool_stats() -> dict:
    """Kept for callers that report pool stats. Pools no longer exist."""
    return {"note": "per-workload pools retired; all handles share the client in database.py"}

