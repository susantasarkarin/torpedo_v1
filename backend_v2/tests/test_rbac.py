"""
Each test in this file is named after the historical failure it proves cannot recur —
not after the method it happens to call. This is deliberate: the register's findings
are about specific incidents (D-01, D-14, and the register §5.6/§5.7 gaps), and a test
suite organized by method name would let a correct-looking implementation still miss
the actual failure mode.
"""

import pytest
from datetime import timezone
from mongomock_motor import AsyncMongoMockClient

from app.models.base import CanonicalRepository
from app.models.money import Money
from app.rbac.identity import ResolvedIdentity
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import ADMIN_WILDCARD, ROLE_ASSIGN
from app.rbac.service import PermissionDenied, RBACService

ORG = "org-A"
OTHER_ORG = "org-B"


@pytest.fixture
def rbac() -> RBACService:
    db = AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]
    return RBACService(
        user_roles=CanonicalRepository(db["user_roles"], UserRole),
        roles=CanonicalRepository(db["roles"], Role),
        approval_authorities=CanonicalRepository(db["approval_authorities"], ApprovalAuthority),
    )


def _identity(
    user_id: str,
    *,
    org_id: str = ORG,
    permissions: frozenset[str] = frozenset(),
    roles: frozenset[str] = frozenset(),
    principal_type: str = "user",
    real_actor_id: str | None = None,
) -> ResolvedIdentity:
    return ResolvedIdentity(
        user_id=user_id,
        org_id=org_id,
        principal_type=principal_type,
        roles=roles,
        permissions=permissions,
        real_actor_id=real_actor_id or user_id,
    )


# ---------------------------------------------------------------------------
# D-01: a plain session token cannot become admin.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unresolved_user_gets_zero_permissions_never_admin(rbac: RBACService):
    """v1's operative resolver returned roles=['admin'] for ANY verified token,
    regardless of the database. Here: a user with zero UserRole grants must resolve
    to zero permissions — deny-by-default, not an implicit admin grant."""
    identity = await rbac.resolve_identity("brand-new-user")

    assert identity.roles == frozenset()
    assert identity.permissions == frozenset()
    assert ADMIN_WILDCARD not in identity.permissions
    assert rbac.has_permission(identity, "anything.at.all", target_org_id=ORG) is False


@pytest.mark.asyncio
async def test_resolved_identity_reflects_actual_stored_grants(rbac: RBACService):
    """The positive case: a user WITH a real grant gets exactly that grant's
    permissions, proving resolution actually reads the database rather than always
    returning empty (which would trivially "pass" the deny-by-default tests above
    for the wrong reason)."""
    await rbac._roles.insert(
        Role(org_id=ORG, created_by="seed", updated_by="seed", code="viewer", name="Viewer", permissions=["person.read"])
    )
    await rbac._user_roles.insert(
        UserRole(org_id=ORG, created_by="seed", updated_by="seed", user_id="alice", role_code="viewer")
    )

    identity = await rbac.resolve_identity("alice")

    assert identity.roles == frozenset({"viewer"})
    assert identity.permissions == frozenset({"person.read"})
    assert identity.org_id == ORG


# ---------------------------------------------------------------------------
# Org boundary
# ---------------------------------------------------------------------------


def test_user_from_org_a_cannot_access_org_b(rbac: RBACService):
    identity = _identity("alice", org_id=ORG, permissions=frozenset({"person.read"}))

    assert rbac.has_permission(identity, "person.read", target_org_id=ORG) is True
    assert rbac.has_permission(identity, "person.read", target_org_id=OTHER_ORG) is False


def test_missing_permission_is_denied(rbac: RBACService):
    identity = _identity("alice", permissions=frozenset({"person.read"}))

    assert rbac.has_permission(identity, "account.merge", target_org_id=ORG) is False
    with pytest.raises(PermissionDenied):
        rbac.require_permission(identity, "account.merge", target_org_id=ORG)


# ---------------------------------------------------------------------------
# D-14: admin does not bypass approval.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_cannot_approve_merely_by_being_admin(rbac: RBACService):
    """v1's admin role held the literal wildcard '*'. Under the v2 approval policy
    that would silently confer unlimited approval authority — this is the exact
    scenario D-14 names. An admin with no explicit `finance.invoice.approve`
    permission and no ApprovalAuthority ceiling must be refused."""
    admin = _identity("admin-bob", permissions=frozenset({ADMIN_WILDCARD}))

    can = await rbac.can_approve(
        admin, entity_type="finance.invoice", amount=Money(amount_minor=10_000, currency="INR"), creator_id="carol"
    )

    assert can is False


@pytest.mark.asyncio
async def test_approver_with_explicit_permission_and_sufficient_ceiling_succeeds(rbac: RBACService):
    """The positive path — proves can_approve isn't just returning False
    unconditionally. A real approver, with the explicit permission and a ceiling
    that covers the amount, approving someone else's request, succeeds."""
    await rbac._approval_authorities.insert(
        ApprovalAuthority(
            org_id=ORG, created_by="seed", updated_by="seed",
            user_id="dana", entity_type="finance.invoice",
            max_amount=Money(amount_minor=50_000, currency="INR"),
        )
    )
    approver = _identity("dana", permissions=frozenset({"finance.invoice.approve"}))

    can = await rbac.can_approve(
        approver, entity_type="finance.invoice", amount=Money(amount_minor=10_000, currency="INR"), creator_id="carol"
    )

    assert can is True


@pytest.mark.asyncio
async def test_approver_ceiling_exceeded_is_denied(rbac: RBACService):
    await rbac._approval_authorities.insert(
        ApprovalAuthority(
            org_id=ORG, created_by="seed", updated_by="seed",
            user_id="dana", entity_type="finance.invoice",
            max_amount=Money(amount_minor=5_000, currency="INR"),
        )
    )
    approver = _identity("dana", permissions=frozenset({"finance.invoice.approve"}))

    can = await rbac.can_approve(
        approver, entity_type="finance.invoice", amount=Money(amount_minor=10_000, currency="INR"), creator_id="carol"
    )

    assert can is False


# ---------------------------------------------------------------------------
# Separation of duties
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creator_cannot_self_approve(rbac: RBACService):
    await rbac._approval_authorities.insert(
        ApprovalAuthority(
            org_id=ORG, created_by="seed", updated_by="seed",
            user_id="carol", entity_type="finance.invoice",
            max_amount=Money(amount_minor=50_000, currency="INR"),
        )
    )
    carol = _identity("carol", permissions=frozenset({"finance.invoice.approve"}))

    can = await rbac.can_approve(
        carol, entity_type="finance.invoice", amount=Money(amount_minor=10_000, currency="INR"), creator_id="carol"
    )

    assert can is False


@pytest.mark.asyncio
async def test_impersonation_cannot_launder_self_approval(rbac: RBACService):
    """register §5.7: 'impersonation cannot be used to satisfy a separation-of-duties
    requirement.' carol creates a request, then impersonates dana (an approver) to
    try to approve her own request. The check uses real_actor_id — the actual human
    behind the session — not the impersonated identity's user_id."""
    await rbac._approval_authorities.insert(
        ApprovalAuthority(
            org_id=ORG, created_by="seed", updated_by="seed",
            user_id="dana", entity_type="finance.invoice",
            max_amount=Money(amount_minor=50_000, currency="INR"),
        )
    )
    carol_impersonating_dana = _identity(
        "dana", permissions=frozenset({"finance.invoice.approve"}), real_actor_id="carol"
    )

    can = await rbac.can_approve(
        carol_impersonating_dana,
        entity_type="finance.invoice",
        amount=Money(amount_minor=10_000, currency="INR"),
        creator_id="carol",
    )

    assert can is False


@pytest.mark.asyncio
async def test_ai_agent_cannot_approve(rbac: RBACService):
    """spec §31: 'no agent may modify money.' An AI principal holding the exact right
    permission and a sufficient ceiling must still be refused, purely on principal type."""
    await rbac._approval_authorities.insert(
        ApprovalAuthority(
            org_id=ORG, created_by="seed", updated_by="seed",
            user_id="agent-007", entity_type="finance.invoice",
            max_amount=Money(amount_minor=50_000, currency="INR"),
        )
    )
    agent = _identity(
        "agent-007", permissions=frozenset({"finance.invoice.approve"}), principal_type="ai_agent"
    )

    can = await rbac.can_approve(
        agent, entity_type="finance.invoice", amount=Money(amount_minor=10_000, currency="INR"), creator_id="carol"
    )

    assert can is False


# ---------------------------------------------------------------------------
# Self-assignment / privilege escalation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_caller_cannot_assign_a_role_to_themselves(rbac: RBACService):
    """register §5.6: v1 had no self-assignment guard on role grants, even though the
    identical guard already existed correctly for self-deletion in the same codebase.
    This must be refused even for a caller who legitimately holds ROLE_ASSIGN."""
    actor = _identity("eve", permissions=frozenset({ROLE_ASSIGN}))

    with pytest.raises(PermissionDenied):
        await rbac.assign_role(actor, target_user_id="eve", role_code="admin", target_org_id=ORG)


@pytest.mark.asyncio
async def test_caller_without_role_assign_permission_is_denied(rbac: RBACService):
    actor = _identity("eve", permissions=frozenset())

    with pytest.raises(PermissionDenied):
        await rbac.assign_role(actor, target_user_id="frank", role_code="viewer", target_org_id=ORG)


@pytest.mark.asyncio
async def test_legitimate_role_assignment_succeeds(rbac: RBACService):
    actor = _identity("eve", permissions=frozenset({ROLE_ASSIGN}))

    grant = await rbac.assign_role(actor, target_user_id="frank", role_code="viewer", target_org_id=ORG)

    assert grant.user_id == "frank"
    assert grant.role_code == "viewer"
    assert grant.org_id == ORG
