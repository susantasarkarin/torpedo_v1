"""
HTTP-level AI Gateway tests. Permission enforcement is what's new at this layer;
broker behavior is exhaustively covered in test_ai_gpu_broker.py.
"""

from datetime import timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.ai.gpu_broker import GpuBroker
from app.ai.routers import get_gpu_broker
from app.auth.dependencies import get_auth_service, get_rbac_service
from app.auth.models import Credential, Session
from app.auth.service import AuthService
from app.main import app
from app.models.base import CanonicalRepository
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import AI_ADMIN, AI_READ
from app.rbac.service import RBACService

ORG_A = "org-A"


class FakeCollection:
    def __init__(self):
        self.doc = None

    async def find_one(self, query):
        return dict(self.doc) if self.doc else None

    async def update_one(self, query, update, upsert=False):
        class Result:
            modified_count = 1
            upserted_id = None

        if self.doc is None and upsert:
            self.doc = {"_id": "active", **update.get("$set", {})}
        else:
            self.doc.update(update.get("$set", {}))
        return Result()

    async def delete_one(self, query):
        self.doc = None


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
def broker() -> GpuBroker:
    return GpuBroker(FakeCollection())


@pytest.fixture
def client(auth_service, rbac_service, broker) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_gpu_broker] = lambda: broker
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
async def test_gpu_status_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.get("/api/v1/ai/gpu/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_gpu_status_reports_off_when_nothing_registered(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[AI_READ])
    resp = client.get("/api/v1/ai/gpu/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "off"


@pytest.mark.asyncio
async def test_gpu_read_permission_does_not_grant_shutdown(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[AI_READ])
    resp = client.post("/api/v1/ai/gpu/shutdown", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_shutdown(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[AI_ADMIN])
    resp = client.post("/api/v1/ai/gpu/shutdown", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["action"] == "nothing-running"
