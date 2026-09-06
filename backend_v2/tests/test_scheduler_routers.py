"""
HTTP-level scheduler tests. `/internal/scheduler/tick` is not a Torpedo user
session — same signed, no-session pattern `/surveys/{id}/callback` already
established (test_panel_routers.py) — so this file proves the same three
outcomes for it (missing secret, bad signature, valid signature) plus the
normal permission-gated observability endpoint. Detection/dispatch mechanics
are already covered in test_scheduler_detectors.py/test_scheduler_orchestrator.py.
"""

import hashlib
import hmac as hmac_module
import json
from datetime import timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.auth.dependencies import get_auth_service, get_rbac_service
from app.auth.models import Credential, Session
from app.auth.service import AuthService
from app.main import app
from app.models.base import CanonicalRepository
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import SCHEDULER_READ
from app.rbac.service import RBACService
from app.scheduler.models import Event
from app.scheduler.orchestrator import EventOrchestrator
from app.scheduler.routers import get_event_orchestrator, get_events_repository, get_scheduler_signing_secret

ORG_A = "org-A"
SECRET = "scheduler-http-test-secret"


def _sign(payload: bytes) -> str:
    return hmac_module.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()


class _NoOpDetection:
    async def run_all(self, *, org_id, as_of=None):
        return {"survey_operations_trigger": 0}


class _StubOrchestrator(EventOrchestrator):
    def __init__(self):
        pass  # deliberately skips the real constructor — this double only exercises the router's own auth/dispatch, not orchestrator internals

    async def run_detection_cycle(self, *, org_id):
        return {"survey_operations_trigger": 0}

    async def process_pending(self, *, org_id, limit=50):
        return {"processed": 0, "failed": 0, "skipped": 0}


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
def client(auth_service, rbac_service, db) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_event_orchestrator] = lambda: _StubOrchestrator()
    app.dependency_overrides[get_events_repository] = lambda: CanonicalRepository(db["events"], Event)
    yield TestClient(app)
    app.dependency_overrides.clear()


async def _make_authenticated_user(auth_service, rbac_service, *, user_id: str, org_id: str, permissions: list[str]) -> str:
    role_code = f"role-{user_id}"
    await rbac_service._roles.insert(Role(org_id=org_id, created_by="seed", updated_by="seed", code=role_code, name=role_code, permissions=permissions))
    await rbac_service._user_roles.insert(UserRole(org_id=org_id, created_by="seed", updated_by="seed", user_id=user_id, role_code=role_code))
    await auth_service.set_password(user_id, "correct-horse-battery")
    _, token = await auth_service.authenticate(user_id, "correct-horse-battery")
    return token


# --------------------------------------------------------------------------- /internal/scheduler/tick


@pytest.mark.asyncio
async def test_tick_with_no_signing_secret_configured_fails_closed(client: TestClient):
    app.dependency_overrides[get_scheduler_signing_secret] = lambda: None
    body = json.dumps({"org_id": ORG_A}).encode()
    resp = client.post("/api/v1/internal/scheduler/tick", content=body, headers={"X-Signature": "irrelevant"})
    assert resp.status_code == 500  # SignatureConfigError — never a silent skip


@pytest.mark.asyncio
async def test_tick_with_a_bad_signature_is_rejected(client: TestClient):
    app.dependency_overrides[get_scheduler_signing_secret] = lambda: SECRET
    body = json.dumps({"org_id": ORG_A}).encode()
    resp = client.post("/api/v1/internal/scheduler/tick", content=body, headers={"X-Signature": "0" * 64})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_tick_with_a_valid_signature_runs_a_cycle(client: TestClient):
    app.dependency_overrides[get_scheduler_signing_secret] = lambda: SECRET
    body = json.dumps({"org_id": ORG_A}).encode()
    resp = client.post("/api/v1/internal/scheduler/tick", content=body, headers={"X-Signature": _sign(body)})
    assert resp.status_code == 200
    assert resp.json() == {"detected": {"survey_operations_trigger": 0}, "processed": {"processed": 0, "failed": 0, "skipped": 0}}


@pytest.mark.asyncio
async def test_tick_requires_no_torpedo_user_session_at_all(client: TestClient):
    """No Authorization header anywhere in these tests — a systemd timer has
    no Torpedo session, by design, same as the survey callback endpoint."""
    app.dependency_overrides[get_scheduler_signing_secret] = lambda: SECRET
    body = json.dumps({"org_id": ORG_A}).encode()
    resp = client.post("/api/v1/internal/scheduler/tick", content=body, headers={"X-Signature": _sign(body)})
    assert resp.status_code == 200


# --------------------------------------------------------------------------- /internal/scheduler/events


@pytest.mark.asyncio
async def test_list_events_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.get("/api/v1/internal/scheduler/events", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_events_with_permission_returns_only_this_orgs_events(client: TestClient, auth_service, rbac_service, db):
    from datetime import datetime, timezone as tz

    events = CanonicalRepository(db["events"], Event)
    await events.insert(Event(org_id=ORG_A, created_by="system", updated_by="system", event_type="ar_followup_due", entity_type="invoice", entity_id="inv-1", occurred_at=datetime.now(tz.utc), dedupe_key="k1"))
    await events.insert(Event(org_id="org-B", created_by="system", updated_by="system", event_type="ar_followup_due", entity_type="invoice", entity_id="inv-2", occurred_at=datetime.now(tz.utc), dedupe_key="k2"))

    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[SCHEDULER_READ])
    resp = client.get("/api/v1/internal/scheduler/events", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["entity_id"] == "inv-1"
