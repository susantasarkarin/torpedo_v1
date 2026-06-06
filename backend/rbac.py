"""
DEPRECATED — DO NOT USE.

This module is shadowed at import time by the `rbac/` package that sits in the
same directory (Python resolves `import rbac` to the package, never this file),
so its contents are unreachable. It previously held a small duplicate role/permission
stub (ROLES, can, has_role). That logic now lives canonically in the package:

    from rbac import can, has_role, SIMPLE_ROLES   # coarse helpers (was here)
    from rbac import require_permission, Permissions  # full permission system

The file is intentionally kept (not deleted) to preserve history and to make the
collision/deprecation explicit for anyone who finds it. If you somehow import it
directly by path, it re-exports the canonical helpers.
"""

try:  # pragma: no cover - only reachable via direct path import
    from rbac.simple import can, has_role, SIMPLE_ROLES as ROLES
except Exception:  # pragma: no cover
    # Last-resort inline fallback mirroring rbac.simple, so direct path imports
    # never crash. The package version is authoritative.
    ROLES = {
        "admin": {"can": ["*"]},
        "manager": {"can": ["read", "write", "approve"]},
        "user": {"can": ["read", "write"]},
        "viewer": {"can": ["read"]},
    }

    def has_role(user: dict, role: str) -> bool:
        return bool(user) and role in (user.get("roles") or [])

    def can(user: dict, action: str) -> bool:
        if not user:
            return False
        for r in user.get("roles", []) or []:
            perms = ROLES.get(r, {}).get("can", [])
            if "*" in perms or action in perms:
                return True
        return False
