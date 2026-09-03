"""
Outreach must run on the leads in hand, whatever the AI is doing.

Lead generation (GSC) and AI segregation are continuous background processes.
Neither is allowed to be on the critical path of sending: when Bedrock went
down on 2026-09-01 the classifier stopped, and nothing about that should stop
outreach reaching leads that were already classified.

These pin the three properties that make that true.
"""

import os
from unittest.mock import patch

import pytest

from leads.canonical_ingestion import compute_icp_basket


# ---------------------------------------------------------------- one bucket
@pytest.mark.parametrize("lead,expected", [
    ({"company_industry": "market research", "department": "insights"}, "A"),
    ({"company_industry": "fmcg", "department": "brand"}, "B"),
    ({"company_industry": "architecture", "department": "bim"}, "C"),
])
def test_every_lead_gets_exactly_one_basket_without_any_model(lead, expected):
    """
    compute_icp_basket is pure rules — no network, no model, no Bedrock. It is
    what guarantees outreach has a full, segmented set of leads during an AI
    outage.
    """
    out = compute_icp_basket(lead)
    assert out["classification_basket"] == expected
    # One basket, not a list: a person belongs to one ICP and hears from one brand.
    assert isinstance(out["classification_basket"], str)


def test_an_unclassifiable_lead_goes_to_nurture_not_to_every_brand():
    """
    A lead we know nothing about must NOT tie across ICPs and fan out. Basket D
    ("Dual Fit") was 55% of the database for exactly that reason.
    """
    out = compute_icp_basket({"name": "Someone"})
    assert out["classification_basket"] == "E"


def test_basket_assignment_makes_no_model_call():
    """The strongest form of the guarantee: assert nothing reaches a provider."""
    with patch("leads.bedrock_client.converse_json_object",
               side_effect=AssertionError("basket assignment called a model")):
        assert compute_icp_basket(
            {"company_industry": "market research", "department": "insights"}
        )["classification_basket"] == "A"


# ------------------------------------------------------------- gmail only
def test_outreach_requires_a_google_mailbox_by_default(monkeypatch):
    from routers.cold_outreach_router import _require_gmail
    monkeypatch.delenv("OUTREACH_REQUIRE_GMAIL", raising=False)
    assert _require_gmail() is True


def test_gmail_requirement_can_be_relaxed_deliberately(monkeypatch):
    from routers.cold_outreach_router import _require_gmail
    monkeypatch.setenv("OUTREACH_REQUIRE_GMAIL", "false")
    assert _require_gmail() is False
    # Read at call time, so the policy changes without a deploy.
    monkeypatch.setenv("OUTREACH_REQUIRE_GMAIL", "true")
    assert _require_gmail() is True


# ---------------------------------------------------------------------------
# A misconfigured mailbox is a failure, not a delivery.
#
# _send_via_provider fell through to _mock_send(), which returns success=True
# with a fabricated "mock_..." id. The caller cannot tell that from a real
# send: it marks the lead sent, advances the step, and schedules the follow-up.
# The trigger is not an exotic provider name — it is provider="gmail" (the
# DEFAULT) with no gmail_service, which is how this engine is constructed
# unless a caller passes one.
# ---------------------------------------------------------------------------
def test_mock_sends_are_off_unless_explicitly_enabled(monkeypatch):
    from outreach_engine.sending_engine import _mock_sends_enabled
    monkeypatch.delenv("OUTREACH_ALLOW_MOCK_SENDS", raising=False)
    assert _mock_sends_enabled() is False
    monkeypatch.setenv("OUTREACH_ALLOW_MOCK_SENDS", "true")
    assert _mock_sends_enabled() is True


def test_gmail_without_a_service_fails_instead_of_faking_a_send(monkeypatch):
    from outreach_engine.sending_engine import SendingEngine
    monkeypatch.delenv("OUTREACH_ALLOW_MOCK_SENDS", raising=False)

    engine = SendingEngine.__new__(SendingEngine)   # no DB, no I/O
    engine.gmail_service = None

    record = type("R", (), {"to_email": "a@kantar.com", "message_id": "m1",
                            "thread_id": None})()
    ok, details = SendingEngine._send_via_provider(
        engine, {"provider": "gmail"}, record)

    assert ok is False
    assert "gmail_service" in details["error"]
    assert "mock" not in str(details).lower()
