"""
Persisted RBAC entities. Each is a CanonicalDocument — role/grant/approval-authority
data goes through the same insert/update path (I-6) as every other entity in v2, with
no carve-out for "this is infrastructure, not business data."
"""

from __future__ import annotations

from app.models.base import CanonicalDocument
from app.models.money import Money


class Role(CanonicalDocument):
    code: str
    name: str
    # Explicit permission codes, or the single wildcard sentinel (`permissions.ADMIN_WILDCARD`)
    # — never "codes plus a comment describing what else it implicitly grants." That pattern
    # is exactly how v1's admin wildcard silently picked up approval authority it was never
    # meant to have.
    permissions: list[str]


class UserRole(CanonicalDocument):
    """A role grant, scoped to the org it was granted in — `org_id` is inherited from
    CanonicalDocument and is the org-boundary enforcement point (RBACService.has_permission)."""

    user_id: str
    role_code: str


class ApprovalAuthority(CanonicalDocument):
    """A per-user or per-role ceiling for one entity type. `user_id` and `role_code`
    are mutually exclusive by convention, not by a stored discriminant — a ceiling
    belongs to a person or to everyone holding a role, never silently to both."""

    user_id: str | None = None
    role_code: str | None = None
    entity_type: str
    max_amount: Money
