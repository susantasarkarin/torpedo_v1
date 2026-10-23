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
