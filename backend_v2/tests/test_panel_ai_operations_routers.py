"""
HTTP-level tests for the AI operations endpoints. Permission enforcement is what's
new at this layer; trigger detection/decision behavior is exhaustively covered in
test_panel_ai_operations.py.
"""

import json
from datetime import timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.ai.decision_engine import DecisionEngine
from app.ai.llm import LLMResponse
from app.ai.tools import ToolRegistry
from app.auth.dependencies import get_auth_service, get_rbac_service
from app.auth.models import Credential, Session
from app.auth.service import AuthService
from app.main import app
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.panel.ai_operations import OperationsAIService
from app.panel.inactivity import StudyInactivityService
from app.panel.models import Allocation, Survey, SurveyResponse
from app.panel.routers import get_operations_ai_service
from app.panel.service import SurveyService
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import SURVEY_AI_OPERATIONS
from app.rbac.service import RBACService

ORG_A = "org-A"


class FakeLLM:
    def __init__(self, content: str):
        self._content = content

    async def chat(self, *, messages, response_format=None):
        return LLMResponse(content=self._content, model="fake-model")


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
def operations_ai_service(db) -> OperationsAIService:
    survey_service = SurveyService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["activities"], Activity))
    inactivity = StudyInactivityService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["allocations"], Allocation), CanonicalRepository(db["activities"], Activity))
    llm = FakeLLM(json.dumps({"decision": "NO_ACTION", "reasoning_summary": "n/a", "confidence": 0.9, "priority": "LOW", "entities": [], "actions": [], "follow_up_at": None, "requires_human_approval": False, "extracted_entities": {}}))
    engine = DecisionEngine(llm, ToolRegistry(), CanonicalRepository(db["ai_proposals"], AiProposal))
    return OperationsAIService(engine, survey_service, inactivity, CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["survey_responses"], SurveyResponse), CanonicalRepository(db["activities"], Activity), CanonicalRepository(db["ai_proposals"], AiProposal))


@pytest.fixture
def client(auth_service, rbac_service, operations_ai_service) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_operations_ai_service] = lambda: operations_ai_service
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
async def test_detect_triggers_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.get("/api/v1/surveys/operations/triggers", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_detect_triggers_returns_empty_list_when_nothing_flagged(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[SURVEY_AI_OPERATIONS])
    resp = client.get("/api/v1/surveys/operations/triggers", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_decide_operations_response_for_unknown_survey_is_400(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[SURVEY_AI_OPERATIONS])
    resp = client.post("/api/v1/surveys/does-not-exist/operations/decide", json={"trigger_type": "no_traffic_7_days"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400
