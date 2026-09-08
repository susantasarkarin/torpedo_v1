"""
EmailIngestionProvider — the sixth instance of this codebase's external-boundary
`Protocol` pattern. Fetching real mail (IMAP/Gmail API polling) is the one part of
Slice 12 that's genuinely credential-blocked; everything downstream of "an email
already exists as an `InboundEmail` document" is real, tested, and does not depend
on this Protocol having a live implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class EmailProviderUnavailable(Exception):
    """Raised, never returned as an empty inbox — mirrors every other provider
    Protocol's failure mode in this codebase."""


@dataclass(frozen=True)
class RawInboundEmail:
    provider_message_id: str
    from_address: str
    to_address: str
    subject: str
    body: str
    thread_id: str | None = None


class EmailIngestionProvider(Protocol):
    async def fetch_new(self, *, mailbox_id: str, since_provider_message_id: str | None = None) -> list[RawInboundEmail]:
        """May raise EmailProviderUnavailable."""
        ...


class NullEmailIngestionProvider:
    """The production default until real IMAP/Gmail credentials exist — same
    pattern as `app.leadgen.routers.NullGSCProvider`. Raises rather than
    returning an empty inbox, so a caller can't mistake "not configured" for
    "no new mail today". This is what makes `email_ingestion_due` (Phase 14
    scheduler) safe to wire up *before* the credential exists: the trigger
    and its plumbing are real and tested now; swapping this for a real
    adapter later is a one-line change to `get_email_ingestion_provider()`,
    not a redesign."""

    async def fetch_new(self, *, mailbox_id: str, since_provider_message_id: str | None = None) -> list[RawInboundEmail]:
        raise EmailProviderUnavailable("no real email ingestion provider is configured — no IMAP/Gmail credentials exist in this environment")
