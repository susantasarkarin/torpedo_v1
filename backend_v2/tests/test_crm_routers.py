"""
HTTP-level CRM tests, through the real wired app. Permission enforcement and org
isolation are new at this layer; stage-machine/conversion behavior is exhaustively
covered in test_crm_service.py.
"""

from datetime import timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.auth.dependencies import get_auth_service, get_rbac_service
from app.auth.models import Credential, Session
from app.auth.service import AuthService
from app.crm.models import Opportunity
from app.crm.routers import get_opportunity_service
from app.crm.service import OpportunityService
from app.finance.models import Invoice
from app.finance.routers import get_invoice_service
from app.finance.sequence import SequenceService
from app.finance.service import InvoiceService
from app.main import app
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import OPPORTUNITY_CONVERT, OPPORTUNITY_CREATE, OPPORTUNITY_READ, OPPORTUNITY_UPDATE
from app.rbac.service import RBACService

ORG_A = "org-A"
ORG_B = "org-B"


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
def invoice_service(db) -> InvoiceService:
    return InvoiceService(CanonicalRepository(db["invoices"], Invoice), SequenceService(db["finance_sequences"]), CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def opportunity_service(db, invoice_service) -> OpportunityService:
    return OpportunityService(CanonicalRepository(db["opportunities"], Opportunity), CanonicalRepository(db["activities"], Activity), invoice_service)


@pytest.fixture
def client(auth_service, rbac_service, opportunity_service, invoice_service) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_opportunity_service] = lambda: opportunity_service
    app.dependency_overrides[get_invoice_service] = lambda: invoice_service
    yield TestClient(app)
    app.dependency_overrides.clear()


async def _make_authenticated_user(auth_service, rbac_service, *, user_id: str, org_id: str, permissions: list[str]) -> str:
    role_code = f"role-{user_id}"
    await rbac_service._roles.insert(Role(org_id=org_id, created_by="seed", updated_by="seed", code=role_code, name=role_code, permissions=permissions))
    await rbac_service._user_roles.insert(UserRole(org_id=org_id, created_by="seed", updated_by="seed", user_id=user_id, role_code=role_code))
    await auth_service.set_password(user_id, "correct-horse-battery")
    _, token = await auth_service.authenticate(user_id, "correct-horse-battery")
    return token


def _line_item():
    return {"description": "research project", "quantity": 1, "unit_price_minor": 500_000, "gst_rate_bps": 1800}


@pytest.mark.asyncio
async def test_create_opportunity_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.post("/api/v1/opportunities", json={"account_id": "acct-1"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_full_opportunity_to_invoice_flow_through_http(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(
        auth_service, rbac_service, user_id="alice", org_id=ORG_A,
        permissions=[OPPORTUNITY_CREATE, OPPORTUNITY_UPDATE, OPPORTUNITY_CONVERT, OPPORTUNITY_READ],
    )

    create_resp = client.post("/api/v1/opportunities", json={"account_id": "acct-1", "amount": {"amount_minor": 500000, "currency": "INR"}}, headers={"Authorization": f"Bearer {token}"})
    assert create_resp.status_code == 200
    opp = create_resp.json()
    opp_id = opp.get("id") or opp.get("_id")
    assert opp["stage"] == "new"

    stage_resp = client.post(f"/api/v1/opportunities/{opp_id}/stage", json={"stage": "won"}, headers={"Authorization": f"Bearer {token}"})
    assert stage_resp.status_code == 200
    assert stage_resp.json()["stage"] == "won"

    convert_resp = client.post(
        f"/api/v1/opportunities/{opp_id}/convert",
        json={"line_items": [_line_item()], "gst_details": {"place_of_supply": "KA"}, "currency": "INR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert convert_resp.status_code == 200
    invoice = convert_resp.json()
    assert invoice["status"] == "draft"
    assert (invoice.get("opportunity_id")) == opp_id

    get_resp = client.get(f"/api/v1/opportunities/{opp_id}", headers={"Authorization": f"Bearer {token}"})
    assert get_resp.status_code == 200
    assert get_resp.json().get("converted_invoice_id") == (invoice.get("id") or invoice.get("_id"))


@pytest.mark.asyncio
async def test_cross_org_opportunity_read_is_404_not_403(client: TestClient, auth_service, rbac_service):
    alice_token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[OPPORTUNITY_CREATE])
    bob_token = await _make_authenticated_user(auth_service, rbac_service, user_id="bob", org_id=ORG_B, permissions=[OPPORTUNITY_READ])

    create_resp = client.post("/api/v1/opportunities", json={"account_id": "acct-1"}, headers={"Authorization": f"Bearer {alice_token}"})
    opp = create_resp.json()
    opp_id = opp.get("id") or opp.get("_id")

    bob_resp = client.get(f"/api/v1/opportunities/{opp_id}", headers={"Authorization": f"Bearer {bob_token}"})
    assert bob_resp.status_code == 404
