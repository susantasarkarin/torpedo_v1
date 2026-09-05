"""
SequenceService — atomic, per-org, per-document-type numbering. The D-35 fix.

The register: v1's `generate_payment_number` used `count(received) + count(made) + 1`
— **one shared counter fed by two collections** — so `RCV-`/`PAY-` sequences
interleaved and collided under concurrency. This service gives every document type
(`INV`, `BILL`, `RCV`, `PAY`, `CN`, ...) its own counter key, `f"{org_id}:{name}"`,
so incrementing one can never collide with or skip because of another.

Same exception-to-I-6 shape as `app.outreach.budget.BudgetService`, for the same
reason: `CanonicalRepository.update()`'s version-match semantics can't express "give
me the next value of a monotonic counter," and a single-document `$inc` is
MongoDB-atomic without needing a version check at all — there's nothing to race
against except itself, and `$inc` serializes.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorCollection


class SequenceService:
    def __init__(self, collection: AsyncIOMotorCollection):
        self._collection = collection

    async def next(self, *, org_id: str, sequence_name: str) -> int:
        _id = f"{org_id}:{sequence_name}"
        result = await self._collection.find_one_and_update(
            {"_id": _id}, {"$inc": {"value": 1}}, upsert=True, return_document=True,
        )
        return result["value"]
