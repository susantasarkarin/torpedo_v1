"""
HTTP-level tests for the billing/margin endpoints and the new integrations-status
diagnostic. Permission enforcement is what's new at this layer; billing/margin
mechanics are exhaustively covered in test_panel_billing.py.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.ai.gpu_broker import GpuBroker
from app.ai.routers import get_events_repository_for_status, get_gpu_broker, get_proposals_repository_for_status
from app.auth.dependencies import get_auth_service, get_rbac_service
from app.auth.models import Credential, Session
from app.auth.service import AuthService
from app.crm.models import Opportunity
from app.finance.models import Bill, Invoice
from app.finance.routers import get_bill_service, get_invoice_service
from app.finance.sequence import SequenceService
from app.finance.service import BillService, InvoiceService
from app.main import app
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.panel.models import Survey, SurveyResponse
from app.panel.routers import get_billing_service
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import INTEGRATIONS_STATUS_READ, SURVEY_MARGIN_READ
from app.rbac.service import RBACService
from app.scheduler.models import Event

ORG_A = "org-A"


class _FakeGpuLeaseCollection:
    """Same fake used by test_ai_routers.py — this file's /integrations/status
    test must not depend on real MONGO_URI/MONGO_DB_NAME settings being
    configured in whatever environment the suite runs in."""

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
def gpu_broker() -> GpuBroker:
    return GpuBroker(_FakeGpuLeaseCollection())


@pytest.fixture
def auth_service(db) -> AuthService:
    return AuthService(credentials=CanonicalRepository(db["credentials"], Credential), sessions=CanonicalRepository(db["sessions"], Session), default_org_id=ORG_A)


@pytest.fixture
def rbac_service(db) -> RBACService:
    return RBACService(user_roles=CanonicalRepository(db["user_roles"], UserRole), roles=CanonicalRepository(db["roles"], Role), approval_authorities=CanonicalRepository(db["approval_authorities"], ApprovalAuthority))


@pytest.fixture
def invoice_service(db) -> InvoiceService:
    return InvoiceService(CanonicalRepository(db["invoices"], Invoice), SequenceService(db["finance_sequences"]), CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def bill_service(db) -> BillService:
    return BillService(CanonicalRepository(db["bills"], Bill), SequenceService(db["finance_sequences"]), CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def billing_service(db, invoice_service, bill_service):
    from app.panel.billing import SurveyBillingService
    return SurveyBillingService(CanonicalRepository(db["survey_responses"], SurveyResponse), CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["opportunities"], Opportunity), invoice_service, bill_service)


@pytest.fixture
def client(db, auth_service, rbac_service, billing_service, invoice_service, bill_service, gpu_broker) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_billing_service] = lambda: billing_service
    app.dependency_overrides[get_invoice_service] = lambda: invoice_service
    app.dependency_overrides[get_bill_service] = lambda: bill_service
    app.dependency_overrides[get_gpu_broker] = lambda: gpu_broker
    app.dependency_overrides[get_events_repository_for_status] = lambda: CanonicalRepository(db["events"], Event)
    app.dependency_overrides[get_proposals_repository_for_status] = lambda: CanonicalRepository(db["ai_proposals"], AiProposal)
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
async def test_margin_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.get("/api/v1/surveys/does-not-exist/margin", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_margin_for_unknown_survey_is_400(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[SURVEY_MARGIN_READ])
    resp = client.get("/api/v1/surveys/does-not-exist/margin", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_integrations_status_reports_credential_blocked_boundaries_not_secrets(client: TestClient, auth_service, rbac_service, monkeypatch):
    monkeypatch.delenv("CINT_API_KEY", raising=False)
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[INTEGRATIONS_STATUS_READ])

    resp = client.get("/api/v1/integrations/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email_send_provider"] == "NOT_CONFIGURED"
    assert body["cint"] == "NOT_CONFIGURED"
    assert body["gpu_credential"] == "NOT_CONFIGURED"
    assert "CINT_API_KEY" not in str(body)  # never echoes the secret's value, only presence/absence
    assert body["scheduler_events"] == {"FAILED": 0, "PENDING": 0, "PROCESSED": 0, "PROCESSING": 0}
    assert body["governance_pending_review"] == 0


@pytest.mark.asyncio
async def test_integrations_status_reports_real_scheduler_and_governance_activity(client: TestClient, auth_service, rbac_service, db):
    await CanonicalRepository(db["events"], Event).insert(
        Event(org_id=ORG_A, created_by="system", updated_by="system", event_type="ar_followup_due", entity_type="invoice", entity_id="inv-1", occurred_at=datetime.now(timezone.utc), dedupe_key="k1", processing_status="FAILED", attempts=1)
    )
    await CanonicalRepository(db["ai_proposals"], AiProposal).insert(
        AiProposal(org_id=ORG_A, created_by="system", updated_by="system", task="evaluate_panel_allocation", subject_id="subj-1", model="m", model_version="v1", confidence=0.9, proposed_fields={}, status="approved")
    )
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[INTEGRATIONS_STATUS_READ])

    resp = client.get("/api/v1/integrations/status", headers={"Authorization": f"Bearer {token}"})
    body = resp.json()
    assert body["scheduler_events"]["FAILED"] == 1
    assert body["scheduler_events_exhausted"] == 0  # still retryable — attempts (1) hasn't reached MAX_ATTEMPTS
    assert body["governance_pending_review"] == 1


@pytest.mark.asyncio
async def test_integrations_status_distinguishes_exhausted_failed_events_from_retryable_ones(client: TestClient, auth_service, rbac_service, db):
    events = CanonicalRepository(db["events"], Event)
    await events.insert(Event(org_id=ORG_A, created_by="system", updated_by="system", event_type="ar_followup_due", entity_type="invoice", entity_id="inv-1", occurred_at=datetime.now(timezone.utc), dedupe_key="k1", processing_status="FAILED", attempts=1))
    await events.insert(Event(org_id=ORG_A, created_by="system", updated_by="system", event_type="ar_followup_due", entity_type="invoice", entity_id="inv-2", occurred_at=datetime.now(timezone.utc), dedupe_key="k2", processing_status="FAILED", attempts=5))
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[INTEGRATIONS_STATUS_READ])

    resp = client.get("/api/v1/integrations/status", headers={"Authorization": f"Bearer {token}"})
    body = resp.json()
    assert body["scheduler_events"]["FAILED"] == 2
    assert body["scheduler_events_exhausted"] == 1  # only the attempts=5 one has hit MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_integrations_status_distinguishes_stuck_processing_events_from_in_flight_ones(client: TestClient, auth_service, rbac_service, db):
    """Phase 16 (failure/recovery audit): a PROCESSING event orphaned by a
    crash is self-healed by the orchestrator's next tick, but a persistent
    nonzero count is a real operational signal — must not be indistinguishable
    from a genuinely in-flight event from moments ago."""
    from app.scheduler.models import STUCK_PROCESSING_THRESHOLD

    events = CanonicalRepository(db["events"], Event)
    stale_at = datetime.now(timezone.utc) - STUCK_PROCESSING_THRESHOLD - timedelta(minutes=1)
    await events.insert(Event(org_id=ORG_A, created_by="system", updated_by="system", event_type="ar_followup_due", entity_type="invoice", entity_id="inv-1", occurred_at=datetime.now(timezone.utc), dedupe_key="k1", processing_status="PROCESSING", updated_at=stale_at))
    await events.insert(Event(org_id=ORG_A, created_by="system", updated_by="system", event_type="ar_followup_due", entity_type="invoice", entity_id="inv-2", occurred_at=datetime.now(timezone.utc), dedupe_key="k2", processing_status="PROCESSING"))
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[INTEGRATIONS_STATUS_READ])

    resp = client.get("/api/v1/integrations/status", headers={"Authorization": f"Bearer {token}"})
    body = resp.json()
    assert body["scheduler_events"]["PROCESSING"] == 2
    assert body["scheduler_events_stuck"] == 1  # only the backdated one is old enough to be orphaned


@pytest.mark.asyncio
async def test_integrations_status_distinguishes_stale_pending_review_from_recent(client: TestClient, auth_service, rbac_service, db):
    from datetime import timedelta

    from app.governance.approvals import STALE_REVIEW_THRESHOLD

    proposals = CanonicalRepository(db["ai_proposals"], AiProposal)
    await proposals.insert(AiProposal(org_id=ORG_A, created_by="system", updated_by="system", task="evaluate_panel_allocation", subject_id="subj-1", model="m", model_version="v1", confidence=0.9, proposed_fields={}, status="approved"))
    await proposals.insert(AiProposal(org_id=ORG_A, created_by="system", updated_by="system", task="evaluate_panel_allocation", subject_id="subj-2", model="m", model_version="v1", confidence=0.9, proposed_fields={}, status="approved", created_at=datetime.now(timezone.utc) - STALE_REVIEW_THRESHOLD - timedelta(hours=1)))
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[INTEGRATIONS_STATUS_READ])

    resp = client.get("/api/v1/integrations/status", headers={"Authorization": f"Bearer {token}"})
    body = resp.json()
    assert body["governance_pending_review"] == 2
    assert body["governance_stale_review_count"] == 1  # only the older one


@pytest.mark.asyncio
async def test_integrations_status_reports_email_send_provider_configured_once_smtp_credentials_exist(client: TestClient, auth_service, rbac_service, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[INTEGRATIONS_STATUS_READ])

    resp = client.get("/api/v1/integrations/status", headers={"Authorization": f"Bearer {token}"})
    body = resp.json()
    assert body["email_send_provider"] == "CONFIGURED"
    assert "app-password" not in str(body)  # never echoes the secret's value, only presence/absence
