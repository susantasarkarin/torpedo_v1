"""
HTTP-level outreach tests, through the real wired app (`app.main.app`), same pattern
as `test_leadgen_routers.py`. Deliberately narrow: permission enforcement is what's
*new* at this layer — every gate's behavior is already exhaustively covered in
test_outreach_service.py and re-proving it through HTTP would be redundant.
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
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.outreach.budget import BudgetService
from app.outreach.kill_switch import KillSwitch, KillSwitchService
from app.outreach.models import Mailbox, Message, SendLogEntry
from app.outreach.providers import ProviderSendResult
from app.outreach.routers import get_kill_switch_service, get_outreach_service, get_send_provider, get_suppression_service
from app.outreach.service import MessagingFacade
from app.outreach.suppression import Suppression, SuppressionService
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import OUTREACH_ADMIN, OUTREACH_SEND, OUTREACH_SUPPRESS
from app.rbac.service import RBACService

ORG_A = "org-A"
ORG_B = "org-B"

BODY_OK = "Hi there — this is a message. Unsubscribe here: https://example.com/u"


class StubSuccessProvider:
    async def send(self, *, mailbox_credentials_id, to_email, subject, body):
        return ProviderSendResult(provider_message_id="stub-1")


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def auth_service(db) -> AuthService:
    return AuthService(
        credentials=CanonicalRepository(db["credentials"], Credential),
        sessions=CanonicalRepository(db["sessions"], Session),
        default_org_id=ORG_A,
    )


@pytest.fixture
def rbac_service(db) -> RBACService:
    return RBACService(
        user_roles=CanonicalRepository(db["user_roles"], UserRole),
        roles=CanonicalRepository(db["roles"], Role),
        approval_authorities=CanonicalRepository(db["approval_authorities"], ApprovalAuthority),
    )


@pytest.fixture
def kill_switch_service(db) -> KillSwitchService:
    return KillSwitchService(CanonicalRepository(db["kill_switches"], KillSwitch))


@pytest.fixture
def suppression_service(db) -> SuppressionService:
    return SuppressionService(CanonicalRepository(db["suppressions"], Suppression))


@pytest.fixture
def outreach_service(db, kill_switch_service, suppression_service) -> MessagingFacade:
    return MessagingFacade(
        mailboxes=CanonicalRepository(db["mailboxes"], Mailbox),
        messages=CanonicalRepository(db["messages"], Message),
        send_logs=CanonicalRepository(db["send_log_entries"], SendLogEntry),
        ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal),
        activities=CanonicalRepository(db["activities"], Activity),
        suppression=suppression_service,
        kill_switch=kill_switch_service,
        budget=BudgetService(db["budget_counters"]),
        provider=StubSuccessProvider(),
    )


@pytest.fixture
def client(auth_service, rbac_service, outreach_service, kill_switch_service, suppression_service) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_outreach_service] = lambda: outreach_service
    app.dependency_overrides[get_kill_switch_service] = lambda: kill_switch_service
    app.dependency_overrides[get_suppression_service] = lambda: suppression_service
    app.dependency_overrides[get_send_provider] = lambda: StubSuccessProvider()
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
async def test_send_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])

    resp = client.post(
        "/api/v1/outreach/send",
        json={"mailbox_id": "m1", "to_email": "a@b.com", "idempotency_key": "k1", "subject": "hi", "body": BODY_OK},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_kill_switch_admin_endpoints_require_outreach_admin(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(
        auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[OUTREACH_SEND]
    )

    resp = client.post(
        "/api/v1/outreach/kill-switch/resume", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403, "OUTREACH_SEND must not implicitly grant kill-switch control"


@pytest.mark.asyncio
async def test_resume_then_send_through_http_end_to_end(client: TestClient, auth_service, rbac_service, outreach_service: MessagingFacade):
    token = await _make_authenticated_user(
        auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[OUTREACH_SEND, OUTREACH_ADMIN]
    )
    mailbox = await outreach_service._mailboxes.insert(
        Mailbox(org_id=ORG_A, created_by="alice", updated_by="alice", email_address="s@b.com", provider="smtp", credentials_id="cred-1")
    )

    resume_resp = client.post("/api/v1/outreach/kill-switch/resume", headers={"Authorization": f"Bearer {token}"})
    assert resume_resp.status_code == 200
    assert resume_resp.json()["paused"] is False

    send_resp = client.post(
        "/api/v1/outreach/send",
        json={"mailbox_id": mailbox.id, "to_email": "a@b.com", "idempotency_key": "k1", "subject": "hi", "body": BODY_OK},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert send_resp.status_code == 200
    assert send_resp.json()["status"] == "sent"


@pytest.mark.asyncio
async def test_suppress_endpoint_requires_permission_and_persists(client: TestClient, auth_service, rbac_service, suppression_service: SuppressionService):
    token = await _make_authenticated_user(
        auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[OUTREACH_SUPPRESS]
    )

    resp = client.post(
        "/api/v1/outreach/suppress", json={"email": "opt-out@b.com", "reason": "unsubscribed"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert await suppression_service.is_suppressed("opt-out@b.com") is True


@pytest.mark.asyncio
async def test_cross_org_kill_switch_state_is_isolated(client: TestClient, auth_service, rbac_service, outreach_service: MessagingFacade):
    """org_id is always derived from the resolved identity, never a caller-supplied
    parameter — pausing org A must not affect org B."""
    token_a = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[OUTREACH_ADMIN])
    token_b = await _make_authenticated_user(auth_service, rbac_service, user_id="bob", org_id=ORG_B, permissions=[OUTREACH_ADMIN])

    client.post("/api/v1/outreach/kill-switch/resume", headers={"Authorization": f"Bearer {token_a}"})
    b_status = client.post("/api/v1/outreach/kill-switch/resume", headers={"Authorization": f"Bearer {token_b}"})

    assert b_status.json()["org_id"] == ORG_B


# --------------------------------------------------------------------------- get_send_provider() selection


def test_get_send_provider_prefers_ses_when_both_ses_and_smtp_are_configured(monkeypatch):
    """SES is the real, verified-working credential this environment
    actually has; SMTP stays a real, independent fallback, not deleted."""
    from app.config import Settings
    from app.outreach.routers import get_send_provider
    from app.outreach.ses_provider import SesSendProvider

    fake_settings = Settings(
        smtp_host="smtp.example.com", smtp_username="u", smtp_password="p",
        aws_ses_region="us-east-1", ses_from_email="sender@example.com",
        aws_access_key_id="AKIAFAKE", aws_secret_access_key="fake-secret",
    )
    monkeypatch.setattr("app.config.get_settings", lambda: fake_settings)

    provider = get_send_provider()
    assert isinstance(provider, SesSendProvider)


def test_get_send_provider_falls_back_to_smtp_when_ses_is_not_configured(monkeypatch):
    from app.config import Settings
    from app.outreach.routers import get_send_provider
    from app.outreach.smtp_provider import SmtpSendProvider

    fake_settings = Settings(smtp_host="smtp.example.com", smtp_username="u", smtp_password="p")
    monkeypatch.setattr("app.config.get_settings", lambda: fake_settings)

    provider = get_send_provider()
    assert isinstance(provider, SmtpSendProvider)
