"""
ResolvedIdentity — what a verified caller actually is, after role resolution.

This is the object D-01's bug produced incorrectly. v1's operative resolver, given ANY
successfully-verified session token, returned `roles: ["admin"]` unconditionally,
never consulting the database (`rbac/decorators.py:89-107`). Two other resolvers in
the same codebase did it correctly — looked up real roles, defaulted to `["user"]` —
but nothing routed requests to them consistently, so the broken one was the operative
path for the app's normal auth mechanism.

There is no default-to-admin code path anywhere in this module or in
`RBACService.resolve_identity()`. An identity with zero `UserRole` grants resolves to
zero permissions — a fully-supported, deny-by-default state, not an error swallowed
into an implicit grant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PrincipalType = Literal["user", "ai_agent", "system"]


@dataclass(frozen=True)
class ResolvedIdentity:
    user_id: str
    org_id: str
    principal_type: PrincipalType
    roles: frozenset[str]
    permissions: frozenset[str]

    # The real human behind the request, ignoring impersonation. Equal to `user_id`
    # unless an impersonation session is active. Approval/self-approval checks use
    # this field, never `user_id` — register §5.7: "impersonation cannot be used to
    # satisfy a separation-of-duties requirement."
    real_actor_id: str

    @property
    def is_ai_agent(self) -> bool:
        return self.principal_type == "ai_agent"
