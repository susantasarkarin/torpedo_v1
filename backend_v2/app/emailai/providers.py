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
