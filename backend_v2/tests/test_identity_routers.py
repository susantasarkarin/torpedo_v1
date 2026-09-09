"""
Identity routers exercised through the real, wired app (`app.main.app`) — not a
throwaway test app — with only the database-touching dependencies overridden. This
is the strongest available proof that Person/Account sit correctly behind the full
security chain built in Slices 2-3, including the org-isolation property that only
becomes observable once real HTTP requests carry a real Authorization header.
"""

from datetime import timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.auth.dependencies import get_auth_service, get_rbac_service
from app.auth.models import Credential, Session
from app.auth.service import AuthService
from app.identity.models import Account, AccountBrandRelationship, Person
from app.identity.routers import get_identity_service
from app.identity.service import IdentityService
from app.main import app
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import ACCOUNT_CREATE, ACCOUNT_MERGE, ACCOUNT_READ, PERSON_CREATE, PERSON_READ, PERSON_RESOLVE
from app.rbac.service import RBACService

ORG_A = "org-A"
ORG_B = "org-B"


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def auth_service(db) -> AuthService:
    return AuthService(
        credentials=CanonicalRepository(db["credentials"], Credential),
        sessions=CanonicalRepository(db["sessions"], Session),
        default_org_id=ORG_A,
    )


@pytest.fixture
def rbac_service(db) -> RBACService:
    return RBACService(
        user_roles=CanonicalRepository(db["user_roles"], UserRole),
        roles=CanonicalRepository(db["roles"], Role),
        approval_authorities=CanonicalRepository(db["approval_authorities"], ApprovalAuthority),
    )


@pytest.fixture
def identity_service(db) -> IdentityService:
    return IdentityService(
        people=CanonicalRepository(db["people"], Person),
        accounts=CanonicalRepository(db["accounts"], Account),
        brand_relationships=CanonicalRepository(db["account_brand_relationships"], AccountBrandRelationship),
        activities=CanonicalRepository(db["activities"], Activity),
    )


@pytest.fixture
def client(auth_service, rbac_service, identity_service) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_identity_service] = lambda: identity_service
    yield TestClient(app)
    app.dependency_overrides.clear()


async def _make_authenticated_user(
    auth_service: AuthService, rbac_service: RBACService, *, user_id: str, org_id: str, permissions: list[str]
) -> str:
    """Seeds a role with the given permissions, grants it, sets a password, logs in,
    and returns the bearer token — the setup every permission-gated test needs."""
    role_code = f"role-{user_id}"
    await rbac_service._roles.insert(
        Role(org_id=org_id, created_by="seed", updated_by="seed", code=role_code, name=role_code, permissions=permissions)
    )
    await rbac_service._user_roles.insert(
        UserRole(org_id=org_id, created_by="seed", updated_by="seed", user_id=user_id, role_code=role_code)
    )
    await auth_service.set_password(user_id, "correct-horse-battery")
    _, token = await auth_service.authenticate(user_id, "correct-horse-battery")
    return token


@pytest.mark.asyncio
async def test_create_person_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(
        auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[]
    )

    resp = client.post(
        "/api/v1/people", json={"primary_email": "carol@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_and_read_person_with_permission_succeeds(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(
        auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[PERSON_CREATE, PERSON_READ]
    )

    create_resp = client.post(
        "/api/v1/people", json={"primary_email": "carol@example.com", "given_name": "Carol"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_resp.status_code == 200
    person_id = create_resp.json()["id"]

    read_resp = client.get(f"/api/v1/people/{person_id}", headers={"Authorization": f"Bearer {token}"})
    assert read_resp.status_code == 200
    assert read_resp.json()["primary_email"] == "carol@example.com"


@pytest.mark.asyncio
async def test_org_isolation_through_the_actual_http_security_chain(client: TestClient, auth_service, rbac_service):
    """The scenario named explicitly: a person created under org A must be
    unreachable by a fully-authenticated, fully-permissioned user whose own
    identity resolves to org B — proven through real HTTP requests with real
    bearer tokens, not by calling the service layer directly."""
    alice_token = await _make_authenticated_user(
        auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[PERSON_CREATE, PERSON_READ]
    )
    bob_token = await _make_authenticated_user(
        auth_service, rbac_service, user_id="bob", org_id=ORG_B, permissions=[PERSON_READ]
    )

    create_resp = client.post(
        "/api/v1/people", json={"primary_email": "carol@example.com"},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    person_id = create_resp.json()["id"]

    bob_read_resp = client.get(f"/api/v1/people/{person_id}", headers={"Authorization": f"Bearer {bob_token}"})

    assert bob_read_resp.status_code == 404  # not 403 — see routers.py's comment on why


@pytest.mark.asyncio
async def test_resolve_person_endpoint_end_to_end(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(
        auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[PERSON_RESOLVE]
    )

    first = client.post(
        "/api/v1/people/resolve", json={"email": "dana@example.com", "name": "Dana Diaz"},
        headers={"Authorization": f"Bearer {token}"},
    )
    second = client.post(
        "/api/v1/people/resolve", json={"email": "dana@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert first.json()["is_new"] is True
    assert second.json()["is_new"] is False
    assert second.json()["person_id"] == first.json()["person_id"]


@pytest.mark.asyncio
async def test_merge_endpoint_requires_permission(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(
        auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[ACCOUNT_CREATE]
    )
    a = client.post("/api/v1/accounts", json={"name": "Acme"}, headers={"Authorization": f"Bearer {token}"}).json()
    b = client.post("/api/v1/accounts", json={"name": "Acme Dup"}, headers={"Authorization": f"Bearer {token}"}).json()

    resp = client.post(
        "/api/v1/accounts/merge", json={"primary_id": a["id"], "duplicate_id": b["id"]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_merge_endpoint_end_to_end_succeeds(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(
        auth_service, rbac_service, user_id="alice", org_id=ORG_A,
        permissions=[ACCOUNT_CREATE, ACCOUNT_READ, ACCOUNT_MERGE],
    )
    a = client.post("/api/v1/accounts", json={"name": "Acme"}, headers={"Authorization": f"Bearer {token}"}).json()
    b = client.post("/api/v1/accounts", json={"name": "Acme Dup"}, headers={"Authorization": f"Bearer {token}"}).json()

    merge_resp = client.post(
        "/api/v1/accounts/merge", json={"primary_id": a["id"], "duplicate_id": b["id"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert merge_resp.status_code == 200

    loser_resp = client.get(f"/api/v1/accounts/{b['id']}", headers={"Authorization": f"Bearer {token}"})
    assert loser_resp.json()["status"] == "merged"
    assert loser_resp.json()["merged_into"] == a["id"]


@pytest.mark.asyncio
async def test_merging_another_orgs_account_through_http_is_400_not_a_cross_tenant_merge(client: TestClient, auth_service, rbac_service):
    """Phase 15 security audit finding (found in a later pass than the rest
    of that sweep): merge_accounts() had no org_id parameter at all — a
    caller in ORG_A with ACCOUNT_MERGE could name a duplicate_id belonging
    to ORG_B, repointing that org's data onto the attacker's own account
    and marking the victim's real Account merged out from under it."""
    org_b_token = await _make_authenticated_user(auth_service, rbac_service, user_id="bob", org_id=ORG_B, permissions=[ACCOUNT_CREATE, ACCOUNT_READ])
    victim = client.post("/api/v1/accounts", json={"name": "Victim Co"}, headers={"Authorization": f"Bearer {org_b_token}"}).json()

    attacker_token = await _make_authenticated_user(auth_service, rbac_service, user_id="mallory", org_id=ORG_A, permissions=[ACCOUNT_CREATE, ACCOUNT_MERGE])
    primary = client.post("/api/v1/accounts", json={"name": "Attacker Co"}, headers={"Authorization": f"Bearer {attacker_token}"}).json()

    resp = client.post(
        "/api/v1/accounts/merge", json={"primary_id": primary["id"], "duplicate_id": victim["id"]},
        headers={"Authorization": f"Bearer {attacker_token}"},
    )
    assert resp.status_code == 400

    untouched = client.get(f"/api/v1/accounts/{victim['id']}", headers={"Authorization": f"Bearer {org_b_token}"})
    assert untouched.json()["status"] == "active"
    assert untouched.json()["merged_into"] is None
