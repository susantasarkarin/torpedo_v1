"""
RBAC enforcement flag — the single reader of RBAC_ENABLED.

There used to be two. `app/security.py` defaulted it to "false" (coarse
capability gates open) while `rbac/decorators.py` defaulted it to "true"
(fine-grained permission gates closed). Same variable, opposite meanings, so
setting it moved the two subsystems in opposite directions from whatever the
operator intended — and leaving it unset meant the app was simultaneously
wide open on one layer and, on any route using the decorators, refusing every
user without a seeded role. See TOR-04.

Both now call `rbac_enabled()` here.

Default is OFF, deliberately. Turning enforcement on before roles are seeded
locks everyone out of the decorator-gated routes; the ordering is:

    1. python -m scripts.seed_rbac_roles --dry-run    # see who gets what
    2. python -m scripts.seed_rbac_roles              # write roles
    3. RBAC_ENABLED=true + restart

The value is read on every call, not captured at import, so tests and a
runtime toggle both work without reloading modules.
"""

import os

_TRUTHY = ("1", "true", "yes", "on")


def rbac_enabled() -> bool:
    """True when RBAC enforcement is switched on. Default: off."""
    return os.getenv("RBAC_ENABLED", "false").strip().lower() in _TRUTHY


def rbac_log_checks() -> bool:
    """True when every permission check should be logged (noisy; debug aid)."""
    return os.getenv("RBAC_LOG_CHECKS", "false").strip().lower() in _TRUTHY
