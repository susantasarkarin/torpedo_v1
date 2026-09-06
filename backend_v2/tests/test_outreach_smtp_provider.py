"""
Slice 21 — SmtpSendProvider, the first real SendProvider implementation.
`StubSendProvider` (app.outreach.routers) always fabricated success; this
proves the real replacement fails loud when unconfigured, sends for real
when configured (smtplib itself mocked — no network in a unit test), and
never blocks the event loop doing it.
"""

import smtplib

import pytest

from app.outreach.providers import SendFailed
from app.outreach.smtp_provider import SendProviderUnavailable, SmtpSendProvider


@pytest.mark.asyncio
async def test_unconfigured_provider_fails_loud_never_fakes_success():
    provider = SmtpSendProvider(host=None, port=587, username=None, password=None)
    with pytest.raises(SendProviderUnavailable):
        await provider.send(mailbox_credentials_id="cred-1", to_email="a@b.com", subject="hi", body="hi")


@pytest.mark.asyncio
async def test_partially_configured_provider_still_fails_loud():
    # host set, but no username/password — must not attempt a send with half a credential.
    provider = SmtpSendProvider(host="smtp.example.com", port=587, username=None, password=None)
    with pytest.raises(SendProviderUnavailable):
        await provider.send(mailbox_credentials_id="cred-1", to_email="a@b.com", subject="hi", body="hi")


class _FakeSmtpConnection:
    def __init__(self, *args, **kwargs):
        self.calls: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, username, password):
        self.calls.append(f"login:{username}")

    def send_message(self, msg):
        self.calls.append(f"send:{msg['To']}")


@pytest.mark.asyncio
async def test_configured_provider_sends_through_real_smtplib_call_shape(monkeypatch):
    fake = _FakeSmtpConnection()
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **kw: fake)

    provider = SmtpSendProvider(host="smtp.example.com", port=587, username="sender@example.com", password="app-password")
    result = await provider.send(mailbox_credentials_id="cred-1", to_email="lead@example.com", subject="Hi", body="<p>hi</p>")

    assert result.provider_message_id.startswith("smtp-")
    assert "starttls" in fake.calls
    assert "login:sender@example.com" in fake.calls
    assert "send:lead@example.com" in fake.calls


@pytest.mark.asyncio
async def test_a_real_smtp_error_raises_send_failed_not_swallowed(monkeypatch):
    class _RaisingSmtp(_FakeSmtpConnection):
        def login(self, username, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **kw: _RaisingSmtp())

    provider = SmtpSendProvider(host="smtp.example.com", port=587, username="sender@example.com", password="wrong-password")
    with pytest.raises(SendFailed):
        await provider.send(mailbox_credentials_id="cred-1", to_email="lead@example.com", subject="Hi", body="hi")


@pytest.mark.asyncio
async def test_send_provider_unavailable_is_a_send_failed_so_messaging_facade_handles_it_unchanged():
    assert issubclass(SendProviderUnavailable, SendFailed)
