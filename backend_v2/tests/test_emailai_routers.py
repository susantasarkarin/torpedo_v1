"""
HTTP-level Email AI tests. Permission enforcement is what's new at this layer;
classification/routing/follow-up behavior is exhaustively covered in
test_emailai_service.py.
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
from app.emailai.drafting import EmailMessageDrafter
from app.emailai.models import InboundEmail
from app.emailai.routers import get_email_ai_service
from app.emailai.service import EmailAIService
from app.finance.models import Payment, ReconciliationRecord
from app.finance.service import ReconciliationService
from app.identity.facet_service import FacetService
from app.identity.facets import AuthIdentity, CustomerBilling, EmployeeRecord, LeadState, PanelistProfile, VendorProfile
from app.identity.models import Account, AccountBrandRelationship, Person
from app.identity.service import IdentityService
from app.leadgen.models import DeadLetterEvent, LeadEnrollment, RawLeadEvent
from app.leadgen.service import LeadGenService
from app.main import app
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.outreach.budget import BudgetService
from app.outreach.kill_switch import KillSwitch, KillSwitchService
from app.outreach.models import Mailbox, Message, SendLogEntry
from app.outreach.service import MessagingFacade
from app.outreach.suppression import Suppression, SuppressionService
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import EMAIL_ANALYZE, EMAIL_INGEST
from app.rbac.service import RBACService

ORG_A = "org-A"


class FakeLLM:
    def __init__(self, content: str):
        self._content = content

    async def chat(self, *, messages, response_format=None):
        return LLMResponse(content=self._content, model="fake-model")


class NullSendProvider:
    async def send(self, *, mailbox_credentials_id, to_email, subject, body):
        raise AssertionError("not exercised in these tests")


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
def email_ai_service(db) -> EmailAIService:
    identity = IdentityService(people=CanonicalRepository(db["people"], Person), accounts=CanonicalRepository(db["accounts"], Account), brand_relationships=CanonicalRepository(db["account_brand_relationships"], AccountBrandRelationship), activities=CanonicalRepository(db["activities"], Activity))
    facets = FacetService(people=CanonicalRepository(db["people"], Person), accounts=CanonicalRepository(db["accounts"], Account), activities=CanonicalRepository(db["activities"], Activity), lead_states=CanonicalRepository(db["lead_states"], LeadState), panelist_profiles=CanonicalRepository(db["panelist_profiles"], PanelistProfile), customer_billing=CanonicalRepository(db["customer_billing"], CustomerBilling), vendor_profiles=CanonicalRepository(db["vendor_profiles"], VendorProfile), employee_records=CanonicalRepository(db["employee_records"], EmployeeRecord), auth_identities=CanonicalRepository(db["auth_identities"], AuthIdentity))
    suppression = SuppressionService(CanonicalRepository(db["suppressions"], Suppression))
    leadgen = LeadGenService(identity, facets, suppression, raw_events=CanonicalRepository(db["raw_lead_events"], RawLeadEvent), ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal), enrollments=CanonicalRepository(db["lead_enrollments"], LeadEnrollment), dead_letters=CanonicalRepository(db["dead_letters"], DeadLetterEvent), activities=CanonicalRepository(db["activities"], Activity))
    reconciliation = ReconciliationService(CanonicalRepository(db["reconciliation_records"], ReconciliationRecord), CanonicalRepository(db["payments"], Payment))
    outreach = MessagingFacade(mailboxes=CanonicalRepository(db["mailboxes"], Mailbox), messages=CanonicalRepository(db["messages"], Message), send_logs=CanonicalRepository(db["send_log_entries"], SendLogEntry), ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal), activities=CanonicalRepository(db["activities"], Activity), suppression=suppression, kill_switch=KillSwitchService(CanonicalRepository(db["kill_switches"], KillSwitch)), budget=BudgetService(db["budget_counters"]), provider=NullSendProvider())

    llm = FakeLLM(content=json.dumps({"decision": "SPAM", "reasoning_summary": "n/a", "confidence": 0.9, "priority": "LOW", "entities": [], "actions": [], "follow_up_at": None, "requires_human_approval": False, "extracted_entities": {}}))
    engine = DecisionEngine(llm, ToolRegistry(), CanonicalRepository(db["ai_proposals"], AiProposal))

    return EmailAIService(
        emails=CanonicalRepository(db["inbound_emails"], InboundEmail), ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal),
        activities=CanonicalRepository(db["activities"], Activity), decision_engine=engine, leadgen=leadgen,
        suppression=suppression, reconciliation=reconciliation, outreach=outreach, drafter=EmailMessageDrafter(llm),
    )


@pytest.fixture
def client(auth_service, rbac_service, email_ai_service) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_email_ai_service] = lambda: email_ai_service
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
async def test_ingest_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.post("/api/v1/emails/ingest", json={"provider": "gmail", "provider_message_id": "e1", "from_address": "a@b.com", "to_address": "s@torpedo.example", "subject": "hi", "body": "hi"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ingest_then_analyze_through_http(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[EMAIL_INGEST, EMAIL_ANALYZE])

    ingest_resp = client.post("/api/v1/emails/ingest", json={"provider": "gmail", "provider_message_id": "e1", "from_address": "a@b.com", "to_address": "s@torpedo.example", "subject": "hi", "body": "hi"}, headers={"Authorization": f"Bearer {token}"})
    assert ingest_resp.status_code == 200
    email = ingest_resp.json()
    email_id = email.get("id") or email.get("_id")

    analyze_resp = client.post(f"/api/v1/emails/{email_id}/analyze", headers={"Authorization": f"Bearer {token}"})
    assert analyze_resp.status_code == 200
    assert analyze_resp.json()["decision"] == "SPAM"
