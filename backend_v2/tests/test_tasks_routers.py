"""
HTTP-level Task tests, through the real wired app. Permission enforcement and
org isolation are what's new at this layer — creation/transition/listing
behavior is exhaustively covered in test_tasks_service.py.
"""

from datetime import timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.auth.dependencies import get_auth_service, get_rbac_service
from app.auth.models import Credential, Session
from app.auth.service import AuthService
from app.main import app
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import TASK_CREATE, TASK_MANAGE, TASK_READ
from app.rbac.service import RBACService
from app.tasks.models import Task
from app.tasks.routers import get_task_service
from app.tasks.service import TaskService

ORG_A = "org-A"
ORG_B = "org-B"


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def auth_service(db) -> AuthService:
    return AuthService(credentials=CanonicalRepository(db["credentials"], Credential), sessions=CanonicalRepository(db["sessions"], Session), default_org_id=ORG_A)


@pytest.fixture
def rbac_service(db) -> RBACService:
    return RBACService(user_roles=CanonicalRepository(db["user_roles"], UserRole), roles=CanonicalRepository(db["roles"], Role), approval_authorities=CanonicalRepository(db["approval_authorities"], ApprovalAuthority))


@pytest.fixture
def task_service(db) -> TaskService:
    return TaskService(CanonicalRepository(db["tasks"], Task), CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def client(auth_service, rbac_service, task_service) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_task_service] = lambda: task_service
    yield TestClient(app)
    app.dependency_overrides.clear()


async def _make_authenticated_user(auth_service, rbac_service, *, user_id: str, org_id: str, permissions: list[str]) -> str:
    role_code = f"role-{user_id}"
    await rbac_service._roles.insert(Role(org_id=org_id, created_by="seed", updated_by="seed", code=role_code, name=role_code, permissions=permissions))
    await rbac_service._user_roles.insert(UserRole(org_id=org_id, created_by="seed", updated_by="seed", user_id=user_id, role_code=role_code))
    await auth_service.set_password(user_id, "correct-horse-battery")
    _, token = await auth_service.authenticate(user_id, "correct-horse-battery")
    return token


@pytest.mark.asyncio
async def test_create_task_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.post("/api/v1/tasks", json={"title": "Follow up"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_full_task_lifecycle_through_http(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[TASK_CREATE, TASK_READ, TASK_MANAGE])

    create_resp = client.post("/api/v1/tasks", json={"title": "Chase invoice", "priority": "HIGH"}, headers={"Authorization": f"Bearer {token}"})
    assert create_resp.status_code == 200
    task = create_resp.json()
    task_id = task.get("id") or task.get("_id")
    assert task["status"] == "OPEN"

    list_resp = client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {token}"})
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    complete_resp = client.post(f"/api/v1/tasks/{task_id}/complete", headers={"Authorization": f"Bearer {token}"})
    assert complete_resp.status_code == 200
    assert complete_resp.json()["status"] == "DONE"

    list_after = client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {token}"})
    assert list_after.json() == []  # no longer open


@pytest.mark.asyncio
async def test_cancel_endpoint_records_the_reason(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[TASK_CREATE, TASK_MANAGE])
    task = client.post("/api/v1/tasks", json={"title": "x"}, headers={"Authorization": f"Bearer {token}"}).json()
    task_id = task.get("id") or task.get("_id")

    resp = client.post(f"/api/v1/tasks/{task_id}/cancel", json={"reason": "no longer needed"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"
    assert resp.json()["cancel_reason"] == "no longer needed"


@pytest.mark.asyncio
async def test_cross_org_task_read_is_404_not_403(client: TestClient, auth_service, rbac_service):
    alice_token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[TASK_CREATE])
    bob_token = await _make_authenticated_user(auth_service, rbac_service, user_id="bob", org_id=ORG_B, permissions=[TASK_READ])

    task = client.post("/api/v1/tasks", json={"title": "x"}, headers={"Authorization": f"Bearer {alice_token}"}).json()
    task_id = task.get("id") or task.get("_id")

    bob_resp = client.get(f"/api/v1/tasks/{task_id}", headers={"Authorization": f"Bearer {bob_token}"})
    assert bob_resp.status_code == 404


@pytest.mark.asyncio
async def test_completing_another_orgs_task_through_http_is_400_not_a_cross_tenant_write(client: TestClient, auth_service, rbac_service):
    org_b_token = await _make_authenticated_user(auth_service, rbac_service, user_id="bob", org_id=ORG_B, permissions=[TASK_CREATE, TASK_READ])
    org_b_task = client.post("/api/v1/tasks", json={"title": "victim's task"}, headers={"Authorization": f"Bearer {org_b_token}"}).json()
    org_b_task_id = org_b_task.get("id") or org_b_task.get("_id")

    attacker_token = await _make_authenticated_user(auth_service, rbac_service, user_id="mallory", org_id=ORG_A, permissions=[TASK_MANAGE])
    resp = client.post(f"/api/v1/tasks/{org_b_task_id}/complete", headers={"Authorization": f"Bearer {attacker_token}"})
    assert resp.status_code == 400

    untouched = client.get(f"/api/v1/tasks/{org_b_task_id}", headers={"Authorization": f"Bearer {org_b_token}"})
    assert untouched.json()["status"] == "OPEN"


@pytest.mark.asyncio
async def test_task_create_permission_does_not_grant_manage(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[TASK_CREATE])
    task = client.post("/api/v1/tasks", json={"title": "x"}, headers={"Authorization": f"Bearer {token}"}).json()
    task_id = task.get("id") or task.get("_id")

    resp = client.post(f"/api/v1/tasks/{task_id}/complete", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
