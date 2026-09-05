"""
Activity — the one canonical, append-only audit stream.

v1 had four competing audit stores: two collections both literally named `audit_log`
in different databases (both live), plus two orphaned governance logs that were
write-only and never read (entity_map.md §2.7). Every domain slice in v2 writes
resolution/state-change/decision records to *this* collection — no domain gets its
own audit table. That's I-1 applied to observability, the same way `RBACService` is
I-1 applied to authorization.
"""

from __future__ import annotations

from app.models.base import CanonicalDocument


class Activity(CanonicalDocument):
    type: str
    subject_type: str
    subject_id: str
    actor_type: str  # "user" | "system" | "ai_agent" — mirrors rbac.identity.PrincipalType
    actor_id: str
    payload: dict = {}
