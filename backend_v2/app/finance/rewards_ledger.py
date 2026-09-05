"""
RewardLedgerEntry / RewardLedgerService — the rewards-ledger **boundary** Slice 8 was
scoped to build, not the full panelist redemption workflow (that's Slice 9's — the
user's own three-slice split names this explicitly: "Slice 8: rewards ledger
boundary. Slice 9: rewards ledger integration").

**Balance is always derived by summing entries, never a stored field**
(endpoint_catalogue.md: "Sum of ledger entries at read time — never a stored field").
This is the direct fix for the class of defect behind D-38 (drift between a cached
scalar and the transactions that were supposed to keep it current) applied to
rewards instead of AR/AP.

**`clawback()` is the D-12 fix's write path**: v1's finding was "supplier reversal
never reaches the reward ledger — panelist keeps points on a reversed complete."
This method is that missing path, made real and approval-gated (register §5.7 names
clawback as *always* requiring approval, no exception). `PaymentService` in this
slice does not call it yet — wiring "a reversed payment tied to a completed survey
reward triggers a clawback" needs a completed-survey/reward-eligibility concept that
belongs to Slice 9's `SurveyResponse`/panel domain, not this one. The boundary
(a real, tested, approval-gated clawback path) exists; the caller is Slice 9's to
build.

**Concurrency caveat, stated once here rather than left implicit**: `debit()`
reads the derived balance, checks it, then inserts — a genuine read-then-write gap
under concurrent debits against the same panelist, unlike `BudgetService`'s
single-document atomic `$inc`. A ledger of individually meaningful entries can't use
that trick directly; closing this gap for real needs either a Mongo transaction or a
version-guarded balance-cache document, both deferred. Documented, not silently
shipped as if it were race-free.
"""

from __future__ import annotations

from app.models.base import CanonicalDocument, CanonicalRepository
from app.models.money import Money
from app.rbac.identity import ResolvedIdentity
from app.rbac.service import RBACService


class RewardLedgerError(Exception):
    """Insufficient balance, currency mismatch, or a clawback denied by approval
    policy. Same discipline as FinanceError/OutreachError/LeadGenError."""


class RewardLedgerEntry(CanonicalDocument):
    panelist_person_id: str
    entry_type: str  # "credit" | "debit" | "clawback"
    amount: Money  # always positive; entry_type carries direction
    reference_type: str  # e.g. "survey_completion", "payment_reversal", "manual"
    reference_id: str


class RewardLedgerService:
    def __init__(self, entries: CanonicalRepository[RewardLedgerEntry]):
        self._entries = entries

    async def get_balance(self, panelist_person_id: str, *, currency: str) -> Money:
        entries = await self._entries.find_all({"panelist_person_id": panelist_person_id})
        balance_minor = 0
        for entry in entries:
            if entry.amount.currency != currency:
                continue
            if entry.entry_type == "credit":
                balance_minor += entry.amount.amount_minor
            else:  # debit | clawback
                balance_minor -= entry.amount.amount_minor
        return Money(amount_minor=balance_minor, currency=currency)

    async def credit(
        self, *, org_id: str, actor: str, panelist_person_id: str, amount: Money, reference_type: str, reference_id: str
    ) -> RewardLedgerEntry:
        if amount.amount_minor <= 0:
            raise RewardLedgerError("credit amount must be positive")
        return await self._entries.insert(
            RewardLedgerEntry(
                org_id=org_id, created_by=actor, updated_by=actor,
                panelist_person_id=panelist_person_id, entry_type="credit", amount=amount,
                reference_type=reference_type, reference_id=reference_id,
            )
        )

    async def debit(
        self, *, org_id: str, actor: str, panelist_person_id: str, amount: Money, reference_type: str, reference_id: str
    ) -> RewardLedgerEntry:
        if amount.amount_minor <= 0:
            raise RewardLedgerError("debit amount must be positive")
        balance = await self.get_balance(panelist_person_id, currency=amount.currency)
        if balance.amount_minor < amount.amount_minor:
            raise RewardLedgerError(f"insufficient balance: {balance.amount_minor} < {amount.amount_minor}")
        return await self._entries.insert(
            RewardLedgerEntry(
                org_id=org_id, created_by=actor, updated_by=actor,
                panelist_person_id=panelist_person_id, entry_type="debit", amount=amount,
                reference_type=reference_type, reference_id=reference_id,
            )
        )

    async def clawback(
        self,
        *,
        org_id: str,
        actor: str,
        identity: ResolvedIdentity,
        rbac: RBACService,
        panelist_person_id: str,
        amount: Money,
        reference_type: str,
        reference_id: str,
        creator_id: str,
    ) -> RewardLedgerEntry:
        """No self-approval, no exception, per register §5.7. `creator_id` is whoever
        created the thing being clawed back (e.g. the reversed Payment's creator) —
        not necessarily the panelist."""
        if not await rbac.can_approve(identity, entity_type="rewards.clawback", amount=amount, creator_id=creator_id):
            raise RewardLedgerError("clawback denied: insufficient approval authority")
        return await self._entries.insert(
            RewardLedgerEntry(
                org_id=org_id, created_by=actor, updated_by=actor,
                panelist_person_id=panelist_person_id, entry_type="clawback", amount=amount,
                reference_type=reference_type, reference_id=reference_id,
            )
        )
