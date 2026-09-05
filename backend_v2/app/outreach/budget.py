"""
BudgetService — atomic daily send-cap reservation, the D-05/D-06/§5.3 fix.

The register names this defect twice, independently: "non-atomic shared budget"
(§5.3) and "Pipeline 5 budget race" (§5.3) — two pipelines, two non-atomic counters,
both racy. This module is the one counter every send path reserves against.

**Deliberate, narrow exception to "every write goes through `CanonicalRepository`"
(I-6):** `CanonicalRepository.update()` requires a version match — it has no way to
express "increment, then check the result against a cap, then roll back if over,"
because that's a conditional atomic upsert-increment, not a version-guarded set.
This service owns its own single-purpose Mongo collection directly instead. That is
a controlled, documented exception (this docstring *is* the audit trail), not a
loophole: nothing else in this codebase talks to Mongo outside a canonical
repository, and this class only ever does one thing — reserve/release a counter.

**Why this is still race-free**: `$inc` on a single document is atomic and
serialized by MongoDB itself — concurrent reservations against the same key never
lose an update, they queue. Two callers racing at exactly the cap both get a
genuine, distinct post-increment count back (e.g. cap+1 and cap+2), both correctly
see "over cap," and both roll back. The rollback step is not itself atomic with the
increment, but it doesn't need to be: the invariant that matters (never let more than
`cap` *successful* reservations stand) only depends on the increment being atomic,
which it is.

The natural key is `f"{org_id}:{mailbox_id}:{day}"` — Mongo enforces `_id`
uniqueness natively, so this needs no separate index-management infrastructure
(which doesn't exist yet in backend_v2 — same caveat as every other "no unique
index yet" note in this codebase).
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorCollection


class BudgetService:
    def __init__(self, collection: AsyncIOMotorCollection):
        self._collection = collection

    @staticmethod
    def key(*, org_id: str, mailbox_id: str, day: str) -> str:
        return f"{org_id}:{mailbox_id}:{day}"

    async def reserve(self, *, org_id: str, mailbox_id: str, day: str, cap: int) -> bool:
        """Atomically increments the counter and returns whether the reservation is
        within cap. Returns False (and rolls back the increment) if it isn't —
        the caller must not send."""
        _id = self.key(org_id=org_id, mailbox_id=mailbox_id, day=day)
        result = await self._collection.find_one_and_update(
            {"_id": _id},
            {"$setOnInsert": {"org_id": org_id, "mailbox_id": mailbox_id, "day": day}, "$inc": {"count": 1}},
            upsert=True,
            return_document=True,
        )
        if result["count"] > cap:
            await self._collection.update_one({"_id": _id}, {"$inc": {"count": -1}})
            return False
        return True

    async def release(self, *, org_id: str, mailbox_id: str, day: str) -> None:
        """Compensating rollback for a reservation that was granted but whose send
        then failed downstream (provider error) — a failed send must not
        permanently consume cap that a retry needs."""
        _id = self.key(org_id=org_id, mailbox_id=mailbox_id, day=day)
        await self._collection.update_one({"_id": _id}, {"$inc": {"count": -1}})
