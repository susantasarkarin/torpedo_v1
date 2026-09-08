"""
HTTP-level finance tests, through the real wired app, same pattern as
`test_leadgen_routers.py`/`test_outreach_routers.py`. Permission enforcement and org
isolation are what's new at this layer — the money/approval/state-machine behavior is
already exhaustively covered in test_finance_service.py.
"""

from datetime import timezone

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.auth.dependencies import get_auth_service, get_rbac_service
from app.auth.models import Credential, Session
from app.auth.service import AuthService
from app.finance.analytics import FinanceAnalyticsService
from app.finance.models import Bill, BankAccount, CreditNote, Expense, Invoice, Payment, ReconciliationRecord
from app.finance.routers import (
    get_bank_account_service,
    get_bill_service,
    get_credit_note_service,
    get_expense_service,
    get_finance_analytics_service,
    get_invoice_service,
    get_payment_service,
    get_reconciliation_service,
    get_reward_ledger_service,
    get_sequence_service,
)
from app.finance.rewards_ledger import RewardLedgerEntry, RewardLedgerService
from app.finance.sequence import SequenceService
from app.finance.service import BankAccountService, BillService, CreditNoteService, ExpenseService, InvoiceService, PaymentService, ReconciliationService
from app.main import app
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import FINANCE_ANALYTICS_READ, INVOICE_CREATE, INVOICE_SEND, INVOICE_SUBMIT
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
    return RBACService(
        user_roles=CanonicalRepository(db["user_roles"], UserRole), roles=CanonicalRepository(db["roles"], Role),
        approval_authorities=CanonicalRepository(db["approval_authorities"], ApprovalAuthority),
    )


@pytest.fixture
def sequences(db) -> SequenceService:
    return SequenceService(db["finance_sequences"])


@pytest.fixture
def invoice_service(db, sequences) -> InvoiceService:
    return InvoiceService(CanonicalRepository(db["invoices"], Invoice), sequences, CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def bill_service(db, sequences) -> BillService:
    return BillService(CanonicalRepository(db["bills"], Bill), sequences, CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def finance_analytics_service(db) -> FinanceAnalyticsService:
    return FinanceAnalyticsService(CanonicalRepository(db["invoices"], Invoice), CanonicalRepository(db["bills"], Bill))


@pytest.fixture
def payment_service(db, sequences) -> PaymentService:
    return PaymentService(CanonicalRepository(db["payments"], Payment), CanonicalRepository(db["invoices"], Invoice), CanonicalRepository(db["bills"], Bill), sequences, CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def expense_service(db) -> ExpenseService:
    return ExpenseService(CanonicalRepository(db["expenses"], Expense), CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def credit_note_service(db, sequences) -> CreditNoteService:
    return CreditNoteService(CanonicalRepository(db["credit_notes"], CreditNote), CanonicalRepository(db["invoices"], Invoice), sequences, CanonicalRepository(db["activities"], Activity))


@pytest.fixture
def bank_account_service(db) -> BankAccountService:
    return BankAccountService(CanonicalRepository(db["bank_accounts"], BankAccount))


@pytest.fixture
def reconciliation_service(db) -> ReconciliationService:
    return ReconciliationService(CanonicalRepository(db["reconciliation_records"], ReconciliationRecord), CanonicalRepository(db["payments"], Payment))


@pytest.fixture
def reward_ledger_service(db) -> RewardLedgerService:
    return RewardLedgerService(CanonicalRepository(db["reward_ledger_entries"], RewardLedgerEntry))


@pytest.fixture
def client(auth_service, rbac_service, invoice_service, bill_service, payment_service, expense_service, credit_note_service, bank_account_service, reconciliation_service, reward_ledger_service, sequences, finance_analytics_service) -> TestClient:
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_invoice_service] = lambda: invoice_service
    app.dependency_overrides[get_bill_service] = lambda: bill_service
    app.dependency_overrides[get_payment_service] = lambda: payment_service
    app.dependency_overrides[get_expense_service] = lambda: expense_service
    app.dependency_overrides[get_credit_note_service] = lambda: credit_note_service
    app.dependency_overrides[get_bank_account_service] = lambda: bank_account_service
    app.dependency_overrides[get_finance_analytics_service] = lambda: finance_analytics_service
    app.dependency_overrides[get_reconciliation_service] = lambda: reconciliation_service
    app.dependency_overrides[get_reward_ledger_service] = lambda: reward_ledger_service
    app.dependency_overrides[get_sequence_service] = lambda: sequences
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
    return {"description": "widget", "quantity": 1, "unit_price_minor": 100_000, "gst_rate_bps": 1800}


def _gst():
    return {"place_of_supply": "KA"}


@pytest.mark.asyncio
async def test_create_invoice_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.post(
        "/api/v1/finance/invoices",
        json={"customer_account_id": "cust-1", "line_items": [_line_item()], "gst_details": _gst(), "currency": "INR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_approve_requires_the_specific_approve_permission_not_just_submit(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[INVOICE_CREATE, INVOICE_SUBMIT])

    create_resp = client.post(
        "/api/v1/finance/invoices",
        json={"customer_account_id": "cust-1", "line_items": [_line_item()], "gst_details": _gst(), "currency": "INR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    invoice_id = create_resp.json()["_id"] if "_id" in create_resp.json() else create_resp.json()["id"]
    client.post(f"/api/v1/finance/invoices/{invoice_id}/submit", headers={"Authorization": f"Bearer {token}"})

    approve_resp = client.post(f"/api/v1/finance/invoices/{invoice_id}/approve", headers={"Authorization": f"Bearer {token}"})
    assert approve_resp.status_code == 403


@pytest.mark.asyncio
async def test_full_invoice_flow_through_http_including_approval_and_payment(client: TestClient, auth_service, rbac_service):
    creator_token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[INVOICE_CREATE, INVOICE_SUBMIT, INVOICE_SEND, "finance.payment.create", "finance.read"])
    approver_token = await _make_authenticated_user(auth_service, rbac_service, user_id="bob", org_id=ORG_A, permissions=["finance.invoice.approve"])
    await rbac_service._approval_authorities.insert(
        ApprovalAuthority(org_id=ORG_A, created_by="seed", updated_by="seed", user_id="bob", entity_type="finance.invoice", max_amount={"amount_minor": 10_000_000, "currency": "INR"})
    )

    create_resp = client.post(
        "/api/v1/finance/invoices",
        json={"customer_account_id": "cust-1", "line_items": [_line_item()], "gst_details": _gst(), "currency": "INR"},
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert create_resp.status_code == 200
    invoice = create_resp.json()
    invoice_id = invoice.get("id") or invoice.get("_id")
    total_minor = invoice["total"]["amount_minor"]

    submit_resp = client.post(f"/api/v1/finance/invoices/{invoice_id}/submit", headers={"Authorization": f"Bearer {creator_token}"})
    assert submit_resp.status_code == 200
    assert submit_resp.json()["status"] == "pending_approval"

    approve_resp = client.post(f"/api/v1/finance/invoices/{invoice_id}/approve", headers={"Authorization": f"Bearer {approver_token}"})
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"

    send_resp = client.post(f"/api/v1/finance/invoices/{invoice_id}/send", headers={"Authorization": f"Bearer {creator_token}"})
    assert send_resp.status_code == 200
    assert send_resp.json()["status"] == "sent"

    payment_resp = client.post(
        "/api/v1/finance/payments",
        json={"direction": "received", "amount": {"amount_minor": total_minor, "currency": "INR"}, "method": "bank_transfer", "idempotency_key": "k1", "invoice_id": invoice_id},
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert payment_resp.status_code == 200
    assert payment_resp.json()["status"] == "recorded"

    get_resp = client.get(f"/api/v1/finance/invoices/{invoice_id}", headers={"Authorization": f"Bearer {creator_token}"})
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "paid"


@pytest.mark.asyncio
async def test_cross_org_invoice_read_is_404_not_403(client: TestClient, auth_service, rbac_service):
    alice_token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[INVOICE_CREATE, "finance.read"])
    bob_token = await _make_authenticated_user(auth_service, rbac_service, user_id="bob", org_id=ORG_B, permissions=["finance.read"])

    create_resp = client.post(
        "/api/v1/finance/invoices",
        json={"customer_account_id": "cust-1", "line_items": [_line_item()], "gst_details": _gst(), "currency": "INR"},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    invoice = create_resp.json()
    invoice_id = invoice.get("id") or invoice.get("_id")

    bob_resp = client.get(f"/api/v1/finance/invoices/{invoice_id}", headers={"Authorization": f"Bearer {bob_token}"})
    assert bob_resp.status_code == 404


@pytest.mark.asyncio
async def test_ar_ageing_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.get("/api/v1/finance/analytics/ar-ageing", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ar_ageing_with_permission_returns_the_real_report(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[FINANCE_ANALYTICS_READ])
    resp = client.get("/api/v1/finance/analytics/ar-ageing", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {}  # no invoices seeded — a real empty report, not a fabricated one


@pytest.mark.asyncio
async def test_ap_ageing_without_permission_is_403(client: TestClient, auth_service, rbac_service):
    token = await _make_authenticated_user(auth_service, rbac_service, user_id="alice", org_id=ORG_A, permissions=[])
    resp = client.get("/api/v1/finance/analytics/ap-ageing", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_submitting_another_orgs_invoice_through_http_is_400_not_a_cross_tenant_write(client: TestClient, auth_service, rbac_service):
    """Phase 15 security audit finding, proven at the HTTP layer (not just the
    service layer test_finance_service.py already covers): a user in ORG_A
    with INVOICE_SUBMIT must not be able to submit an invoice belonging to
    ORG_B just by knowing or guessing its id."""
    org_b_token = await _make_authenticated_user(auth_service, rbac_service, user_id="mallory-setup", org_id=ORG_B, permissions=[INVOICE_CREATE])
    create_resp = client.post(
        "/api/v1/finance/invoices",
        json={"customer_account_id": "cust-1", "line_items": [_line_item()], "gst_details": _gst(), "currency": "INR"},
        headers={"Authorization": f"Bearer {org_b_token}"},
    )
    org_b_invoice_id = create_resp.json().get("_id") or create_resp.json().get("id")

    attacker_token = await _make_authenticated_user(auth_service, rbac_service, user_id="mallory", org_id=ORG_A, permissions=[INVOICE_SUBMIT])
    resp = client.post(f"/api/v1/finance/invoices/{org_b_invoice_id}/submit", headers={"Authorization": f"Bearer {attacker_token}"})
    assert resp.status_code == 400

    org_b_read_token = await _make_authenticated_user(auth_service, rbac_service, user_id="org-b-reader", org_id=ORG_B, permissions=["finance.read"])
    untouched = client.get(f"/api/v1/finance/invoices/{org_b_invoice_id}", headers={"Authorization": f"Bearer {org_b_read_token}"})
    assert untouched.json()["status"] == "draft"
