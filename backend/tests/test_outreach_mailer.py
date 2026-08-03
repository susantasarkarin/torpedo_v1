"""
OUTREACH MAILER TESTS
=====================

Focus: email validation (placeholders, length, CTA, name, unsupportable
claims), the send pre-flight blockers, CAN-SPAM footer construction, and
multipart assembly.

Nothing here sends mail or calls a model.

Run with: pytest backend/tests/test_outreach_mailer.py -v
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import outreach_mailer as om
from leads.outreach_mailer import (
    MAX_BODY_WORDS,
    MAX_SUBJECT_CHARS,
    MIN_BODY_WORDS,
    build_footer,
    build_message,
    preflight,
    validate_email,
)
from leads.outreach_config import PITCH_PLACEHOLDER


LEAD = {
    "_id": "lead1",
    "email": "asha.rao@larsentoubro.com",
    "first_name": "Asha",
    "last_name": "Rao",
    "title": "Head of BIM",
    "company": "Larsen & Toubro",
    "outreach_bucket": "BIM",
}


def _body(words: int = 100, name: str = "Asha", cta: bool = True) -> str:
    text = f"Hi {name}, " + "word " * (words - 8)
    if cta:
        text += "Open to a 15-min call next week?"
    else:
        text += "Let me know your thoughts on this."
    return text


# ============================================
# VALIDATION: BASELINE
# ============================================

def test_valid_email_has_no_problems():
    assert validate_email("Quick question on BIM delivery", _body(), LEAD) == []


# ============================================
# VALIDATION: PLACEHOLDERS
# ============================================

@pytest.mark.parametrize("junk", [
    "[TODO: pitch]", "[Company]", "[insert value prop]",
    "{{first_name}}", "TODO", "TBD", "XXX", "<insert pitch>",
    "Lorem ipsum dolor", "your company",
])
def test_placeholder_text_rejected(junk):
    body = _body(95) + " " + junk
    problems = validate_email("Subject", body, LEAD)
    assert any("placeholder" in p for p in problems), f"{junk!r} not caught: {problems}"


def test_pitch_placeholder_sentinel_is_caught():
    body = _body(95) + " " + PITCH_PLACEHOLDER
    problems = validate_email("Subject", body, LEAD)
    assert any("placeholder" in p for p in problems)


def test_placeholder_in_subject_rejected():
    problems = validate_email("Question for [Company]", _body(), LEAD)
    assert any("placeholder" in p for p in problems)


# ============================================
# VALIDATION: LENGTH
# ============================================

def test_subject_over_limit_rejected():
    problems = validate_email("x" * (MAX_SUBJECT_CHARS + 1), _body(), LEAD)
    assert any("subject too long" in p for p in problems)


def test_subject_at_limit_accepted():
    subject = ("BIM delivery question for Larsen and Toubro teams ab"
               .ljust(MAX_SUBJECT_CHARS, "z"))[:MAX_SUBJECT_CHARS]
    assert len(subject) == MAX_SUBJECT_CHARS
    assert validate_email(subject, _body(), LEAD) == []


def test_lowercase_x_runs_are_not_placeholders():
    """'XXX' is an uppercase placeholder convention; prose must not trip it."""
    assert validate_email("xxxxx test subject", _body(), LEAD) == []
    assert any("placeholder" in p
               for p in validate_email("XXX subject", _body(), LEAD))


def test_empty_subject_rejected():
    assert any("empty subject" in p for p in validate_email("", _body(), LEAD))


def test_body_too_short_rejected():
    problems = validate_email("Subject", _body(MIN_BODY_WORDS - 20), LEAD)
    assert any("body too short" in p for p in problems)


def test_body_too_long_rejected():
    problems = validate_email("Subject", _body(MAX_BODY_WORDS + 30), LEAD)
    assert any("body too long" in p for p in problems)


def test_empty_body_rejected():
    assert any("empty body" in p for p in validate_email("Subject", "", LEAD))


# ============================================
# VALIDATION: CTA AND NAME
# ============================================

def test_missing_cta_rejected():
    problems = validate_email("Subject", _body(cta=False), LEAD)
    assert any("CTA" in p for p in problems)


@pytest.mark.parametrize("cta", [
    "Open to a 15-min call?", "Worth a 15 minute call?",
    "Fancy a quick call next week?", "Up for a brief call?",
])
def test_accepted_cta_phrasings(cta):
    body = "Hi Asha, " + "word " * 92 + cta
    assert validate_email("Subject", body, LEAD) == []


def test_wrong_recipient_name_rejected():
    problems = validate_email("Subject", _body(name="Priya"), LEAD)
    assert any("first name" in p for p in problems)


def test_name_match_is_case_insensitive():
    body = "Hi ASHA, " + "word " * 92 + "Open to a 15-min call?"
    assert validate_email("Subject", body, LEAD) == []


# ============================================
# VALIDATION: FABRICATED CLAIMS
# ============================================

@pytest.mark.parametrize("claim", [
    "I noticed your team is expanding rapidly",
    "I saw that your company has recently grown",
    "your recent project caught my eye",
    "I have been following your work closely",
    "your Q3 results were impressive",
])
def test_unsupportable_claims_rejected(claim):
    body = "Hi Asha, " + claim + ". " + "word " * 85 + "Open to a 15-min call?"
    problems = validate_email("Subject", body, LEAD)
    assert any("unsupportable" in p or "placeholder" in p for p in problems), \
        f"{claim!r} not caught: {problems}"


def test_role_based_hook_is_allowed():
    """Referencing their stated title/industry is legitimate, not fabrication."""
    body = ("Hi Asha, most Head of BIM roles I speak to are juggling ISO 19650 "
            "compliance with delivery deadlines. " + "word " * 80 +
            "Open to a 15-min call?")
    assert validate_email("Subject", body, LEAD) == []


# ============================================
# PRE-FLIGHT
# ============================================

def test_dry_run_never_blocked():
    assert preflight(send=False) == []


def test_placeholder_pitch_blocks_sending():
    blockers = preflight(send=True)
    assert any("pitch copy" in b for b in blockers)


def test_missing_postal_address_blocks_sending(monkeypatch):
    monkeypatch.setattr(om, "SENDER_POSTAL_ADDRESS", "")
    blockers = preflight(send=True)
    assert any("POSTAL_ADDRESS" in b for b in blockers)


def test_missing_unsubscribe_url_blocks_sending(monkeypatch):
    monkeypatch.setattr(om, "UNSUBSCRIBE_BASE_URL", "")
    assert any("UNSUBSCRIBE" in b for b in preflight(send=True))


def test_run_refuses_to_send_when_blocked():
    """The blocker must actually stop the run, not just warn."""
    with patch.object(om, "qualified_leads") as mock_leads:
        stats = om.run(send=True)
    mock_leads.assert_not_called()
    assert stats["sent"] == 0


# ============================================
# FOOTER / COMPLIANCE
# ============================================

def test_footer_contains_unsubscribe_and_address(monkeypatch):
    monkeypatch.setattr(om, "SENDER_POSTAL_ADDRESS", "1 Test St, Kolkata 700001")
    monkeypatch.setattr(om, "UNSUBSCRIBE_BASE_URL", "https://x.test/u")
    footer = build_footer("asha@acme.com")
    assert "1 Test St" in footer
    assert "unsubscribe" in footer.lower()
    assert "https://x.test/u" in footer


def test_unsubscribe_url_encodes_email(monkeypatch):
    monkeypatch.setattr(om, "UNSUBSCRIBE_BASE_URL", "https://x.test/u")
    assert "%40" in om.unsubscribe_url("a+b@acme.com")


# ============================================
# MESSAGE ASSEMBLY
# ============================================

def test_message_is_multipart_alternative_with_plain_text(monkeypatch):
    monkeypatch.setattr(om, "SENDER_EMAIL", "me@acme.com")
    monkeypatch.setattr(om, "SENDER_NAME", "Me")
    monkeypatch.setattr(om, "SENDER_POSTAL_ADDRESS", "1 Test St")
    monkeypatch.setattr(om, "UNSUBSCRIBE_BASE_URL", "https://x.test/u")

    msg = build_message(LEAD, "Subject", _body())
    assert msg.get_content_subtype() == "alternative"
    subtypes = [p.get_content_subtype() for p in msg.get_payload()]
    assert "plain" in subtypes and "html" in subtypes


def test_message_has_list_unsubscribe_headers(monkeypatch):
    monkeypatch.setattr(om, "SENDER_EMAIL", "me@acme.com")
    monkeypatch.setattr(om, "UNSUBSCRIBE_BASE_URL", "https://x.test/u")
    msg = build_message(LEAD, "Subject", _body())
    assert msg["List-Unsubscribe"]
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


# ============================================
# CAPS
# ============================================

def test_daily_cap_blocks():
    with patch.object(om, "sends_since", side_effect=[om.SEND_DAILY_CAP, 0]):
        assert "daily cap" in om.cap_blocked()


def test_hourly_cap_blocks():
    with patch.object(om, "sends_since", side_effect=[0, om.SEND_HOURLY_CAP]):
        assert "hourly cap" in om.cap_blocked()


def test_under_caps_not_blocked():
    with patch.object(om, "sends_since", side_effect=[0, 0]):
        assert om.cap_blocked() is None
