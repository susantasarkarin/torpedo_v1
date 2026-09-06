"""
HTTP-level tests for the AI finance endpoints. Permission enforcement is what's
new at this layer; AR/AP/matching behavior is exhaustively covered in
test_finance_ai.py.
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
from app.finance.ai_finance import AIFinanceService
from app.finance.models import Bill, Payment, ReconciliationRecord
from app.finance.routers import get_ai_finance_service
from app.finance.sequence import SequenceService
from app.finance.service import BillService, InvoiceService, PaymentService, ReconciliationService
from app.main import app
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.finance.models import Invoice
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import FINANCE_AI_AR
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
def ai_finance_service(db) -> AIFinanceService:
    sequences = SequenceService(db["finance_sequences"])
    activities = CanonicalRepository(db["activities"], Activity)
    invoice_service = InvoiceService(CanonicalRepository(db["invoices"], Invoice), sequences, activities)
    bill_service = BillService(CanonicalRepository(db["bills"], Bill), sequences, activities)
    payment_service = PaymentService(CanonicalRepository(db["payments"], Payment), CanonicalRepository(db["invoices"], Invoice), CanonicalRepository(db["bills"], Bill), sequences, activities)
    reconciliation_service = ReconciliationService(CanonicalRepository(db["reconciliation_records"], ReconciliationRecord), CanonicalRepository(db["payments"], Payment))
    llm = FakeLLM(json.dumps({"decision": "REMINDER", "reasoning_summary": "n/a", "confidence": 0.9, "priority": "LOW", "entities": [], "actions": [], "follow_up_at": None, "requires_human_approval": False, "extracted_entities": {}}))
    engine = DecisionEngine(llm, ToolRegistry(), CanonicalRepository(db["ai_proposals"], AiProposal))
    return AIFinanceService(engine, invoice_service, bill_service, payment_service, reconciliation_service, CanonicalRepository(db["reconciliation_records"], ReconciliationRecord), CanonicalRepository(db["ai_proposals"], AiProposal), activities)


@pytest.fixture
def client(auth_service, rbac_service, ai_finance_service) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_ai_finance_service] = lambda: ai_finance_service
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
async def test_ar_followup_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.post("/api/v1/finance/invoices/does-not-exist/ai/ar-followup", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ar_followup_for_unknown_invoice_is_400(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[FINANCE_AI_AR])
    resp = client.post("/api/v1/finance/invoices/does-not-exist/ai/ar-followup", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400
