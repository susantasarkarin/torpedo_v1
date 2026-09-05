"""
The FastAPI wiring for the full request security chain:

    Authorization header -> AuthService.verify_token() -> Session.user_id
    -> RBACService.resolve_identity() -> ResolvedIdentity -> permission decision

This is the module that actually closes D-01 end-to-end, not just at the service
layer: `get_current_identity()` is the only way a route in this codebase obtains an
identity, and it contains no code path that can produce one without a verified
session backing it — there is no default identity, no header the caller can set to
assert who they are, and no way to skip straight to `ResolvedIdentity` without a
token that `AuthService` has actually verified.

401 vs 403 is enforced as two distinct exception types raised at two distinct points:
`get_current_identity()` can only ever raise 401 (authentication failed — there is no
valid caller). `require_permission()` can only ever raise 403 (a real, authenticated
caller who isn't allowed to do this one thing). A route cannot accidentally blur the
two by construction, because they're different dependencies.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from app.auth.models import Credential, Session
from app.auth.service import AuthenticationFailed, AuthService
from app.db import get_database
from app.models.base import CanonicalRepository
from app.rbac.identity import ResolvedIdentity
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.service import RBACService

from app.config import get_settings


def get_auth_service() -> AuthService:
    db = get_database()
    settings = get_settings()
    return AuthService(
        credentials=CanonicalRepository(db["credentials"], Credential),
        sessions=CanonicalRepository(db["sessions"], Session),
        default_org_id=settings.default_org_id,
    )


def get_rbac_service() -> RBACService:
    db = get_database()
    return RBACService(
        user_roles=CanonicalRepository(db["user_roles"], UserRole),
        roles=CanonicalRepository(db["roles"], Role),
        approval_authorities=CanonicalRepository(db["approval_authorities"], ApprovalAuthority),
    )


async def get_current_identity(
    authorization: str | None = Header(default=None),
    auth_service: AuthService = Depends(get_auth_service),
    rbac_service: RBACService = Depends(get_rbac_service),
) -> ResolvedIdentity:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or malformed Authorization header")
    raw_token = authorization.removeprefix("Bearer ").strip()

    try:
        session = await auth_service.verify_token(raw_token)
    except AuthenticationFailed as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    return await rbac_service.resolve_identity(
        session.user_id,
        principal_type=session.principal_type,  # type: ignore[arg-type]
        real_actor_id=session.impersonated_by or session.user_id,
    )


def require_permission(code: str):
    """
    Dependency factory: `Depends(require_permission("finance.invoice.create"))`.
    Checked against the resolved identity's own org — a resource-specific org check
    (e.g. "does *this* invoice's org match the caller's") belongs at the resource
    endpoint once resources with their own org_id exist; this generic dependency only
    knows about the caller, not about any particular target document yet.
    """

    async def dependency(
        identity: ResolvedIdentity = Depends(get_current_identity),
        rbac_service: RBACService = Depends(get_rbac_service),
    ) -> ResolvedIdentity:
        if not rbac_service.has_permission(identity, code, target_org_id=identity.org_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing permission: {code}")
        return identity

    return dependency
