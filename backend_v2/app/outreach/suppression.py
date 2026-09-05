"""
The canonical Suppression check (data_lineage_map.md §3.1 shape) — an append-only
`events[]` list, never an overwritten `reason` field. The direct structural fix for
D-27 (v1's `$set`-overwritten suppression reason destroyed the legal record of an
opt-out) and, more broadly, for the register's three-competing-suppression-stores
finding (§5.2): there is exactly one `Suppression` model and one `SuppressionService`
in this codebase, and every consumer — `app.leadgen`'s contactability gate, this
package's own `MessagingFacade` — depends on this same instance, never a
domain-local copy.

**Relocated here from `app/leadgen/suppression.py` during Slice 7** (Outreach):
Slice 6 built this to make lead enrollment's contactability gate real rather than a
stub, correctly minimal for what that one caller needed. Slice 7 needed the same
check for the send facade — building a second one there would have been exactly the
I-1 violation this whole codebase exists to prevent, so this module moved to its
correct canonical home instead. `app/leadgen/service.py` now imports from here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.base import CanonicalDocument, CanonicalRepository


class Suppression(CanonicalDocument):
    email: str  # normalized: lowercased, trimmed
    events: list[dict] = []  # [{reason, source, actor, occurred_at}] — append-only, see module docstring


class SuppressionService:
    def __init__(self, suppressions: CanonicalRepository[Suppression]):
        self._suppressions = suppressions

    async def is_suppressed(self, email: str) -> bool:
        record = await self._suppressions.find_one({"email": email.strip().lower()})
        return record is not None and len(record.events) > 0

    async def suppress(self, *, org_id: str, actor: str, email: str, reason: str, source: str) -> Suppression:
        normalized = email.strip().lower()
        existing = await self._suppressions.find_one({"email": normalized})
        event = {"reason": reason, "source": source, "actor": actor, "occurred_at": datetime.now(timezone.utc).isoformat()}
        if existing:
            return await self._suppressions.update(
                existing.id, existing.version, {"events": [*existing.events, event]}, updated_by=actor
            )
        record = Suppression(org_id=org_id, created_by=actor, updated_by=actor, email=normalized, events=[event])
        return await self._suppressions.insert(record)
