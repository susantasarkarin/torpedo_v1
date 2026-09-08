"""
SesSendProvider — a second real `SendProvider` implementation, alongside
`SmtpSendProvider` (Slice 21). Built after discovering v1's real, working
email credential is AWS SES (`sesv2.send_email`), not SMTP — the two are
structurally different transports (an authenticated API call vs. an SMTP
session), so `SmtpSendProvider` cannot simply accept SES credentials; this is
a separate adapter behind the same `SendProvider` Protocol, the exact "a real
adapter is a one-line swap, not a redesign" the Protocol's own docstring
promises.

**Config is explicit, not boto3's ambient credential chain** — same
discipline as every other credential in this codebase (`app.config.Settings`,
checked for presence before a send is attempted, never a bare `NoCredentialsError`
surfacing from deep inside botocore). v1's own `bedrock_client.py` relies on
boto3's implicit chain; this module doesn't, for consistency with
`SmtpSendProvider`'s explicit `host`/`username`/`password` shape.

**`get_send_provider()` prefers SES over SMTP when both are configured** —
SES is the real, verified-working credential (confirmed live against the
real AWS account before this module was written); SMTP remains a real,
independent fallback path, not deleted.

**Known operational limit, not a code gap**: the AWS SES account backing
this was confirmed live (2026-09-08) to be in **sandbox mode**
(`ProductionAccessEnabled=False`) — SES will only deliver to
pre-verified recipient addresses until AWS approves production access,
an AWS-console business action, not something this code can route around.
`send()` still succeeds or fails honestly either way; a sandbox rejection
surfaces as a real `SendFailed`, never faked as delivered.
"""

from __future__ import annotations

import asyncio

from app.outreach.providers import ProviderSendResult, SendFailed


class SendProviderUnavailable(SendFailed):
    """No SES configuration (`AWS_SES_REGION`/`SES_FROM_EMAIL`, and AWS
    credentials) present, confirmed, in this environment. A subclass of
    `SendFailed` on purpose — `MessagingFacade.send()`'s existing failure
    handling applies completely unchanged. Still, correctly, a failed send —
    never a silently fabricated success."""


class SesSendProvider:
    def __init__(
        self, *, region: str | None, from_email: str | None,
        aws_access_key_id: str | None = None, aws_secret_access_key: str | None = None,
    ):
        self._region = region
        self._from_email = from_email
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self._client = None  # lazy — never built at import time, same as app.ai.gpu_broker's clients

    def _get_client(self):
        if self._client is None:
            import boto3

            kwargs: dict = {"region_name": self._region}
            if self._aws_access_key_id and self._aws_secret_access_key:
                kwargs["aws_access_key_id"] = self._aws_access_key_id
                kwargs["aws_secret_access_key"] = self._aws_secret_access_key
            self._client = boto3.client("sesv2", **kwargs)
        return self._client

    async def send(self, *, mailbox_credentials_id: str, to_email: str, subject: str, body: str) -> ProviderSendResult:
        if not (self._region and self._from_email and self._aws_access_key_id and self._aws_secret_access_key):
            raise SendProviderUnavailable(
                "SES is not configured — AWS_SES_REGION/SES_FROM_EMAIL/AWS_ACCESS_KEY_ID/"
                "AWS_SECRET_ACCESS_KEY are not all present, refusing to fabricate a send"
            )
        try:
            return await asyncio.to_thread(self._send_sync, to_email, subject, body)
        except SendProviderUnavailable:
            raise
        except Exception as exc:
            raise SendFailed(f"SES send failed: {exc}") from exc

    def _send_sync(self, to_email: str, subject: str, body: str) -> ProviderSendResult:
        client = self._get_client()
        response = client.send_email(
            FromEmailAddress=self._from_email,
            Destination={"ToAddresses": [to_email]},
            Content={"Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": body, "Charset": "UTF-8"}},
            }},
        )
        return ProviderSendResult(provider_message_id=response["MessageId"])
