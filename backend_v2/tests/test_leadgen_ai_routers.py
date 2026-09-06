"""
HTTP-level tests for the GSC lead-gen/ICP endpoints. Confirms the default
`NullGSCProvider` fails loud (502) rather than fabricating an empty-but-successful
result — the credential-absent-mode requirement (master-prompt §21) proven at the
HTTP boundary, not just the service layer.
"""

from datetime import timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.ai.decision_engine import Decision
from app.auth.dependencies import get_auth_service, get_rbac_service
from app.auth.models import Credential, Session
from app.auth.service import AuthService
from app.leadgen.ai_conversion import LeadConversionAIError
from app.leadgen.routers import get_gsc_provider, get_lead_conversion_ai_service
from app.main import app
from app.models.base import CanonicalRepository
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import LEADGEN_AI_CONVERT, LEADGEN_AI_GENERATE
from app.rbac.service import RBACService

ORG_A = "org-A"


class FakeConversionAIService:
    def __init__(self, *, raises=None, decision="HOLD", opportunity=None):
        self._raises = raises
        self._decision = decision
        self._opportunity = opportunity
        self.calls: list[dict] = []

    async def evaluate_and_convert(self, *, org_id, actor, lead_state_id):
        self.calls.append({"lead_state_id": lead_state_id})
        if self._raises:
            raise self._raises
        return Decision(decision=self._decision, reasoning_summary="n/a", confidence=0.9, priority="MEDIUM"), self._opportunity


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
def client(auth_service, rbac_service) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
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
async def test_generate_leads_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.post("/api/v1/leads/generate", json={"site_url": "https://torpedo.example"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_generate_leads_with_no_gsc_credentials_fails_loud_not_fake_success(client: TestClient, auth_service, rbac_service):
    """The default GSCProvider (NullGSCProvider) must report unavailable, not a
    fabricated empty analytics result that looks like a real, quiet day."""
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[LEADGEN_AI_GENERATE])
    resp = client.post("/api/v1/leads/generate", json={"site_url": "https://torpedo.example"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_ai_convert_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    app.dependency_overrides[get_lead_conversion_ai_service] = lambda: FakeConversionAIService()
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.post("/api/v1/leads/lead-1/ai/convert", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ai_convert_returns_the_decision_and_no_opportunity_on_hold(client: TestClient, auth_service, rbac_service):
    fake = FakeConversionAIService(decision="HOLD")
    app.dependency_overrides[get_lead_conversion_ai_service] = lambda: fake
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[LEADGEN_AI_CONVERT])

    resp = client.post("/api/v1/leads/lead-1/ai/convert", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"]["decision"] == "HOLD"
    assert body["opportunity"] is None
    assert fake.calls == [{"lead_state_id": "lead-1"}]


@pytest.mark.asyncio
async def test_ai_convert_with_an_ineligible_lead_is_400(client: TestClient, auth_service, rbac_service):
    app.dependency_overrides[get_lead_conversion_ai_service] = lambda: FakeConversionAIService(raises=LeadConversionAIError("lead is not eligible"))
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[LEADGEN_AI_CONVERT])

    resp = client.post("/api/v1/leads/lead-1/ai/convert", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400
