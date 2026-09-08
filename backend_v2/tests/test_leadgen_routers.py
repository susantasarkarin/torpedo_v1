"""
HTTP-level leadgen tests, through the real wired app (`app.main.app`), same pattern
as `test_identity_routers.py`. Deliberately narrow: permission enforcement and org
isolation are what's *new* at this layer — the qualification math, AI handling, and
enrollment mechanics are already exhaustively covered in `test_leadgen_service.py`
and re-proving them through HTTP would be redundant, not additional coverage.
"""

from datetime import timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.auth.dependencies import get_auth_service, get_rbac_service
from app.auth.models import Credential, Session
from app.auth.service import AuthService
from app.identity.facets import AuthIdentity, CustomerBilling, EmployeeRecord, LeadState, PanelistProfile, VendorProfile
from app.identity.models import Account, AccountBrandRelationship, Person
from app.leadgen.models import DeadLetterEvent, LeadEnrollment, RawLeadEvent
from app.models.ai_proposal import AiProposal
from app.leadgen.routers import get_leadgen_service
from app.leadgen.service import LeadGenService
from app.outreach.suppression import Suppression, SuppressionService
from app.main import app
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import LEAD_ASSIGN, LEAD_INGEST, LEAD_QUALIFY, LEAD_READ
from app.rbac.service import RBACService
from app.identity.facet_service import FacetService
from app.identity.service import IdentityService

ORG_A = "org-A"
ORG_B = "org-B"


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
def leadgen_service(db) -> LeadGenService:
    identity = IdentityService(
        people=CanonicalRepository(db["people"], Person),
        accounts=CanonicalRepository(db["accounts"], Account),
        brand_relationships=CanonicalRepository(db["account_brand_relationships"], AccountBrandRelationship),
        activities=CanonicalRepository(db["activities"], Activity),
    )
    facets = FacetService(
        people=CanonicalRepository(db["people"], Person),
        accounts=CanonicalRepository(db["accounts"], Account),
        activities=CanonicalRepository(db["activities"], Activity),
        lead_states=CanonicalRepository(db["lead_states"], LeadState),
        panelist_profiles=CanonicalRepository(db["panelist_profiles"], PanelistProfile),
        customer_billing=CanonicalRepository(db["customer_billing"], CustomerBilling),
        vendor_profiles=CanonicalRepository(db["vendor_profiles"], VendorProfile),
        employee_records=CanonicalRepository(db["employee_records"], EmployeeRecord),
        auth_identities=CanonicalRepository(db["auth_identities"], AuthIdentity),
    )
    suppression = SuppressionService(CanonicalRepository(db["suppressions"], Suppression))
    return LeadGenService(
        identity, facets, suppression,
        raw_events=CanonicalRepository(db["raw_lead_events"], RawLeadEvent),
        ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal),
        enrollments=CanonicalRepository(db["lead_enrollments"], LeadEnrollment),
        dead_letters=CanonicalRepository(db["dead_letters"], DeadLetterEvent),
        activities=CanonicalRepository(db["activities"], Activity),
    )


@pytest.fixture
def client(auth_service, rbac_service, leadgen_service) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_leadgen_service] = lambda: leadgen_service
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

    resp = client.post(
        "/api/v1/leads/ingest",
        json={"source_type": "web_form", "source_record_id": "evt-1", "payload": {"email": "a@b.com"}},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_assign_sets_owner_and_team_through_http(client: TestClient, auth_service, rbac_service, leadgen_service: LeadGenService):
    """The scenario named explicitly: owner/team permission enforcement, and the
    values, proven through a real HTTP request."""
    token = await _make_authenticated_user(
        auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[LEAD_INGEST, LEAD_QUALIFY, LEAD_ASSIGN, LEAD_READ]
    )

    ingest_resp = client.post(
        "/api/v1/leads/ingest",
        json={"source_type": "web_form", "source_record_id": "evt-1", "payload": {"email": "carol@acme.com", "company_domain": "acme.com"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    lead_state_id = ingest_resp.json()["lead_state_id"]

    # Force a qualifying score directly, same pragmatic setup as the service-layer
    # suite's _qualifying_lead helper — this file's job is permission/org
    # enforcement, not re-deriving the scoring math via HTTP. Title alone (senior
    # marker -> title=3 + seniority=1 = 4) clears QUALIFY_THRESHOLD; industry is
    # patched too for margin. Neither is reachable via ingest()'s payload today —
    # via the PassthroughAIClassifier HTTP path, title/country never get set at
    # all (ingest() doesn't accept a title field, and country has no source in this
    # slice), which is exactly why this file patches the DB directly rather than
    # pretending the HTTP surface can drive a full qualifying signal on its own yet.
    lead = await leadgen_service.get_lead(lead_state_id)
    await leadgen_service._identity._accounts.update(lead.account_id, 1, {"industry": "software"}, updated_by="test")
    person = await leadgen_service._identity.get_person(lead.person_id)
    await leadgen_service._identity._people.update(person.id, person.version, {"title": "VP of Sales"}, updated_by="test")

    client.post(f"/api/v1/leads/{lead_state_id}/qualify", headers={"Authorization": f"Bearer {token}"})

    assign_resp = client.post(
        f"/api/v1/leads/{lead_state_id}/assign", json={"owner": "rep-1", "team": "enterprise"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert assign_resp.status_code == 200
    assert assign_resp.json()["owner"] == "rep-1"
    assert assign_resp.json()["team"] == "enterprise"


@pytest.mark.asyncio
async def test_cross_org_lead_access_fails(client: TestClient, auth_service, rbac_service):
    alice_token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[LEAD_INGEST, LEAD_READ])
    bob_token = await _make_authenticated_user(auth_service, rbac_service, user_id="bob", org_id=ORG_B, permissions=[LEAD_READ])

    ingest_resp = client.post(
        "/api/v1/leads/ingest",
        json={"source_type": "web_form", "source_record_id": "evt-1", "payload": {"email": "a@b.com"}},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    lead_state_id = ingest_resp.json()["lead_state_id"]

    bob_resp = client.get(f"/api/v1/leads/{lead_state_id}", headers={"Authorization": f"Bearer {bob_token}"})

    assert bob_resp.status_code == 404


@pytest.mark.asyncio
async def test_assigning_another_orgs_lead_through_http_is_400_not_a_cross_tenant_write(client: TestClient, auth_service, rbac_service, leadgen_service: LeadGenService):
    """Phase 15 security audit finding, proven at the HTTP layer (not just
    the service layer test_leadgen_service.py already covers): a user in
    ORG_A with LEAD_ASSIGN must not be able to assign a lead belonging to
    ORG_B just by knowing or guessing its id."""
    org_b_token = await _make_authenticated_user(auth_service, rbac_service, user_id="bob", org_id=ORG_B, permissions=[LEAD_INGEST, LEAD_READ])
    ingest_resp = client.post(
        "/api/v1/leads/ingest",
        json={"source_type": "web_form", "source_record_id": "evt-org-b", "payload": {"email": "org-b-lead@acme.com"}},
        headers={"Authorization": f"Bearer {org_b_token}"},
    )
    org_b_lead_id = ingest_resp.json()["lead_state_id"]
    org_b_lead = await leadgen_service.get_lead(org_b_lead_id)
    await leadgen_service._facets.update_lead_state(org_b_lead.id, org_b_lead.version, {"state": "QUALIFIED"}, updated_by="test")

    attacker_token = await _make_authenticated_user(auth_service, rbac_service, user_id="mallory", org_id=ORG_A, permissions=[LEAD_ASSIGN])
    resp = client.post(
        f"/api/v1/leads/{org_b_lead_id}/assign", json={"owner": "rep-1"},
        headers={"Authorization": f"Bearer {attacker_token}"},
    )
    assert resp.status_code == 400

    untouched = await leadgen_service.get_lead(org_b_lead_id)
    assert untouched.owner is None


@pytest.mark.asyncio
async def test_list_account_contacts_through_http(client: TestClient, auth_service, rbac_service, leadgen_service: LeadGenService):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[LEAD_INGEST, LEAD_READ])
    client.post(
        "/api/v1/leads/ingest",
        json={"source_type": "web_form", "source_record_id": "evt-1", "payload": {"email": "alice@acme.com", "company_domain": "acme.com", "company_name": "Acme"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    ingest_resp = client.post(
        "/api/v1/leads/ingest",
        json={"source_type": "web_form", "source_record_id": "evt-2", "payload": {"email": "bob@acme.com", "company_domain": "acme.com", "company_name": "Acme"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    lead_state_id = ingest_resp.json()["lead_state_id"]
    lead = await leadgen_service.get_lead(lead_state_id)

    resp = client.get(f"/api/v1/accounts/{lead.account_id}/contacts", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    emails = {p["primary_email"] for p in resp.json()}
    assert emails == {"alice@acme.com", "bob@acme.com"}


@pytest.mark.asyncio
async def test_list_account_contacts_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.get("/api/v1/accounts/does-not-exist/contacts", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_account_contacts_for_another_orgs_account_is_404_not_403(client: TestClient, auth_service, rbac_service, leadgen_service: LeadGenService):
    other_orgs_account = await leadgen_service._identity.create_account(org_id=ORG_B, actor="mallory", name="Victim Co")
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[LEAD_READ])

    resp = client.get(f"/api/v1/accounts/{other_orgs_account.id}/contacts", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 404
