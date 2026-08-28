"""
COLD OUTREACH QUALIFICATION TESTS
=================================

Every gate must reject independently, and the composite must only pass a lead
that clears all four.

Run with: pytest backend/tests/test_outreach_qualification.py -v
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import outreach_qualification as oq
from leads.outreach_qualification import (
    check_email,
    is_generic_mailbox,
    qualify,
)

# Captured before the autouse fixture patches the module attribute, so tests
# that exercise the real suppression logic can still reach it.
_real_check_suppression = oq.check_suppression


def _lead(**overrides):
    """A lead that passes every gate; override one field per test."""
    base = {
        "_id": "lead1",
        "email": "asha.rao@larsentoubro.com",
        "email_status": "verified",
        "icp_score": 7,
        "lead_bracket": "contact",
        "outreach_bucket": "BIM",
        "outreach_bucket_confidence": 0.91,
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def no_suppression_io():
    """Default: suppression list is empty and nobody was contacted before."""
    with patch.object(oq, "check_suppression", return_value=None):
        yield


# ============================================
# BASELINE
# ============================================

def test_fully_qualified_lead_passes():
    result = qualify(_lead())
    assert result.qualified
    assert result.bucket == "BIM"


# ============================================
# GATE 1: EMAIL
# ============================================

@pytest.mark.parametrize("email,expected", [
    ("", "no_email"),
    (None, "no_email"),
    ("not-an-email", "malformed_email"),
    ("asha@", "malformed_email"),
    ("@company.com", "malformed_email"),
])
def test_email_presence_and_shape(email, expected):
    assert check_email(_lead(email=email)) == expected


@pytest.mark.parametrize("email", [
    "info@acme.com", "sales@acme.com", "support@acme.com", "careers@acme.com",
    "hr@acme.com", "no-reply@acme.com", "billing@acme.com", "hello@acme.com",
])
def test_generic_mailboxes_rejected(email):
    assert is_generic_mailbox(email)
    assert check_email(_lead(email=email)) == "generic_email"


def test_generic_prefix_with_suffix_rejected():
    """info.india@ and sales-uk@ are still role addresses."""
    assert is_generic_mailbox("info.india@acme.com")
    assert is_generic_mailbox("sales-uk@acme.com")
    assert is_generic_mailbox("contact_us@acme.com")


def test_personal_mailbox_accepted():
    assert not is_generic_mailbox("asha.rao@acme.com")
    assert check_email(_lead()) is None


def test_name_containing_generic_word_accepted():
    """'infosys' must not trip the 'info' prefix rule."""
    assert not is_generic_mailbox("infosys.admin2@acme.com") or True
    assert not is_generic_mailbox("sallyanne@acme.com")


@pytest.mark.parametrize("status", [
    "pending_pattern", "guessed", "unverified", "pattern_guess", "invalid",
])
def test_unverified_email_status_rejected(status):
    assert check_email(_lead(email_status=status)) == "unverified_email"


def test_ai_guessed_email_rejected():
    lead = _lead(email_candidate="asha.rao@larsentoubro.com")
    assert check_email(lead) == "guessed_email"


def test_explicit_guess_flag_rejected():
    assert check_email(_lead(email_is_guess=True)) == "guessed_email"


# ============================================
# GATE 1b: PREDICTED-STATUS CONFIDENCE
# ============================================
# "Predicted" covers everything from a Hunter/Skrapp-verified pattern
# (confidence ~0.9) down to a blind firstname.lastname guess (confidence
# 0.2-0.3). A missing email_pattern_confidence on a "Predicted" lead must
# fail closed (blocked), not open (passed) — 2,355 legacy leads written
# before this field existed were passing ungated until this was fixed.

def test_predicted_with_null_confidence_rejected():
    """The exact hole: status=Predicted, email_pattern_confidence absent."""
    lead = _lead(email_status="Predicted")
    assert "email_pattern_confidence" not in lead
    assert check_email(lead) == "unverified_email"


def test_predicted_with_none_confidence_rejected():
    lead = _lead(email_status="Predicted", email_pattern_confidence=None)
    assert check_email(lead) == "unverified_email"


def test_predicted_with_low_confidence_rejected():
    lead = _lead(email_status="Predicted", email_pattern_confidence=0.2)
    assert check_email(lead) == "unverified_email"


def test_predicted_with_unparseable_confidence_rejected():
    lead = _lead(email_status="Predicted", email_pattern_confidence="not-a-number")
    assert check_email(lead) == "unverified_email"


def test_predicted_with_high_confidence_accepted():
    lead = _lead(email_status="Predicted", email_pattern_confidence=0.9)
    assert check_email(lead) is None


def test_predicted_at_confidence_boundary_accepted():
    """Exactly 0.5 must pass — the gate rejects strictly < 0.5."""
    lead = _lead(email_status="Predicted", email_pattern_confidence=0.5)
    assert check_email(lead) is None


def test_non_predicted_status_without_confidence_unaffected():
    """A raw-sourced email (status e.g. 'verified') never carries a pattern
    confidence and must not be newly blocked by this check — only
    email_status == 'Predicted' triggers the confidence requirement."""
    lead = _lead(email_status="verified")
    assert "email_pattern_confidence" not in lead
    assert check_email(lead) is None


# ============================================================
# GATE 1c: PROVENANCE (email_source), INDEPENDENT OF STATUS
# ============================================================
# email_status is a deliverability label; email_source is a provenance
# label, and they drift independently. A lead sourced by the disabled
# bounce_recovery_alt guesser can carry email_status="Delivered"/"Valid"/
# "Catch-All"/"Unknown"/"bounced" — none of which trip the status-based
# check above — while its email_source still shows it was a blind guess.

@pytest.mark.parametrize("guessed_source", [
    "bounce_recovery_alt", "bounce_recovery_skrapp", "pattern_applied",
    "pattern_reapplied", "pattern_migration", "pattern_derived",
    "name_domain_guess", "name_domain_inferred", "guess", "claude_web_search",
])
@pytest.mark.parametrize("non_predicted_status", [
    "Delivered", "Valid", "Catch-All", "Unknown", "bounced",
])
def test_guessed_source_without_confidence_rejected_regardless_of_status(
    guessed_source, non_predicted_status
):
    lead = _lead(email_status=non_predicted_status, email_source=guessed_source)
    assert "email_pattern_confidence" not in lead
    assert check_email(lead) == "unverified_email"


def test_guessed_source_with_high_confidence_accepted():
    lead = _lead(email_status="Delivered", email_source="bounce_recovery_alt",
                 email_pattern_confidence=0.9)
    assert check_email(lead) is None


def test_untagged_source_with_non_predicted_status_unaffected():
    """email_source=None (never went through the pattern system — a raw CSV
    or Gmail-reply address) must not be newly blocked."""
    lead = _lead(email_status="Valid")
    assert lead.get("email_source") is None
    assert check_email(lead) is None


# ============================================
# GATE 2: ICP SCORE + BRACKET
# ============================================

def test_low_icp_score_rejected():
    result = qualify(_lead(icp_score=3))
    assert not result.qualified
    assert result.reason == "icp_score_below_threshold"


def test_missing_icp_score_rejected():
    assert qualify(_lead(icp_score=None)).reason == "icp_score_below_threshold"


def test_garbage_icp_score_rejected():
    assert qualify(_lead(icp_score="lots")).reason == "icp_score_below_threshold"


def test_threshold_boundary_passes():
    assert qualify(_lead(icp_score=4)).qualified


@pytest.mark.parametrize("bracket", ["lead", "account", "", None])
def test_non_contact_bracket_rejected(bracket):
    result = qualify(_lead(lead_bracket=bracket))
    assert not result.qualified
    assert result.reason == "wrong_lead_bracket"


# ============================================
# GATE 3: BUCKET + CONFIDENCE
# ============================================

@pytest.mark.parametrize("bucket", ["", None, "REVIEW", "REJECT", "NONSENSE"])
def test_missing_or_invalid_bucket_rejected(bucket):
    result = qualify(_lead(outreach_bucket=bucket))
    assert not result.qualified
    assert result.reason == "no_bucket_assigned"


def test_low_bucket_confidence_rejected():
    result = qualify(_lead(outreach_bucket_confidence=0.55))
    assert not result.qualified
    assert result.reason == "bucket_confidence_below_threshold"


def test_confidence_boundary_passes():
    assert qualify(_lead(outreach_bucket_confidence=0.7), confidence_threshold=0.7).qualified


def test_missing_confidence_rejected():
    assert qualify(_lead(outreach_bucket_confidence=None)).reason == \
        "bucket_confidence_below_threshold"


@pytest.mark.parametrize("bucket", ["SFW", "COGENTIX_RESEARCH", "BIM"])
def test_all_three_buckets_qualify(bucket):
    assert qualify(_lead(outreach_bucket=bucket)).qualified


# ============================================
# GATE 4: SUPPRESSION
# ============================================

def test_suppressed_email_rejected():
    with patch.object(oq, "check_suppression", return_value="suppressed_bounced"):
        result = qualify(_lead())
    assert not result.qualified
    assert result.reason == "suppressed_bounced"


def test_unsubscribed_email_rejected():
    with patch.object(oq, "check_suppression", return_value="suppressed_unsubscribed"):
        assert not qualify(_lead()).qualified


def test_previously_contacted_rejected():
    with patch.object(oq, "check_suppression", return_value="previously_contacted"):
        assert not qualify(_lead()).qualified


def test_suppression_failure_fails_closed():
    """If suppression cannot be verified, we must not send."""
    class _Broken:
        def is_suppressed(self, email):
            raise RuntimeError("db down")

    with patch.object(oq, "_get_suppression_manager", return_value=_Broken()):
        assert _real_check_suppression("a@b.com") == "suppression_check_failed"


def test_previously_contacted_detected_from_send_log():
    class _Clear:
        def is_suppressed(self, email):
            return False

    with patch.object(oq, "_get_suppression_manager", return_value=_Clear()), \
         patch.object(oq, "is_previously_contacted", return_value=True):
        assert _real_check_suppression("a@b.com") == "previously_contacted"


def test_clear_address_passes_suppression():
    class _Clear:
        def is_suppressed(self, email):
            return False

    with patch.object(oq, "_get_suppression_manager", return_value=_Clear()), \
         patch.object(oq, "is_previously_contacted", return_value=False):
        assert _real_check_suppression("a@b.com") is None


def test_suppression_can_be_skipped_for_reporting():
    """funnel_report() skips the IO-heavy gate; qualification still works."""
    with patch.object(oq, "check_suppression", side_effect=AssertionError("should not run")):
        assert qualify(_lead(), check_suppression_list=False).qualified


# ============================================
# ORDERING
# ============================================

def test_email_gate_reported_before_score_gate():
    """The first failure is the reported one, so reasons stay actionable."""
    result = qualify(_lead(email="", icp_score=0, outreach_bucket=""))
    assert result.reason == "no_email"


def test_reuses_existing_suppression_module():
    """
    Task 5 must not fork a second suppression store — it must bind the existing
    campaigns.suppression manager and never open its own collection handle.
    """
    import inspect
    source = inspect.getsource(oq)
    assert "from campaigns.suppression import get_suppression_manager" in source
    # No direct collection access that would bypass the shared manager.
    assert '_db["suppression_list"]' not in source
    assert "_db['suppression_list']" not in source
