"""
SesSendProvider — the second real SendProvider implementation, built after
confirming v1's real, working email credential is AWS SES (sesv2.send_email),
not SMTP. Same shape as test_outreach_smtp_provider.py: fails loud when
unconfigured, sends for real when configured (boto3 itself mocked — no
network in a unit test), never blocks the event loop doing it.
"""

import boto3
import pytest

from app.outreach.providers import SendFailed
from app.outreach.ses_provider import SendProviderUnavailable, SesSendProvider


@pytest.mark.asyncio
async def test_unconfigured_provider_fails_loud_never_fakes_success():
    provider = SesSendProvider(region=None, from_email=None, aws_access_key_id=None, aws_secret_access_key=None)
    with pytest.raises(SendProviderUnavailable):
        await provider.send(mailbox_credentials_id="cred-1", to_email="a@b.com", subject="hi", body="hi")


@pytest.mark.asyncio
async def test_partially_configured_provider_still_fails_loud():
    # region/from_email set, but no AWS credentials — must not attempt a send with half a credential.
    provider = SesSendProvider(region="us-east-1", from_email="sender@example.com", aws_access_key_id=None, aws_secret_access_key=None)
    with pytest.raises(SendProviderUnavailable):
        await provider.send(mailbox_credentials_id="cred-1", to_email="a@b.com", subject="hi", body="hi")


class _FakeSesClient:
    def __init__(self):
        self.calls: list[dict] = []

    def send_email(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "ses-message-id-123"}


@pytest.mark.asyncio
async def test_configured_provider_sends_through_real_boto3_call_shape(monkeypatch):
    fake = _FakeSesClient()
    monkeypatch.setattr(boto3, "client", lambda service, **kw: fake)

    provider = SesSendProvider(region="us-east-1", from_email="sender@example.com", aws_access_key_id="AKIAFAKE", aws_secret_access_key="fake-secret")
    result = await provider.send(mailbox_credentials_id="cred-1", to_email="lead@example.com", subject="Hi", body="<p>hi</p>")

    assert result.provider_message_id == "ses-message-id-123"
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["FromEmailAddress"] == "sender@example.com"
    assert call["Destination"] == {"ToAddresses": ["lead@example.com"]}
    assert call["Content"]["Simple"]["Subject"]["Data"] == "Hi"
    assert call["Content"]["Simple"]["Body"]["Html"]["Data"] == "<p>hi</p>"


@pytest.mark.asyncio
async def test_a_real_ses_error_raises_send_failed_not_swallowed(monkeypatch):
    class _RaisingSesClient:
        def send_email(self, **kwargs):
            raise RuntimeError("MessageRejected: Email address is not verified (sandbox mode)")

    monkeypatch.setattr(boto3, "client", lambda service, **kw: _RaisingSesClient())

    provider = SesSendProvider(region="us-east-1", from_email="sender@example.com", aws_access_key_id="AKIAFAKE", aws_secret_access_key="fake-secret")
    with pytest.raises(SendFailed):
        await provider.send(mailbox_credentials_id="cred-1", to_email="lead@example.com", subject="Hi", body="hi")


@pytest.mark.asyncio
async def test_send_provider_unavailable_is_a_send_failed_so_messaging_facade_handles_it_unchanged():
    assert issubclass(SendProviderUnavailable, SendFailed)


@pytest.mark.asyncio
async def test_client_is_built_lazily_not_at_construction(monkeypatch):
    """Same discipline as app.ai.gpu_broker's clients — never built at import
    or construction time, only on first real use."""
    build_calls = []

    def _fake_client(service, **kw):
        build_calls.append(service)
        return _FakeSesClient()

    monkeypatch.setattr(boto3, "client", _fake_client)
    provider = SesSendProvider(region="us-east-1", from_email="sender@example.com", aws_access_key_id="AKIAFAKE", aws_secret_access_key="fake-secret")
    assert build_calls == []  # not built yet

    await provider.send(mailbox_credentials_id="cred-1", to_email="lead@example.com", subject="Hi", body="hi")
    assert build_calls == ["sesv2"]
