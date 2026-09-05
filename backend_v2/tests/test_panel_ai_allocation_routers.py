"""
HTTP-level tests for the AI allocation endpoint. Permission enforcement is what's
new at this layer; ranking/allocation behavior is exhaustively covered in
test_panel_ai_allocation.py.
"""

import json
from datetime import timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.auth.dependencies import get_auth_service, get_rbac_service
from app.auth.models import Credential, Session
from app.auth.service import AuthService
from app.main import app
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.models.money import Money
from app.panel.models import Allocation, Survey, SurveyResponse
from app.panel.routers import get_panel_allocation_ai_service, get_survey_provider
from app.panel.service import AllocationService, SurveyService
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import SURVEY_AI_ALLOCATE
from app.rbac.service import RBACService

ORG_A = "org-A"


class FakeLLM:
    def __init__(self, content: str):
        self._content = content

    async def chat(self, *, messages, response_format=None):
        from app.ai.llm import LLMResponse
        return LLMResponse(content=self._content, model="fake-model")


class StubProvider:
    async def build_redirect_url(self, *, survey, respondent_ref):
        return f"https://stub/{survey.external_id}/{respondent_ref}"

    async def refresh(self, *, survey):
        from app.panel.providers import SurveyProjection
        return SurveyProjection(quota_remaining=survey.quota_remaining, cpi_minor=survey.cpi.amount_minor, conversion_rate=survey.conversion_rate)


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
def survey_service(db) -> SurveyService:
    return SurveyService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def allocation_ai_service(db, survey_service):
    from app.ai.decision_engine import DecisionEngine
    from app.ai.tools import ToolRegistry
    from app.panel.ai_allocation import PanelAllocationAIService

    allocation_service = AllocationService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["allocations"], Allocation), CanonicalRepository(db["activities"], Activity))
    llm = FakeLLM(json.dumps({"decision": "NONE", "reasoning_summary": "n/a", "confidence": 0.9, "priority": "LOW", "entities": [], "actions": [], "follow_up_at": None, "requires_human_approval": False, "extracted_entities": {}}))
    engine = DecisionEngine(llm, ToolRegistry(), CanonicalRepository(db["ai_proposals"], AiProposal))
    return PanelAllocationAIService(engine, survey_service, allocation_service, CanonicalRepository(db["survey_responses"], SurveyResponse), CanonicalRepository(db["allocations"], Allocation))


@pytest.fixture
def client(auth_service, rbac_service, allocation_ai_service) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_panel_allocation_ai_service] = lambda: allocation_ai_service
    app.dependency_overrides[get_survey_provider] = lambda: StubProvider()
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
async def test_ai_allocate_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.post("/api/v1/traffic/ts-1/allocate/ai", json={"person_id": "p1", "vendor_id": "v1", "country_code": "IN", "respondent_ref": "r1"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ai_allocate_with_no_eligible_surveys_is_422(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[SURVEY_AI_ALLOCATE])
    resp = client.post("/api/v1/traffic/ts-1/allocate/ai", json={"person_id": "p1", "vendor_id": "v1", "country_code": "IN", "respondent_ref": "r1"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422
