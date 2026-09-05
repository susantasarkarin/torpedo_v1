"""
Message / SendLogEntry / Mailbox — the outreach domain's persisted shapes.

**`Mailbox` never stores a secret.** `credentials_id` is an opaque reference into a
secrets store this slice doesn't build (out of scope — the point proven here is the
*indirection*, not a secrets-manager implementation). This is the direct structural
fix for D-26: v1 stored `smtp_password`, `aws_access_key_id`/`aws_secret_access_key`,
and a full Gmail service-account JSON in plaintext Mongo documents, and one endpoint
even echoed an AWS secret key back to the caller in its response. There is no field
on this model a secret could be put in by mistake — `Mailbox.credentials_id` is the
one indirection v1 modeled correctly (`outreach_engine/models.py:181`) and never used.

**`Message.body` retention is explicitly still open (B-11)** — the register found
three contradictory positions on message-body retention across four v1 collections.
Kept here, not because the decision is made, but because building this slice without
somewhere to put drafted/sent content isn't meaningful — see README for how this is
tracked as still-open rather than silently decided by omission.
"""

from __future__ import annotations

from app.models.base import CanonicalDocument


class Mailbox(CanonicalDocument):
    email_address: str
    provider: str  # "gmail" | "smtp" | "ses" — see providers.py for the adapter boundary
    credentials_id: str  # opaque reference only — see module docstring
    daily_cap: int = 200
    is_active: bool = True


class Message(CanonicalDocument):
    to_email: str
    subject: str
    body: str  # retention: B-11, still open — see module docstring
    campaign_id: str | None = None
    transactional: bool = False


class SendLogEntry(CanonicalDocument):
    message_id: str | None = None  # None for statuses blocked before a Message existed
    mailbox_id: str
    to_email: str
    status: str  # "sent"|"suppressed"|"budget_blocked"|"kill_switch_active"|"compliance_blocked"|"failed"
    idempotency_key: str
    provider_message_id: str | None = None
    error: str | None = None
