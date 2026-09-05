"""
HTTP-level panel tests, through the real wired app. Permission enforcement, and the
one deliberate exception to it (the signed callback endpoint), are what's new at this
layer — allocation/callback/reconciliation behavior is exhaustively covered in
test_panel_service.py.
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
from app.finance.rewards_ledger import RewardLedgerEntry, RewardLedgerService
from app.main import app
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.panel.models import Allocation, Survey, SurveyResponse
from app.panel.routers import get_allocation_service, get_callback_service, get_survey_provider, get_survey_service
from app.panel.service import AllocationService, CallbackService, SurveyService
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import SURVEY_ALLOCATE, SURVEY_MANAGE
from app.rbac.service import RBACService

ORG_A = "org-A"
SECRET = "http-test-secret"


def _sign(payload: bytes) -> str:
    return hmac_module.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()


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
def allocation_service(db) -> AllocationService:
    return AllocationService(CanonicalRepository(db["surveys"], Survey), CanonicalRepository(db["allocations"], Allocation), CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def callback_service(db) -> CallbackService:
    return CallbackService(
        CanonicalRepository(db["survey_responses"], SurveyResponse), CanonicalRepository(db["allocations"], Allocation),
        CanonicalRepository(db["activities"], Activity), RewardLedgerService(CanonicalRepository(db["reward_ledger_entries"], RewardLedgerEntry)),
        signing_secret=SECRET,
    )


@pytest.fixture
def client(auth_service, rbac_service, survey_service, allocation_service, callback_service) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_survey_service] = lambda: survey_service
    app.dependency_overrides[get_allocation_service] = lambda: allocation_service
    app.dependency_overrides[get_callback_service] = lambda: callback_service
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
async def test_allocate_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.post(
        "/api/v1/traffic/ts-1/allocate",
        json={"candidate_survey_ids": ["s1"], "person_id": "p1", "vendor_id": "v1", "country_code": "IN", "respondent_ref": "r1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_full_allocate_and_callback_flow_through_http(client: TestClient, auth_service, rbac_service):
    admin_token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[SURVEY_MANAGE, SURVEY_ALLOCATE])

    create_resp = client.post(
        "/api/v1/surveys",
        json={"provider": "cint", "external_id": "ext-1", "quota_remaining": 5, "cpi": {"amount_minor": 500, "currency": "INR"}, "conversion_rate": 0.3},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 200
    survey = create_resp.json()
    survey_id = survey.get("id") or survey.get("_id")

    elig_resp = client.post(f"/api/v1/surveys/{survey_id}/eligibility", json={"is_active_in_pool": True}, headers={"Authorization": f"Bearer {admin_token}"})
    assert elig_resp.status_code == 200
    assert elig_resp.json()["eligibility_is_active_in_pool"] is True

    allocate_resp = client.post(
        "/api/v1/traffic/ts-1/allocate",
        json={"candidate_survey_ids": [survey_id], "person_id": "p1", "vendor_id": "v1", "country_code": "IN", "respondent_ref": "r1"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert allocate_resp.status_code == 200
    allocation = allocate_resp.json()
    allocation_id = allocation.get("id") or allocation.get("_id")
    assert "stub" in allocation["redirect_url"]

    payload = {"org_id": ORG_A, "allocation_id": allocation_id, "provider": "cint", "external_event_id": "evt-1", "final_status": "complete", "payout": {"amount_minor": 200, "currency": "INR"}}
    body = json.dumps(payload).encode()
    callback_resp = client.post(f"/api/v1/surveys/{survey_id}/callback", content=body, headers={"X-Signature": _sign(body), "Content-Type": "application/json"})
    assert callback_resp.status_code == 200
    assert callback_resp.json()["final_status"] == "complete"


@pytest.mark.asyncio
async def test_callback_endpoint_requires_no_torpedo_session_but_does_require_a_valid_signature(client: TestClient):
    """The one deliberate exception to this codebase's usual auth chain — proven
    two ways: no Authorization header at all still reaches the handler (a genuine
    401-from-bad-signature, not a 401-from-missing-session), and a wrong signature
    is rejected even though no session was ever checked."""
    payload = {"org_id": ORG_A, "allocation_id": "does-not-exist", "provider": "cint", "external_event_id": "evt-1", "final_status": "complete", "payout": None}
    body = json.dumps(payload).encode()

    wrong_sig_resp = client.post("/api/v1/surveys/s1/callback", content=body, headers={"X-Signature": "0" * 64, "Content-Type": "application/json"})
    assert wrong_sig_resp.status_code == 401  # from SignatureInvalid, not from a missing bearer token

    right_sig_resp = client.post("/api/v1/surveys/s1/callback", content=body, headers={"X-Signature": _sign(body), "Content-Type": "application/json"})
    assert right_sig_resp.status_code == 400  # signature passed; fails later because allocation "does-not-exist" is a real 400, proving the signature check ran first and is the actual gate
