"""
SmtpSendProvider — the first real `SendProvider` implementation (Slice 21).
Every AI-decided send (`EmailAIService.decide_followup()`,
`OutreachAIService.decide_and_act()`) and every human-triggered
`POST /outreach/send` has gone through `StubSendProvider` since Slice 7 —
which always reports success against a fabricated `stub-{uuid}` message id,
even outside shadow mode. That was fine while proving out `MessagingFacade`'s
governance (kill switch/suppression/budget/footer/idempotency) end-to-end
without a real transport; it stopped being fine the moment shadow mode could
be turned off and a real send needed to actually happen. `get_survey_provider()`
got this exact upgrade in Slice 18 (`CintSurveyProvider`); this is the same
upgrade for email.

**Blocking I/O, on a worker thread, never the event loop.** stdlib `smtplib`
is synchronous; wrapping it in `asyncio.to_thread()` avoids adding a new async
SMTP dependency this codebase otherwise doesn't need (`requirements.txt` stays
at 8 packages), while still never blocking a FastAPI worker for the length of
a real SMTP round-trip — the identical class of bug found and fixed while
porting v1's `gpu_lease.py` in Slice 11 (blocking `requests`/`time.sleep()` in
an async context).

**Credentials are one globally configured relay, not yet a per-Mailbox
store.** The `SendProvider` Protocol's `mailbox_credentials_id` parameter is
accepted (the signature can't change without touching every caller) but not
yet resolved against anything — there is no per-mailbox secrets store
anywhere in this codebase, and building one for what is still a
single-org deployment would be exactly the over-engineering this rebuild's
discipline exists to avoid. `get_send_provider()` (`app.outreach.routers`) is
the one place this changes if/when a real multi-mailbox store is built.
"""

from __future__ import annotations

import asyncio
import smtplib
import uuid
from email.mime.text import MIMEText

from app.outreach.providers import ProviderSendResult, SendFailed


class SendProviderUnavailable(SendFailed):
    """No SMTP credentials configured (`SMTP_HOST`/`SMTP_USERNAME`/
    `SMTP_PASSWORD` all absent, confirmed, in this environment). A subclass of
    `SendFailed` on purpose — `MessagingFacade.send()`'s existing failure
    handling (release the budget reservation, record a `failed` SendLogEntry,
    re-raise as `OutreachError`) applies completely unchanged. This is still,
    correctly, a failed send — never a silently fabricated success."""


class SmtpSendProvider:
    def __init__(self, *, host: str | None, port: int, username: str | None, password: str | None, use_tls: bool = True):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls

    async def send(self, *, mailbox_credentials_id: str, to_email: str, subject: str, body: str) -> ProviderSendResult:
        if not (self._host and self._username and self._password):
            raise SendProviderUnavailable("SMTP is not configured — SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD are absent, refusing to fabricate a send")
        try:
            return await asyncio.to_thread(self._send_sync, to_email, subject, body)
        except SendProviderUnavailable:
            raise
        except Exception as exc:
            raise SendFailed(f"SMTP send failed: {exc}") from exc

    def _send_sync(self, to_email: str, subject: str, body: str) -> ProviderSendResult:
        message_id = f"smtp-{uuid.uuid4()}"
        msg = MIMEText(body, "html")
        msg["From"] = self._username
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Message-Id"] = f"<{message_id}@torpedo>"

        with smtplib.SMTP(self._host, self._port, timeout=30) as server:
            if self._use_tls:
                server.starttls()
            server.login(self._username, self._password)
            server.send_message(msg)
        return ProviderSendResult(provider_message_id=message_id)
