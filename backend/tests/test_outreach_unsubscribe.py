"""
Cold-outreach opt-out: token round-trip, and the refusal that keeps a
non-compliant message from ever leaving.

The bug worth pinning: messaging.facade's compliance gate only proves the two
env vars are SET. It cannot tell whether the message actually carries a postal
address and an opt-out link — and for the whole life of the v2 send path, it
did not. So the tests that matter here are the ones asserting the footer is
either present or the send is refused, never neither.
"""

import importlib

import pytest


@pytest.fixture
def unsub(monkeypatch):
    monkeypatch.setenv("OUTREACH_UNSUBSCRIBE_SECRET", "test-secret")
    monkeypatch.setenv("TRACKING_BASE_URL", "https://mail.example.com")
    monkeypatch.setenv("OUTREACH_SENDER_POSTAL_ADDRESS",
                       "Torpedo Research, 1 Example Rd, Kolkata 700001, India")
    import services.outreach_unsubscribe as mod
    return importlib.reload(mod)


def test_token_round_trips(unsub):
    assert unsub.read_token(unsub.make_token("Person@Example.COM")) == "person@example.com"


def test_tampered_signature_still_honours_the_optout(unsub):
    """Fail-open: refusing a real opt-out is a compliance failure; wrongly
    honouring a forged one costs a single address."""
    token = unsub.make_token("person@example.com")
    payload, _, _sig = token.partition(".")
    assert unsub.read_token(f"{payload}.deadbeef" + "0" * 24) == "person@example.com"


def test_garbage_token_resolves_to_nothing(unsub):
    assert unsub.read_token("!!!not-base64!!!") is None
    assert unsub.read_token("") is None


def test_footer_carries_the_address_and_a_working_link(unsub):
    footer = unsub.compliance_footer("person@example.com", "Survey Fieldwork")
    assert "1 Example Rd" in footer
    assert "https://mail.example.com/api/cold-outreach/unsubscribe/" in footer
    assert "Survey Fieldwork" in footer
    assert unsub.footer_blocker() is None


def test_no_postal_address_means_no_footer_and_a_named_blocker(monkeypatch):
    monkeypatch.setenv("TRACKING_BASE_URL", "https://mail.example.com")
    monkeypatch.delenv("OUTREACH_SENDER_POSTAL_ADDRESS", raising=False)
    import services.outreach_unsubscribe as mod
    mod = importlib.reload(mod)

    assert mod.compliance_footer("person@example.com") == ""
    assert "OUTREACH_SENDER_POSTAL_ADDRESS" in mod.footer_blocker()


def test_no_base_url_means_no_footer(monkeypatch):
    monkeypatch.setenv("OUTREACH_SENDER_POSTAL_ADDRESS", "1 Example Rd")
    monkeypatch.delenv("OUTREACH_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("TRACKING_BASE_URL", raising=False)
    import services.outreach_unsubscribe as mod
    mod = importlib.reload(mod)

    assert mod.compliance_footer("person@example.com") == ""
    assert "unsubscribe link" in mod.footer_blocker()


def test_footer_escapes_a_hostile_business_label(unsub):
    footer = unsub.compliance_footer("person@example.com", '<script>alert(1)</script>')
    assert "<script>" not in footer
    assert "&lt;script&gt;" in footer
