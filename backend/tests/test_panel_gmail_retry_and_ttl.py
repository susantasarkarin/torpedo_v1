"""Panel Gmail send retry (transient only, never twice) and the panel_sessions TTL index."""
import socket
import ssl
from email.message import EmailMessage

import pytest

from services import panel_gmail_sender as g


class HttpErr(Exception):
    def __init__(self, status):
        super().__init__(f"HttpError {status}")
        self.resp = type("R", (), {"status": status})()


class FakeGmail:
    def __init__(self, sends, listing=None):
        self.sends, self.listing, self.send_calls, self.list_calls = list(sends), listing, 0, 0

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        self.send_calls += 1
        outcome = self.sends.pop(0)
        return type("E", (), {"execute": staticmethod(lambda: _do(outcome))})

    def list(self, **kw):
        self.list_calls += 1
        listing = self.listing
        return type("E", (), {"execute": staticmethod(lambda: _do(listing))})


def _do(o):
    if isinstance(o, Exception):
        raise o
    return o


@pytest.fixture
def gm(monkeypatch):
    sleeps = []
    monkeypatch.setattr(g, "_sleep", sleeps.append)

    def install(sends, listing=None):
        fake = FakeGmail(sends, listing)
        monkeypatch.setattr(g, "_gmail", lambda: fake)
        monkeypatch.setattr(g, "_reset_service", lambda: None)
        return fake
    install.sleeps = sleeps
    return install


def _msg():
    m = EmailMessage()
    m["To"], m["Subject"] = "a@example.com", "Hi"
    m.set_content("x")
    return m


def test_ssl_handshake_error_retried_then_logged_sent(gm):
    f = gm([ssl.SSLError("[SSL: WRONG_VERSION_NUMBER] wrong version number"), {"id": "m1"}])
    ok, info = g.send_message(_msg())
    assert ok and info["gmail_message_id"] == "m1" and f.send_calls == 2 and gm.sleeps == [2]


def test_5xx_and_429_retry_with_backoff_then_give_up(gm):
    f = gm([HttpErr(503), HttpErr(429), HttpErr(500)])
    ok, info = g.send_message(_msg())
    assert not ok and f.send_calls == 3 and gm.sleeps == [2, 5]


def test_4xx_never_retried(gm):
    f = gm([HttpErr(400)])
    ok, _ = g.send_message(_msg())
    assert not ok and f.send_calls == 1 and not gm.sleeps


def test_read_timeout_not_resent_when_gmail_already_has_it(gm):
    f = gm([socket.timeout("The read operation timed out")], listing={"messages": [{"id": "z"}]})
    ok, _ = g.send_message(_msg())
    assert ok and f.send_calls == 1 and f.list_calls == 1


def test_read_timeout_never_resent_even_when_not_found_in_sent(gm):
    # Gmail may rewrite our Message-ID, so "not in SENT" doesn't prove it wasn't
    # delivered: fail instead of risking a duplicate (owner decision 2026-11-22).
    f = gm([socket.timeout("timed out"), {"id": "m2"}], listing={})
    ok, _ = g.send_message(_msg())
    assert not ok and f.send_calls == 1 and f.list_calls == 1


def test_read_timeout_check_failure_means_no_retry(gm):
    f = gm([socket.timeout("timed out")], listing=HttpErr(500))
    ok, _ = g.send_message(_msg())
    assert not ok and f.send_calls == 1


def test_panel_sessions_ttl_in_index_registry():
    import indexes
    specs = indexes.INDEXES["campaign_platform"]["panel_sessions"]
    assert ("expires_at", {"expireAfterSeconds": 0}) in [(k, o) for k, o in specs] or \
        ("expires_at", {'expireAfterSeconds': 0}) in specs
