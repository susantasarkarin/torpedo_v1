"""
Route authorization for the CRM/AI API layer.

Builds on the canonical session auth (main.verify_session) and the unified RBAC
package's coarse capability helper (rbac.can: read/write/approve). Provides a
`require(capability)` FastAPI dependency the /api/crm and /api/ai routers use.

SAFE-BY-DEFAULT: enforcement is OPT-IN via the RBAC_ENABLED env var (default
off). When off, any authenticated user passes — so adding these checks to a live
system never locks anyone out. Enable it (RBAC_ENABLED=true) once user roles are
seeded. The full permission system (rbac.permissions / RBACService) remains
available for finer-grained control later.
"""

import os
from typing import Optional

from fastapi import Request, HTTPException

try:
    from ..database import get_database
    from ..rbac import can
except ImportError:  # pragma: no cover - absolute import fallback
    from database import get_database
    from rbac import can


def rbac_enabled() -> bool:
    """Read at call time so tests / runtime can toggle it."""
    return os.getenv("RBAC_ENABLED", "false").lower() in ("1", "true", "yes")


def is_allowed(user: dict, capability: Optional[str], enabled: Optional[bool] = None) -> bool:
    """
    Pure authorization decision (no I/O) — the unit-testable core.

    - enforcement disabled, or no capability required -> allow
    - otherwise defer to the coarse RBAC capability check (admin bypass via '*')
    """
    if enabled is None:
        enabled = rbac_enabled()
    if not enabled or capability is None:
        return True
    return can(user, capability)


def _user_roles(user_doc: Optional[dict]) -> list:
    if not user_doc:
        return ["user"]
    roles = user_doc.get("roles")
    if not roles:
        role = user_doc.get("role")
        roles = [role] if role else []
    return roles or ["user"]


async def _authenticated_user(request: Request) -> dict:
    """Resolve the current user (username + roles) via the canonical verifier."""
    try:
        from ..main import verify_session
    except ImportError:  # pragma: no cover
        from main import verify_session

    username = await verify_session(request)  # raises 401 on bad/missing token
    try:
        users = get_database("email_automation")["users"]
        user_doc = users.find_one({"username": username})
    except Exception:
        user_doc = None
    return {"username": username, "roles": _user_roles(user_doc)}


def require(capability: Optional[str] = None):
    """
    Dependency factory. Returns a dependency that authenticates the request and,
    when RBAC is enabled, enforces the given coarse capability. Returns the
    username (so call sites that record the acting identity keep working).
    """

    async def dependency(request: Request) -> str:
        user = await _authenticated_user(request)
        if not is_allowed(user, capability):
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: requires '{capability}'",
            )
        return user["username"]

    return dependency
