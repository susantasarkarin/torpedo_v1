"""
Credential and Session — the authentication boundary's own persisted state.

Deliberately minimal identity: `user_id` here is an opaque string, not a foreign key
into a `Person` collection that doesn't exist yet (Person/Account land in the next
slice). Wiring authentication to a real Person record is that slice's job, not this
one's — this module only needs to know "this credential belongs to this user_id" and
"this session was issued to this user_id."
"""

from __future__ import annotations

from datetime import datetime

from app.models.base import CanonicalDocument


class Credential(CanonicalDocument):
    user_id: str
    password_hash: str


class Session(CanonicalDocument):
    """
    `org_id` (inherited from CanonicalDocument) is informational only, captured at
    creation time — it is NEVER read by any authorization decision. The chain this
    module implements is deliberately:

        credential -> verified session -> user_id -> RBACService.resolve_identity()
        -> ResolvedIdentity (carrying the *authoritative*, freshly-resolved org_id)
        -> permission decision

    not "trust whatever org/role claims the token carries." A session carries only a
    `user_id` (plus principal type and impersonation/revocation state) — nothing an
    authorization decision would use is ever read off this document directly, so a
    stale or tampered session field can't desync from the canonical RBAC records the
    way v1's various trust boundaries did.
    """

    user_id: str
    principal_type: str  # "user" | "ai_agent" | "system" — see app.rbac.identity.PrincipalType
    token_hash: str
    expires_at: datetime
    revoked_at: datetime | None = None

    # Set only on an impersonation session: the real human/service behind it. See
    # RBACService.can_approve() — impersonation must never be able to satisfy a
    # separation-of-duties check, which is why this is threaded through as
    # ResolvedIdentity.real_actor_id rather than being invisible after this point.
    impersonated_by: str | None = None
