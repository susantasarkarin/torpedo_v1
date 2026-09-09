"""
HTTP-level tests for the login/logout endpoints — the piece that used to not
exist at all (app.auth.routers). Through the real wired app, same pattern as
every other router's HTTP-level test file. Service-level authentication
behavior (lockout, session lifecycle, impersonation) is exhaustively covered
in test_auth_service.py; this file proves the HTTP surface on top of it.
"""

from datetime import timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.auth.dependencies import get_auth_service, get_rbac_service
from app.auth.models import Credential, Session
from app.auth.service import MAX_FAILED_ATTEMPTS, AuthService
from app.main import app
from app.models.base import CanonicalRepository
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.service import RBACService

ORG = "torpedo"


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def auth_service(db) -> AuthService:
    return AuthService(credentials=CanonicalRepository(db["credentials"], Credential), sessions=CanonicalRepository(db["sessions"], Session), default_org_id=ORG)


@pytest.fixture
def rbac_service(db) -> RBACService:
    return RBACService(user_roles=CanonicalRepository(db["user_roles"], UserRole), roles=CanonicalRepository(db["roles"], Role), approval_authorities=CanonicalRepository(db["approval_authorities"], ApprovalAuthority))


@pytest.fixture
def client(auth_service, rbac_service) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_with_correct_credentials_returns_a_real_bearer_token(client: TestClient, auth_service: AuthService):
    await auth_service.set_password("alice", "correct-horse-battery")

    resp = client.post("/api/v1/auth/login", json={"user_id": "alice", "password": "correct-horse-battery"})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["token"]) > 20
    assert body["user_id"] == "alice"
    assert "expires_at" in body


@pytest.mark.asyncio
async def test_the_returned_token_actually_authenticates_a_real_request(client: TestClient, auth_service: AuthService, rbac_service: RBACService):
    """The strongest proof available: log in through HTTP, then use the
    returned token on a real permission-gated endpoint — the same
    authenticate() -> resolve_identity() -> permission chain any real client
    would exercise."""
    await auth_service.set_password("alice", "correct-horse-battery")
    await rbac_service._roles.insert(Role(org_id=ORG, created_by="seed", updated_by="seed", code="role-alice", name="role-alice", permissions=["ai.read"]))
    await rbac_service._user_roles.insert(UserRole(org_id=ORG, created_by="seed", updated_by="seed", user_id="alice", role_code="role-alice"))

    login_resp = client.post("/api/v1/auth/login", json={"user_id": "alice", "password": "correct-horse-battery"})
    token = login_resp.json()["token"]

    resp = client.get("/api/v1/ai/gpu/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_login_with_wrong_password_is_401(client: TestClient, auth_service: AuthService):
    await auth_service.set_password("alice", "correct-horse-battery")

    resp = client.post("/api/v1/auth/login", json={"user_id": "alice", "password": "wrong-password"})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid credentials"


@pytest.mark.asyncio
async def test_login_with_unknown_user_gives_the_same_response_as_wrong_password(client: TestClient, auth_service: AuthService):
    """No user-enumeration oracle at the HTTP layer either — same status
    code and same body for both failure modes."""
    await auth_service.set_password("alice", "correct-horse-battery")

    unknown_resp = client.post("/api/v1/auth/login", json={"user_id": "nobody", "password": "anything"})
    wrong_password_resp = client.post("/api/v1/auth/login", json={"user_id": "alice", "password": "wrong-password"})

    assert unknown_resp.status_code == wrong_password_resp.status_code == 401
    assert unknown_resp.json() == wrong_password_resp.json()


@pytest.mark.asyncio
async def test_login_with_missing_fields_is_422_not_500(client: TestClient):
    resp = client.post("/api/v1/auth/login", json={"user_id": "alice"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_repeated_failed_logins_lock_the_account_through_http(client: TestClient, auth_service: AuthService):
    await auth_service.set_password("alice", "correct-horse-battery")

    for _ in range(MAX_FAILED_ATTEMPTS):
        resp = client.post("/api/v1/auth/login", json={"user_id": "alice", "password": "wrong-password"})
        assert resp.status_code == 401

    # Correct password now also fails — the account is locked, not just still counting.
    locked_resp = client.post("/api/v1/auth/login", json={"user_id": "alice", "password": "correct-horse-battery"})
    assert locked_resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_the_session(client: TestClient, auth_service: AuthService):
    await auth_service.set_password("alice", "correct-horse-battery")
    login_resp = client.post("/api/v1/auth/login", json={"user_id": "alice", "password": "correct-horse-battery"})
    token = login_resp.json()["token"]

    logout_resp = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_resp.status_code == 204

    # The same token no longer authenticates anything.
    resp = client.get("/api/v1/ai/gpu/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_with_no_token_is_a_harmless_no_op(client: TestClient):
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_logout_with_a_garbage_token_is_a_harmless_no_op(client: TestClient):
    resp = client.post("/api/v1/auth/logout", headers={"Authorization": "Bearer this-was-never-issued"})
    assert resp.status_code == 204
