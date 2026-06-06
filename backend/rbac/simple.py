"""
Simple coarse-grained role helpers.

These are lightweight convenience checks (read/write/approve style) that live
alongside the full permission-code system (see permissions.py / service.py).
They were previously duplicated in the now-deprecated top-level `backend/rbac.py`
stub, which Python silently shadowed with this package. The helpers are folded
in here so there is a single, reachable source of truth:

    from rbac import can, has_role, SIMPLE_ROLES

For real, granular authorization on endpoints prefer the permission system:

    from rbac import require_permission, Permissions
"""

from typing import List, Dict

# Coarse role -> allowed action map. "*" means all actions.
SIMPLE_ROLES: Dict[str, Dict[str, List[str]]] = {
    "admin": {"can": ["*"]},
    "manager": {"can": ["read", "write", "approve"]},
    "user": {"can": ["read", "write"]},
    "viewer": {"can": ["read"]},
}


def has_role(user: dict, role: str) -> bool:
    """True if the user has the given role code."""
    if not user:
        return False
    return role in (user.get("roles") or [])


def can(user: dict, action: str) -> bool:
    """
    Coarse action check against SIMPLE_ROLES.
    Admin (or any role granting '*') passes everything.
    """
    if not user:
        return False
    for role in user.get("roles", []) or []:
        perms = SIMPLE_ROLES.get(role, {}).get("can", [])
        if "*" in perms or action in perms:
            return True
    return False
