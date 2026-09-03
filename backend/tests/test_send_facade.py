"""
Tests for the unified send facade (TOR-06).

These pin the guarantees that the thirteen scattered send paths did not have:
suppression is checked before budget, both are checked before the transport,
the kill switch works, and a check that cannot run fails CLOSED.

Fully mocked — no Mongo, no SES, no network.
"""

from unittest.mock import MagicMock, patch

import pytest

from messaging import facade
from messaging.budget import BudgetExceeded


@pytest.fixture(autouse=True)
def _compliance_env(monkeypatch):
    """Bulk sends refuse without these; set them so tests exercise other paths."""
    monkeypatch.setenv("OUTREACH_SENDER_POSTAL_ADDRESS", "1 Test St, Kolkata")
    monkeypatch.setenv("OUTREACH_UNSUBSCRIBE_URL", "https://example.com/u")
    monkeypatch.setenv("SENDING_ENABLED", "true")


@pytest.fixture
def transport():
    return MagicMock(return_value="provider-msg-1")


def _send(transport, **over):
    kwargs = dict(
        to_email="Person@Kantar.COM",   # a real corporate domain: example.com is now blocklisted
        subject="hello",
        body_text="hi",
        transport=transport,
        identity="outreach@cogentixresearch.com",
        channel="outreach",
    )
    kwargs.update(over)
    return facade.send(**kwargs)


# ---------------------------------------------------------------- happy path
def test_clear_address_is_delivered_and_logged(transport):
    with patch.object(facade._suppression, "is_suppressed", return_value=False), \
         patch.object(facade._budget, "allows", return_value=None), \
         patch.object(facade._log, "record", return_value="log-1") as rec:
        result = _send(transport)

    assert result.delivered is True
    assert bool(result) is True
    assert result.provider_message_id == "provider-msg-1"
    transport.assert_called_once()
    assert rec.call_args.kwargs["status"] == "sent"
    # Address is normalised before it reaches the log or the provider.
    assert rec.call_args.kwargs["to_email"] == "person@kantar.com"


# -------------------------------------------------------------- suppression
def test_suppressed_address_never_reaches_the_transport(transport):
    with patch.object(facade._suppression, "is_suppressed", return_value=True), \
         patch.object(facade._suppression, "reason_for", return_value="complaint"), \
         patch.object(facade._budget, "allows") as allows, \
         patch.object(facade._log, "record", return_value="log-1") as rec:
        result = _send(transport)

    assert result.delivered is False
    assert result.category == "suppressed"
    assert "complaint" in result.reason
    transport.assert_not_called()
    # Suppression is checked BEFORE budget so a suppressed address cannot burn
    # quota — that ordering is the point, not an accident.
    allows.assert_not_called()
    assert rec.call_args.kwargs["status"] == "suppressed"


def test_suppression_failure_fails_closed(transport):
    """An unanswerable suppression check must block, not send."""
    with patch.object(facade._suppression, "lookup", side_effect=RuntimeError("mongo down")), \
         patch.object(facade._budget, "allows", return_value=None), \
         patch.object(facade._log, "record", return_value="log-1"):
        result = _send(transport)

    assert result.delivered is False
    assert result.category == "suppressed"
    transport.assert_not_called()


def test_skip_suppression_is_honoured_for_unskippable_mail(transport):
    with patch.object(facade._suppression, "is_suppressed", return_value=True) as sup, \
         patch.object(facade._budget, "allows", return_value=None), \
         patch.object(facade._log, "record", return_value="log-1"):
        result = _send(transport, skip_suppression=True, transactional=True)

    assert result.delivered is True
    sup.assert_not_called()


# ------------------------------------------------------------------- budget
def test_budget_block_stops_the_send(transport):
    with patch.object(facade._suppression, "is_suppressed", return_value=False), \
         patch.object(facade._budget, "allows", return_value="daily cap reached"), \
         patch.object(facade._log, "record", return_value="log-1") as rec:
        result = _send(transport)

    assert result.delivered is False
    assert result.category == "budget"
    transport.assert_not_called()
    assert rec.call_args.kwargs["status"] == "budget_blocked"


def test_transactional_mail_is_passed_through_to_the_budget(transport):
    with patch.object(facade._suppression, "is_suppressed", return_value=False), \
         patch.object(facade._budget, "allows", return_value=None) as allows, \
         patch.object(facade._log, "record", return_value="log-1"):
        _send(transport, transactional=True)

    # The reserve only means anything if the flag actually reaches the budget.
    assert allows.call_args.kwargs["transactional"] is True


# -------------------------------------------------------------- kill switch
def test_kill_switch_stops_everything(transport, monkeypatch):
    monkeypatch.setenv("SENDING_ENABLED", "false")
    with patch.object(facade._log, "record", return_value="log-1"):
        result = _send(transport)

    assert result.delivered is False
    assert result.category == "disabled"
    transport.assert_not_called()


def test_kill_switch_is_read_at_call_time(transport, monkeypatch):
    """It has to work without a restart, so it must not be captured at import."""
    monkeypatch.setenv("SENDING_ENABLED", "false")
    assert facade.sending_enabled() is False
    monkeypatch.setenv("SENDING_ENABLED", "true")
    assert facade.sending_enabled() is True


# -------------------------------------------------------------- compliance
@pytest.mark.parametrize("missing", ["OUTREACH_SENDER_POSTAL_ADDRESS",
                                     "OUTREACH_UNSUBSCRIBE_URL"])
def test_bulk_send_refuses_without_compliance_fields(transport, monkeypatch, missing):
    monkeypatch.delenv(missing, raising=False)
    with patch.object(facade._log, "record", return_value="log-1"):
        result = _send(transport)

    assert result.delivered is False
    assert result.category == "compliance"
    transport.assert_not_called()


def test_transactional_mail_is_exempt_from_compliance_fields(transport, monkeypatch):
    """A password reset needs no unsubscribe link."""
    monkeypatch.delenv("OUTREACH_SENDER_POSTAL_ADDRESS", raising=False)
    monkeypatch.delenv("OUTREACH_UNSUBSCRIBE_URL", raising=False)
    with patch.object(facade._suppression, "is_suppressed", return_value=False), \
         patch.object(facade._budget, "allows", return_value=None), \
         patch.object(facade._log, "record", return_value="log-1"):
        result = _send(transport, transactional=True)

    assert result.delivered is True


def test_invalid_address_is_rejected(transport):
    with patch.object(facade._log, "record", return_value="log-1"):
        result = _send(transport, to_email="not-an-address")
    assert result.delivered is False
    assert result.category == "compliance"
    transport.assert_not_called()


# -------------------------------------------------------------- transport
def test_transport_failure_is_returned_not_raised(transport):
    """A caller looping over recipients must not abort the batch on one bad send."""
    transport.side_effect = RuntimeError("SES throttled")
    with patch.object(facade._suppression, "is_suppressed", return_value=False), \
         patch.object(facade._budget, "allows", return_value=None), \
         patch.object(facade._log, "record", return_value="log-1") as rec:
        result = _send(transport)

    assert result.delivered is False
    assert result.category == "transport"
    assert "SES throttled" in result.reason
    assert rec.call_args.kwargs["status"] == "failed"


def test_prebuilt_message_is_passed_through_untouched(transport):
    """Callers with List-Unsubscribe headers keep their own message."""
    from email.mime.multipart import MIMEMultipart
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "custom"
    msg["List-Unsubscribe"] = "<https://example.com/u>"

    with patch.object(facade._suppression, "is_suppressed", return_value=False), \
         patch.object(facade._budget, "allows", return_value=None), \
         patch.object(facade._log, "record", return_value="log-1"):
        _send(transport, message=msg)

    assert transport.call_args.args[0] is msg


# ------------------------------------------------------------------ budget unit
def test_budget_counts_only_successful_sends():
    """Suppressed and blocked attempts are logged but must not consume quota."""
    from messaging import log as log_mod
    col = MagicMock()
    col.count_documents.return_value = 7
    with patch.object(log_mod, "_col", return_value=col):
        assert log_mod.count_sends("id@example.com") == 7
    assert col.count_documents.call_args.args[0]["status"] == "sent"


def test_send_log_count_failure_reports_budget_exhausted():
    """An uncountable log is an unknown quota; block rather than send blind."""
    from messaging import log as log_mod
    col = MagicMock()
    col.count_documents.side_effect = RuntimeError("mongo down")
    with patch.object(log_mod, "_col", return_value=col):
        assert log_mod.count_sends("id@example.com") > 10 ** 8


def test_budget_reserve_is_withheld_from_bulk(monkeypatch):
    from messaging import budget as budget_mod
    monkeypatch.setattr(budget_mod, "DEFAULT_DAILY", 100)
    monkeypatch.setattr(budget_mod, "DEFAULT_HOURLY", 100)
    monkeypatch.setattr(budget_mod, "TRANSACTIONAL_RESERVE", 20)
    monkeypatch.delenv("SEND_BUDGET_ID_EXAMPLE_COM_DAILY", raising=False)

    with patch.object(budget_mod, "usage", wraps=budget_mod.usage):
        with patch("messaging.log.count_sends", return_value=85):
            # 85 sent, 100 daily: transactional may proceed, bulk may not.
            assert budget_mod.allows("id@example.com", transactional=True) is None
            assert budget_mod.allows("id@example.com", transactional=False) is not None


# ---------------------------------------------------------------------------
# Regression: panelist login returned 500 for the 223,951 panelists who have
# no password_hash at all (registration happens on the SFW panel). An absent
# credential is a failed check, not a "security violation".
# ---------------------------------------------------------------------------
def test_missing_password_hash_fails_verification_without_raising():
    from auth import verify_password
    assert verify_password("anything", "") is False
    assert verify_password("anything", None or "") is False


def test_genuinely_plaintext_hash_still_raises():
    """The security check must survive the fix above — a real plaintext value
    stored where a hash belongs is still refused loudly."""
    from auth import verify_password
    with pytest.raises(ValueError):
        verify_password("anything", "hunter2")


# ---------------------------------------------------------------------------
# Placeholder / social domains. The recorded bounces contain 119 sends to
# @domain.com and 26 to @company.com — the pattern template's own placeholder
# text — plus 76 to @linkedin.com. All were generated by us and could never
# have been delivered.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("addr", [
    "first.last@domain.com",      # unsubstituted template placeholder
    "first.last@company.com",     # ditto
    "someone@linkedin.com",       # domain taken from the profile URL
    "guessed.name@gmail.com",     # a guess here reaches a stranger, not a bounce
])
def test_unsendable_domains_are_refused(transport, addr):
    with patch.object(facade._log, "record", return_value="log-1"):
        result = _send(transport, to_email=addr)
    assert result.delivered is False
    assert result.category == "compliance"
    transport.assert_not_called()


def test_real_corporate_domain_still_sends(transport):
    with patch.object(facade._suppression, "is_suppressed", return_value=False), \
         patch.object(facade._budget, "allows", return_value=None), \
         patch.object(facade._log, "record", return_value="log-1"):
        assert _send(transport, to_email="first.last@kantar.com").delivered is True


# ---------------------------------------------------------------------------
# facade.gate() — the shared pre-send checks, for senders that deliver their
# own mail. The v2 cold-outreach engine does its own SMTP/SES and so had none
# of these: no kill switch, no cross-channel budget, no unified suppression,
# no placeholder-domain blocklist. It is the path that over-sent in August.
# ---------------------------------------------------------------------------
def _gate(addr="person@kantar.com", **over):
    kwargs = dict(identity="outreach@cogentixresearch.com", channel="outreach")
    kwargs.update(over)
    return facade.gate(addr, **kwargs)


def test_gate_allows_a_clean_address():
    with patch.object(facade._suppression, "is_suppressed", return_value=False), \
         patch.object(facade._budget, "allows", return_value=None):
        assert _gate() is None


def test_gate_honours_the_kill_switch(monkeypatch):
    monkeypatch.setenv("SENDING_ENABLED", "false")
    reason, category = _gate()
    assert category == "disabled"


def test_gate_blocks_suppressed_addresses():
    with patch.object(facade._suppression, "is_suppressed", return_value=True), \
         patch.object(facade._suppression, "reason_for", return_value="complaint"), \
         patch.object(facade._budget, "allows") as allows:
        reason, category = _gate()
    assert category == "suppressed"
    # Suppression before budget, so a suppressed address cannot burn quota.
    allows.assert_not_called()


def test_gate_blocks_on_budget():
    with patch.object(facade._suppression, "is_suppressed", return_value=False), \
         patch.object(facade._budget, "allows", return_value="daily cap reached"):
        reason, category = _gate()
    assert category == "budget"


@pytest.mark.parametrize("addr", ["first.last@domain.com", "someone@linkedin.com"])
def test_gate_blocks_unsendable_domains(addr):
    reason, category = _gate(addr)
    assert category == "compliance"


def test_gate_and_send_apply_the_same_rules(transport):
    """The split must not let the two paths drift apart."""
    with patch.object(facade._suppression, "is_suppressed", return_value=True), \
         patch.object(facade._suppression, "reason_for", return_value="complaint"), \
         patch.object(facade._budget, "allows", return_value=None), \
         patch.object(facade._log, "record", return_value="log-1"):
        sent = _send(transport)
        gated = _gate()
    assert sent.category == gated[1] == "suppressed"
