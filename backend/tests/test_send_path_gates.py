"""
Every sender that can mail a lead or panelist must go through messaging.facade.gate().

Before 2026-10-24 these paths skipped it: sales_outreach's Gmail send, nurture
auto-send, panel drips, and the legacy SMTP campaign senders. A paused outreach
kill switch therefore did not stop them. Each test makes gate() refuse and
checks the transport is never touched. Fully mocked: no Mongo, no Gmail, no SMTP.
"""
from unittest.mock import MagicMock, patch

import pytest

from messaging import facade

BLOCK = ("outreach kill switch paused (torpedo.outreach_kill_switch)", "disabled")


def test_sales_outreach_gmail_send_is_gated():
    from sales import outreach_pipeline
    service = MagicMock()
    with patch.object(facade, "gate", return_value=BLOCK) as g:
        with pytest.raises(facade.SendBlocked) as exc:
            outreach_pipeline._send_via_gmail(service, "lead@kantar.com", "hello", "body")
    assert exc.value.category == "disabled"
    assert g.call_args.kwargs["channel"] == "sales_outreach"
    service.users.assert_not_called()


def test_panel_drip_is_gated():
    from services import panel_drip_service
    stage = next(iter(panel_drip_service.STAGES))
    with patch("services.panel_email_service._panel_gate", return_value=BLOCK), \
         patch("services.panel_gmail_sender.send_message") as send:
        ok, details = panel_drip_service._send_one_drip(stage, "member@gmail.com", "Asha")
    assert ok is False and details["error"] == "disabled"
    send.assert_not_called()


def test_legacy_email_campaigns_smtp_is_gated(monkeypatch):
    from routers import email_campaigns
    monkeypatch.setenv("SMTP_HOST", "smtp.example.net")
    monkeypatch.setenv("SMTP_USER", "u@cogentixresearch.com")
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    with patch.object(facade, "gate", return_value=BLOCK), \
         patch("smtplib.SMTP") as smtp:
        assert email_campaigns.send_email("lead@kantar.com", "s", "<p>b</p>") is False
    smtp.assert_not_called()


def test_campaign_service_smtp_is_gated():
    from services import campaign_service
    with patch.object(facade, "gate", return_value=BLOCK), \
         patch("smtplib.SMTP") as smtp:
        with pytest.raises(facade.SendBlocked):
            campaign_service.send_email_html_sync("lead@kantar.com", "s", "<p>b</p>")
    smtp.assert_not_called()


def test_nurture_auto_send_is_gated(monkeypatch):
    from sales import nurture
    monkeypatch.setattr(nurture, "_auto_send", lambda: True)
    svc = MagicMock()
    svc.get_signature.return_value = ""
    with patch.object(facade, "gate", return_value=BLOCK), \
         patch("app.services.gmail_workspace_service.GmailWorkspaceService", return_value=svc):
        out = nurture._deliver({"email": "lead@kantar.com"},
                               {"subject": "s", "body": "b"},
                               {"email": "in@surveyfieldwork.com", "thread_id": None})
    assert out["mode"] == "blocked" and out["success"] is False
    svc.send_email.assert_not_called()


# ------------------------------------------- non-lead mail: transactional rules
def _supp(reason):
    return patch.multiple(facade._suppression, is_suppressed=MagicMock(return_value=True),
                          reason_for=MagicMock(return_value=reason))


@pytest.fixture
def _no_side_effects(monkeypatch):
    monkeypatch.setenv("SENDING_ENABLED", "true")
    monkeypatch.setattr(facade, "outreach_paused", lambda: True)   # must not matter for these channels
    monkeypatch.setattr(facade, "_audit_block", lambda **kw: None)
    monkeypatch.setattr(facade, "_preview", lambda **kw: None)


@pytest.mark.parametrize("reason,blocked", [("unsubscribed", False), ("bounced", True),
                                            ("complaint", True), ("manual", True), ("unknown", True)])
def test_finance_passes_outreach_unsubscribe_only(_no_side_effects, reason, blocked):
    with _supp(reason):
        out = facade.gate_recipients(["ap@hansaresearch.com"], identity="accounts@surveyfieldwork.com",
                                     channel="finance", allow_suppressed_reasons=facade.FINANCE_ALLOWED)
    assert (out is not None) is blocked


@pytest.mark.parametrize("reason,blocked", [("unsubscribed", False), ("bounced", False),
                                            ("complaint", True), ("manual", True)])
def test_manual_compose_blocks_only_complaint_and_do_not_contact(_no_side_effects, reason, blocked):
    with _supp(reason):
        why = facade.manual_compose_block("in@surveyfieldwork.com", ["x@kantar.com"], None, None, "hi")
    assert (why is not None) is blocked


def test_manual_compose_checks_cc_and_bcc(_no_side_effects):
    def is_supp(addr):
        return addr == "dnc@kantar.com"
    with patch.object(facade._suppression, "is_suppressed", side_effect=is_supp), \
         patch.object(facade._suppression, "reason_for", return_value="manual"):
        why = facade.manual_compose_block("in@surveyfieldwork.com", "ok@kantar.com", [], "dnc@kantar.com", "s")
    assert why and "dnc@kantar.com" in why


def test_finance_send_is_gated_before_gmail(_no_side_effects):
    from app.services import finance_automation
    with _supp("complaint"), patch("app.services.gmail_workspace_service.GmailWorkspaceService") as svc:
        out = finance_automation._send(["ap@hansaresearch.com"], "Statement", "<p>x</p>", "x")
    assert out["success"] is False and out["blocked"] is True
    svc.assert_not_called()


def test_panel_account_mail_is_gated_before_gmail(_no_side_effects):
    from services import panel_transactional_email as pte
    with _supp("complaint"), patch("services.panel_gmail_sender.send_message") as send:
        ok, details = pte._send("member@gmail.com", "Reset your password", "<p>x</p>", "x", "reset")
    assert ok is False and details["error"] == "suppressed"
    send.assert_not_called()


def test_panel_account_mail_ignores_marketing_unsubscribe(_no_side_effects):
    from services import panel_transactional_email as pte
    with _supp("unsubscribed"), patch("services.panel_gmail_sender.send_message",
                                      return_value=(True, {"gmail_message_id": "g1"})) as send:
        ok, _ = pte._send("member@gmail.com", "Reset your password", "<p>x</p>", "x", "reset")
    assert ok is True
    send.assert_called_once()
