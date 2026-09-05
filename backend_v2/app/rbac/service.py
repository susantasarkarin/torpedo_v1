"""
RBACService — the single authority for permission and approval decisions.

Register §5.7 (decision B-07): "No approval logic may be reimplemented inside the
invoice, payment, expense, bill, credit-note, or reward services — all of them call
the same policy service. This is I-1 applied to authorization: a second approval
implementation is a defect by definition, even if correct." Every rule in that section
is implemented exactly once, here — not restated, not partially reimplemented, by any
domain service built on top of this in a later slice.

Deny-by-default is unconditional in this module. There is deliberately no
`RBAC_ENABLED` flag anywhere in v2. v1's version of that flag defaulted to `false`
(register §5.6), and its mere existence was what let every fine-grained check be
skipped in production for as long as nobody flipped it — the safest value a feature
flag guarding authorization can have is not existing.
"""

from __future__ import annotations

from app.models.base import CanonicalRepository
from app.models.money import Money
from app.rbac.identity import PrincipalType, ResolvedIdentity
from app.rbac.models import ApprovalAuthority, Role, UserRole
from app.rbac.permissions import ADMIN_WILDCARD, APPROVAL_PERMISSIONS, ROLE_ASSIGN


class PermissionDenied(Exception):
    """Raised, never returned as a bare `False` and silently discarded — a caller
    can't accidentally treat "denied" as "empty result," which is a different failure
    with a different correct response."""


class MultiOrgNotSupported(Exception):
    """A user has UserRole grants spanning more than one org. See resolve_identity()."""


class RBACService:
    def __init__(
        self,
        user_roles: CanonicalRepository[UserRole],
        roles: CanonicalRepository[Role],
        approval_authorities: CanonicalRepository[ApprovalAuthority],
    ):
        self._user_roles = user_roles
        self._roles = roles
        self._approval_authorities = approval_authorities

    async def resolve_identity(
        self,
        user_id: str,
        *,
        principal_type: PrincipalType = "user",
        real_actor_id: str | None = None,
    ) -> ResolvedIdentity:
        """
        The D-01 fix. Looks up this user's actual `UserRole` grants and never returns
        a default role for an unresolvable or role-less user.

        `org_id` on the returned identity comes from the user's own grant records —
        there is no parameter on this method that lets a caller assert which org a
        request belongs to. That is deliberate: v1's outreach router bug (D-15) was
        exactly this shape of mistake (a value that should come from the server's own
        records instead arriving as a caller-supplied parameter) applied to a database
        name instead of an org id. The fix generalizes.

        `principal_type` is supplied by the caller (the not-yet-built auth/token layer
        determines whether a credential belongs to a human session or an AI-agent
        service account) — this method's job starts after that determination, matching
        where the actual v1 defect lived: verification worked, *role resolution after
        verification* did not.
        """
        grants = await self._user_roles.find_all({"user_id": user_id})
        if not grants:
            return ResolvedIdentity(
                user_id=user_id,
                org_id="",
                principal_type=principal_type,
                roles=frozenset(),
                permissions=frozenset(),
                real_actor_id=real_actor_id or user_id,
            )

        # Single-tenant today (see app/config.py's default_org_id) — every grant for a
        # given user_id is expected to share one org_id. Multi-org membership is later,
        # explicit scope (a ResolvedIdentity carrying one org_id, not a per-org
        # multi-identity model) — until it's designed, silently taking grants[0] would
        # hide a real bug (a user accidentally granted roles in two orgs) behind
        # whichever grant happened to sort first. Fail loudly instead.
        distinct_orgs = {g.org_id for g in grants}
        if len(distinct_orgs) > 1:
            raise MultiOrgNotSupported(
                f"user {user_id} has grants in multiple orgs {distinct_orgs} — "
                "multi-org membership is not yet a supported identity shape"
            )
        org_id = grants[0].org_id

        role_codes = frozenset(g.role_code for g in grants)
        permissions: set[str] = set()
        for code in role_codes:
            role = await self._roles.find_one({"code": code})
            if role:
                permissions.update(role.permissions)

        return ResolvedIdentity(
            user_id=user_id,
            org_id=org_id,
            principal_type=principal_type,
            roles=role_codes,
            permissions=frozenset(permissions),
            real_actor_id=real_actor_id or user_id,
        )

    def has_permission(self, identity: ResolvedIdentity, code: str, *, target_org_id: str) -> bool:
        """
        Deny-by-default, org-scoped. The admin wildcard grants everything EXCEPT the
        codes in `APPROVAL_PERMISSIONS` — the D-14 half of the Phase 1 gate. Fixing
        D-01 alone is not sufficient: an unqualified wildcard would still silently
        confer approval authority the instant real roles resolve correctly.
        """
        if not target_org_id or identity.org_id != target_org_id:
            return False
        if code in identity.permissions:
            return True
        if ADMIN_WILDCARD in identity.permissions and code not in APPROVAL_PERMISSIONS:
            return True
        return False

    def require_permission(self, identity: ResolvedIdentity, code: str, *, target_org_id: str) -> None:
        if not self.has_permission(identity, code, target_org_id=target_org_id):
            raise PermissionDenied(f"{identity.user_id} lacks {code} in org {target_org_id}")

    async def get_approval_ceiling(self, identity: ResolvedIdentity, entity_type: str) -> Money | None:
        """Per-user ceiling takes precedence over a per-role ceiling if both exist.
        The single evaluator for "how much can this identity approve" — nothing else
        in v2 computes this independently."""
        by_user = await self._approval_authorities.find_one(
            {"user_id": identity.user_id, "entity_type": entity_type}
        )
        if by_user:
            return by_user.max_amount
        for role_code in identity.roles:
            by_role = await self._approval_authorities.find_one(
                {"role_code": role_code, "entity_type": entity_type}
            )
            if by_role:
                return by_role.max_amount
        return None

    async def can_approve(
        self,
        identity: ResolvedIdentity,
        *,
        entity_type: str,
        amount: Money,
        creator_id: str,
    ) -> bool:
        """
        Every rule in register §5.7, in one place, so no domain service can
        reimplement — and subtly get wrong — any one of them individually:

        - self-approval blocked, checked against `real_actor_id` so impersonation
          can't launder around it (§5.7: "impersonation cannot be used to satisfy a
          separation-of-duties requirement")
        - AI/system principals can never approve, regardless of permissions held
          (spec §31: "no agent may modify money")
        - the admin wildcard does not satisfy the approval-permission check — there is
          no branch here that treats `ADMIN_WILDCARD` as "unlimited approval." That
          was D-14, and this method is where it's fixed in code, not just in policy.
        """
        if identity.real_actor_id == creator_id:
            return False
        if identity.principal_type != "user":
            return False

        approve_code = f"{entity_type}.approve"
        if approve_code not in identity.permissions:
            return False  # deliberately: wildcard membership does not reach here

        ceiling = await self.get_approval_ceiling(identity, entity_type)
        if ceiling is None or ceiling.currency != amount.currency:
            return False
        return amount.amount_minor <= ceiling.amount_minor

    async def assign_role(
        self,
        actor: ResolvedIdentity,
        *,
        target_user_id: str,
        role_code: str,
        target_org_id: str,
    ) -> UserRole:
        """
        Fixes the register's finding (§5.6) that v1 had no self-assignment guard on
        role grants, even though the identical guard already existed correctly for
        self-deletion in the same codebase — "which shows the guard pattern was known
        and simply not applied here." Mirrored unconditionally: the check runs before
        the permission check, so a misconfigured permission grant can't reopen it.
        """
        if actor.real_actor_id == target_user_id:
            raise PermissionDenied("cannot assign a role to yourself")
        self.require_permission(actor, ROLE_ASSIGN, target_org_id=target_org_id)

        grant = UserRole(
            org_id=target_org_id,
            created_by=actor.user_id,
            updated_by=actor.user_id,
            user_id=target_user_id,
            role_code=role_code,
        )
        return await self._user_roles.insert(grant)
