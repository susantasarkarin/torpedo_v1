"""
Startup self-checks: prove the app came up whole before it serves traffic.

Two problems this closes.

ROUTE MANIFEST (TOR-05)
-----------------------
Router mounts now raise instead of printing a warning, but two mount sites
legitimately stay tolerant because they also do database setup (the Cint and
CPX blocks in main.py) — a Mongo hiccup there should not kill the process, yet
its router going missing still must not pass unnoticed. And a router can mount
"successfully" while registering nothing at all.

So after every mount, assert the paths that must exist. A missing prefix is a
hard failure: the deploy's health poll hits /docs, which returns 200 on a
half-loaded app, so this is the only thing standing between a broken deploy and
a silently missing module.

INDEX VISIBILITY (TOR-09)
-------------------------
`indexes.py` holds 576 lines of index definitions that nothing ever calls, so
what production actually has has never been verified. The obvious fix — call
setup_indexes() on startup — is the one thing we must NOT do by default, and
main.py said so: on MongoDB 4.2+ `background=True` is ignored, so 130+
foreground builds would lock collections for minutes on every boot.

The gap was never really "indexes aren't created", it was "nobody knows". So
the default is a read-only audit on a background thread: compare the expected
index set against `index_information()` and log what's missing at WARNING.
Creation stays opt-in via AUTO_CREATE_INDEXES=true, and even then runs off the
event loop so a long build never blocks request handling.
"""

import logging
import os
import threading

logger = logging.getLogger(__name__)

# Path prefixes that MUST be routable for the app to be considered whole.
# Keep this list honest: adding a router without adding its prefix here means
# the guard cannot catch that router disappearing.
REQUIRED_ROUTE_PREFIXES = (
    "/login",
    "/logout",
    "/profile",
    "/api/crm",
    "/finance",
    "/panel",
    "/api/panel-admin",
    "/leads",
    "/sales",
    "/api/operations",
    "/api/projects",
    "/campaigns",
    "/api/cint",
    "/cpx",
    "/settings",
    "/users",
    "/roles",
    "/health",
)


def assert_routes_mounted(app, required=REQUIRED_ROUTE_PREFIXES) -> int:
    """
    Verify every required prefix has at least one registered route.

    Raises RuntimeError listing everything missing — one error naming all the
    gaps beats restarting into the next one at a time.
    """
    paths = [getattr(r, "path", "") for r in app.routes]
    missing = [p for p in required if not any(path.startswith(p) for path in paths)]
    if missing:
        raise RuntimeError(
            "Startup route manifest check FAILED — the application is only "
            f"partially loaded. Unroutable prefixes: {', '.join(missing)}. "
            f"({len(paths)} routes registered.) Refusing to serve; the previous "
            "release is still running and should stay that way until this is fixed."
        )
    logger.info("route manifest OK — %d routes, all %d required prefixes present",
                len(paths), len(required))
    return len(paths)


# ---------------------------------------------------------------------------
# Index audit
# ---------------------------------------------------------------------------
def _audit_indexes() -> None:
    """Report (and optionally create) the indexes defined in indexes.py."""
    auto_create = os.getenv("AUTO_CREATE_INDEXES", "false").strip().lower() in (
        "1", "true", "yes", "on")

    if auto_create:
        logger.warning(
            "AUTO_CREATE_INDEXES=true — building indexes now. On MongoDB 4.2+ "
            "background:true is ignored, so large collections WILL lock during "
            "the build. This runs off the event loop, but Mongo itself is the "
            "bottleneck; prefer running `python indexes.py` in a maintenance "
            "window instead."
        )
        try:
            try:
                from indexes import setup_indexes
            except ImportError:
                from .indexes import setup_indexes
            setup_indexes()
            logger.info("index creation pass complete")
        except Exception:
            logger.exception("index creation failed")
        return

    # Default: read-only visibility.
    try:
        try:
            from database import get_client
        except ImportError:
            from .database import get_client
        client = get_client()
    except Exception:
        logger.warning("index audit skipped: no database client", exc_info=True)
        return

    # A small, high-value subset — the indexes whose absence actually costs
    # something today: the suppression uniqueness constraint that stops
    # duplicate suppression rows, and the fields the CRM list/search endpoint
    # filters and regex-scans on every request.
    expected = {
        ("email_automation", "suppression_list"): ["email"],
        ("email_automation", "leads_enriched"): ["email"],
        ("email_automation", "leads_raw"): ["email"],
        ("crm_db", "accounts"): ["name_normalized"],
        ("crm_db", "contacts"): ["email"],
        ("crm_db", "activities"): ["account_id"],
        ("crm_db", "opportunities"): ["stage"],
        ("campaign_platform", "panelists"): ["email"],
    }

    missing = []
    for (dbname, colname), fields in expected.items():
        try:
            info = client[dbname][colname].index_information()
        except Exception:
            continue
        indexed = {k[0] for spec in info.values() for k in spec.get("key", [])}
        for field in fields:
            if field not in indexed:
                missing.append(f"{dbname}.{colname}.{field}")

    if missing:
        logger.warning(
            "MISSING INDEXES (%d): %s — queries on these fields are collection "
            "scans. Fix with `python indexes.py` in a maintenance window, or set "
            "AUTO_CREATE_INDEXES=true to build them at the next restart.",
            len(missing), ", ".join(missing),
        )
    else:
        logger.info("index audit OK — all %d checked indexes present",
                    sum(len(v) for v in expected.values()))


def audit_indexes_async() -> None:
    """Kick the index audit onto a daemon thread; never blocks startup."""
    threading.Thread(target=_audit_indexes, name="index-audit", daemon=True).start()
