"""
KillSwitch — the D-28 fix.

v1's global outreach kill switch was read at `cold_outreach_router.py:2418-2421` and
**failed safe to paused when the document was missing** — but no code anywhere wrote
that document. The register's own note: this may explain the standing outreach pause
(memory: outreach has been off since 2026-08-25 with no scheduler to resume it). The
fail-safe-to-paused default was the *correct* half of v1's design — it matches this
codebase's existing "no verifiable channel = fail closed" philosophy
(`app.leadgen.service.check_contactability`). The defect was never the default; it was
that an operator had no way to ever change it in either direction. This module's whole
job is to be that missing writer: `pause()`/`resume()` exist and this is the only place
that constructs a `KillSwitch` document.

The P1 list adds two more requirements this module (together with `MessagingFacade`)
must satisfy: "test-send bypasses kill switch" and "panel drips not kill-switch gated"
(register §5.1) — i.e. no send path, and no caller-supplied flag, may skip this check.
`MessagingFacade.send()` calls `is_paused()` unconditionally, with no parameter that
turns it off.
"""

from __future__ import annotations

from app.models.base import CanonicalDocument, CanonicalRepository


class KillSwitch(CanonicalDocument):
    scope: str = "org"  # the only scope this slice implements — one switch per org
    paused: bool = True
    reason: str | None = None


class KillSwitchService:
    def __init__(self, kill_switches: CanonicalRepository[KillSwitch]):
        self._repo = kill_switches

    async def is_paused(self, org_id: str) -> bool:
        """No document for this org == fail safe to paused. This is a deliberate
        default, not a placeholder — see module docstring."""
        doc = await self._repo.find_one({"org_id": org_id, "scope": "org"})
        return doc.paused if doc else True

    async def pause(self, *, org_id: str, actor: str, reason: str) -> KillSwitch:
        existing = await self._repo.find_one({"org_id": org_id, "scope": "org"})
        if existing:
            return await self._repo.update(existing.id, existing.version, {"paused": True, "reason": reason}, updated_by=actor)
        return await self._repo.insert(
            KillSwitch(org_id=org_id, created_by=actor, updated_by=actor, paused=True, reason=reason)
        )

    async def resume(self, *, org_id: str, actor: str) -> KillSwitch:
        existing = await self._repo.find_one({"org_id": org_id, "scope": "org"})
        if existing:
            return await self._repo.update(existing.id, existing.version, {"paused": False, "reason": None}, updated_by=actor)
        return await self._repo.insert(
            KillSwitch(org_id=org_id, created_by=actor, updated_by=actor, paused=False, reason=None)
        )
