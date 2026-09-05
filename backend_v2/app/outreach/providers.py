"""
SendProvider — the outbound-transport boundary, deliberately shaped like
`app.leadgen.ai.AIClassifier`: a `Protocol`, tested against fakes, no concrete SMTP/SES/
Gmail client lives in this package. Provider-specific behavior (OAuth refresh, SES
signing, SMTP retries) belongs in an adapter this slice doesn't build — the thing this
slice proves is that `MessagingFacade` calls exactly one abstraction here, never a
provider SDK directly, so a real adapter is a one-line swap, not a redesign.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SendFailed(Exception):
    """Raised by a provider on transport failure. Never silently swallowed —
    `MessagingFacade.send()` records the failure to the unified send log and
    re-raises, the same DLQ discipline as `app.leadgen.service.ingest()`."""


@dataclass(frozen=True)
class ProviderSendResult:
    provider_message_id: str


class SendProvider(Protocol):
    async def send(self, *, mailbox_credentials_id: str, to_email: str, subject: str, body: str) -> ProviderSendResult:
        """May raise SendFailed. Receives `credentials_id`, never a secret — the
        adapter is responsible for resolving it against whatever secrets store
        backs it in a real deployment (out of scope here, see Mailbox docstring)."""
        ...
