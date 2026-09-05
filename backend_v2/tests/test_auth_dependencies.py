"""
End-to-end tests through actual HTTP requests, not direct function calls — this is
the strongest proof available that the full chain (Authorization header -> AuthService
-> RBACService -> route) is wired correctly, since it exercises exactly the path a
real client hits.

`test_d01_end_to_end_fresh_user_is_never_treated_as_admin` is the single test in this
whole slice that most directly answers "does this actually close D-01": it is the one
test that would have failed if run against a resolver shaped like v1's.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.auth.dependencies import get_auth_service, get_current_identity, get_rbac_service, require_permission
from app.auth.models import Credential, Session
from app.auth.service import AuthService
from app.models.base import CanonicalRepository
from app.rbac.identity import ResolvedIdentity
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.service import RBACService

ORG = "org-A"


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def auth_service(db) -> AuthService:
    return AuthService(
        credentials=CanonicalRepository(db["credentials"], Credential),
        sessions=CanonicalRepository(db["sessions"], Session),
        default_org_id=ORG,
    )


@pytest.fixture
def rbac_service(db) -> RBACService:
    return RBACService(
        user_roles=CanonicalRepository(db["user_roles"], UserRole),
        roles=CanonicalRepository(db["roles"], Role),
        approval_authorities=CanonicalRepository(db["approval_authorities"], ApprovalAuthority),
    )


@pytest.fixture
def client(auth_service: AuthService, rbac_service: RBACService) -> TestClient:
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(identity: ResolvedIdentity = Depends(get_current_identity)):
        return {"user_id": identity.user_id, "org_id": identity.org_id}

    @app.get("/protected")
    async def protected(identity: ResolvedIdentity = Depends(require_permission("person.read"))):
        return {"ok": True}

    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    return TestClient(app)


def test_no_authorization_header_is_401(client: TestClient):
    resp = client.get("/whoami")
    assert resp.status_code == 401


def test_malformed_authorization_header_is_401(client: TestClient):
    resp = client.get("/whoami", headers={"Authorization": "NotBearer xyz"})
    assert resp.status_code == 401


def test_garbage_token_is_401(client: TestClient):
    resp = client.get("/whoami", headers={"Authorization": "Bearer this-was-never-issued"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_resolves_identity_end_to_end(client: TestClient, auth_service: AuthService):
    await auth_service.set_password("alice", "correct-horse-battery")
    _, raw_token = await auth_service.authenticate("alice", "correct-horse-battery")

    resp = client.get("/whoami", headers={"Authorization": f"Bearer {raw_token}"})

    assert resp.status_code == 200
    assert resp.json()["user_id"] == "alice"


@pytest.mark.asyncio
async def test_expired_token_is_401_not_500(client: TestClient, auth_service: AuthService):
    await auth_service.set_password("alice", "correct-horse-battery")
    session, raw_token = await auth_service.authenticate("alice", "correct-horse-battery")
    await auth_service._sessions.update(
        session.id, session.version,
        {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
        updated_by="test",
    )

    resp = client.get("/whoami", headers={"Authorization": f"Bearer {raw_token}"})

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_revoked_token_is_401(client: TestClient, auth_service: AuthService):
    await auth_service.set_password("alice", "correct-horse-battery")
    _, raw_token = await auth_service.authenticate("alice", "correct-horse-battery")
    await auth_service.revoke_session(raw_token)

    resp = client.get("/whoami", headers={"Authorization": f"Bearer {raw_token}"})

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_authenticated_caller_without_permission_is_403_not_401(
    client: TestClient, auth_service: AuthService
):
    """A real, valid, non-expired session that simply lacks the permission must be
    403 — distinct from every 401 case above. Conflating the two would mean a caller
    can't tell "log in again" from "you're logged in but not allowed to do this,"
    which is exactly the ambiguity this slice's module docstring calls out."""
    await auth_service.set_password("alice", "correct-horse-battery")
    _, raw_token = await auth_service.authenticate("alice", "correct-horse-battery")

    resp = client.get("/protected", headers={"Authorization": f"Bearer {raw_token}"})

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_authenticated_caller_with_permission_succeeds(
    client: TestClient, auth_service: AuthService, rbac_service: RBACService
):
    await rbac_service._roles.insert(
        Role(org_id=ORG, created_by="seed", updated_by="seed", code="viewer", name="Viewer", permissions=["person.read"])
    )
    await rbac_service._user_roles.insert(
        UserRole(org_id=ORG, created_by="seed", updated_by="seed", user_id="alice", role_code="viewer")
    )
    await auth_service.set_password("alice", "correct-horse-battery")
    _, raw_token = await auth_service.authenticate("alice", "correct-horse-battery")

    resp = client.get("/protected", headers={"Authorization": f"Bearer {raw_token}"})

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_d01_end_to_end_fresh_user_is_never_treated_as_admin(
    client: TestClient, auth_service: AuthService
):
    """
    The actual v1 defect, reproduced and proven closed end-to-end: a real,
    successfully-verified session for a user with zero role grants must be refused a
    permission check, never silently granted admin. This is the one test in this
    entire slice that would have failed against a resolver shaped like v1's
    operative one (`rbac/decorators.py:89-107`, which returned `roles=["admin"]` for
    any verified token, unconditionally).
    """
    await auth_service.set_password("brand-new-user", "correct-horse-battery")
    _, raw_token = await auth_service.authenticate("brand-new-user", "correct-horse-battery")

    resp = client.get("/protected", headers={"Authorization": f"Bearer {raw_token}"})

    assert resp.status_code == 403
