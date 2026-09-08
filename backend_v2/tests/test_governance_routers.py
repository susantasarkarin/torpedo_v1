"""
HTTP-level governance/approval tests. Permission enforcement and request/
response wiring are what's new at this layer — ApprovalService's own logic is
exhaustively covered in test_governance_approvals.py.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.auth.dependencies import get_auth_service, get_rbac_service
from app.auth.models import Credential, Session
from app.auth.service import AuthService
from app.governance.approvals import STALE_REVIEW_THRESHOLD, ApprovalService
from app.governance.routers import get_approval_service
from app.main import app
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import GOVERNANCE_READ, GOVERNANCE_REVIEW
from app.rbac.service import RBACService

ORG_A = "org-A"


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
def approval_service(db) -> ApprovalService:
    return ApprovalService(CanonicalRepository(db["ai_proposals"], AiProposal))


@pytest.fixture
def client(auth_service, rbac_service, approval_service) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_approval_service] = lambda: approval_service
    yield TestClient(app)
    app.dependency_overrides.clear()


async def _make_authenticated_user(auth_service, rbac_service, *, user_id: str, org_id: str, permissions: list[str]) -> str:
    role_code = f"role-{user_id}"
    await rbac_service._roles.insert(Role(org_id=org_id, created_by="seed", updated_by="seed", code=role_code, name=role_code, permissions=permissions))
    await rbac_service._user_roles.insert(UserRole(org_id=org_id, created_by="seed", updated_by="seed", user_id=user_id, role_code=role_code))
    await auth_service.set_password(user_id, "correct-horse-battery")
    _, token = await auth_service.authenticate(user_id, "correct-horse-battery")
    return token


async def _proposal(db, *, created_at=None) -> AiProposal:
    kwargs = {"created_at": created_at} if created_at is not None else {}
    return await CanonicalRepository(db["ai_proposals"], AiProposal).insert(
        AiProposal(org_id=ORG_A, created_by="system", updated_by="system", task="evaluate_panel_allocation", subject_id="subj-1", model="m", model_version="v1", confidence=0.9, proposed_fields={}, status="approved", **kwargs)
    )


@pytest.mark.asyncio
async def test_list_proposals_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.get("/api/v1/governance/proposals", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_proposals_returns_unreviewed_ones(client: TestClient, auth_service, rbac_service, db):
    proposal = await _proposal(db)
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[GOVERNANCE_READ])

    resp = client.get("/api/v1/governance/proposals", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["_id"] == proposal.id


@pytest.mark.asyncio
async def test_review_without_permission_is_403(client: TestClient, auth_service, rbac_service, db):
    proposal = await _proposal(db)
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.post(f"/api/v1/governance/proposals/{proposal.id}/review", json={"action": "APPROVE"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_review_records_the_reviewer_and_removes_it_from_pending(client: TestClient, auth_service, rbac_service, db):
    proposal = await _proposal(db)
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[GOVERNANCE_READ, GOVERNANCE_REVIEW])

    resp = client.post(f"/api/v1/governance/proposals/{proposal.id}/review", json={"action": "APPROVE", "notes": "matches expected outcome"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["reviewed_by"] == "alice"
    assert body["review_action"] == "APPROVE"

    pending = client.get("/api/v1/governance/proposals", headers={"Authorization": f"Bearer {token}"}).json()
    assert pending == []


@pytest.mark.asyncio
async def test_review_with_an_unrecognized_action_is_400(client: TestClient, auth_service, rbac_service, db):
    proposal = await _proposal(db)
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[GOVERNANCE_REVIEW])
    resp = client.post(f"/api/v1/governance/proposals/{proposal.id}/review", json={"action": "MAYBE_LATER"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_reviewing_an_unknown_proposal_is_400(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[GOVERNANCE_REVIEW])
    resp = client.post("/api/v1/governance/proposals/does-not-exist/review", json={"action": "APPROVE"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_review_with_modified_fields_stores_the_structured_change(client: TestClient, auth_service, rbac_service, db):
    proposal = await _proposal(db)
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[GOVERNANCE_REVIEW])

    resp = client.post(f"/api/v1/governance/proposals/{proposal.id}/review", json={"action": "MODIFY", "modified_fields": {"decision": "survey-2"}}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["modified_fields"] == {"decision": "survey-2"}


@pytest.mark.asyncio
async def test_modified_fields_for_a_non_modify_action_is_400(client: TestClient, auth_service, rbac_service, db):
    proposal = await _proposal(db)
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[GOVERNANCE_REVIEW])

    resp = client.post(f"/api/v1/governance/proposals/{proposal.id}/review", json={"action": "APPROVE", "modified_fields": {"decision": "survey-2"}}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_stale_only_excludes_recent_proposals(client: TestClient, auth_service, rbac_service, db):
    await _proposal(db)
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[GOVERNANCE_READ])

    resp = client.get("/api/v1/governance/proposals?stale_only=true", headers={"Authorization": f"Bearer {token}"})
    assert resp.json() == []


@pytest.mark.asyncio
async def test_stale_only_includes_genuinely_stale_proposals(client: TestClient, auth_service, rbac_service, db):
    stale = await _proposal(db, created_at=datetime.now(timezone.utc) - STALE_REVIEW_THRESHOLD - timedelta(hours=1))
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[GOVERNANCE_READ])

    resp = client.get("/api/v1/governance/proposals?stale_only=true", headers={"Authorization": f"Bearer {token}"})
    body = resp.json()
    assert len(body) == 1
    assert body[0]["_id"] == stale.id
