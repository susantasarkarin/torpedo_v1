"""
SES SNS TESTS
=============

SNS: bounce/complaint routing into the suppression list, the
transient-bounce rule, envelope unwrapping.

No AWS calls anywhere.

Run with: pytest backend/tests/test_batch_and_sns.py -v
"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import ses_notifications as sns
from leads.ses_notifications import (
    process_ses_notification,
    process_unsubscribe,
    unwrap_sns_envelope,
)


# ============================================
# SNS: BOUNCES
# ============================================

def _bounce(bounce_type, emails):
    return {"notificationType": "Bounce",
            "bounce": {"bounceType": bounce_type,
                       "bouncedRecipients": [{"emailAddress": e} for e in emails]}}


def test_permanent_bounce_suppresses():
    with patch.object(sns, "_suppress") as mock:
        result = process_ses_notification(_bounce("Permanent", ["a@b.com"]))
    mock.assert_called_once_with("a@b.com", "bounced")
    assert result["suppressed"] == ["a@b.com"]


def test_transient_bounce_does_not_suppress():
    """Mailbox-full must not burn a good lead."""
    with patch.object(sns, "_suppress") as mock:
        result = process_ses_notification(_bounce("Transient", ["a@b.com"]))
    mock.assert_not_called()
    assert result["ignored"] == ["a@b.com"]
    assert result["suppressed"] == []


def test_undetermined_bounce_does_not_suppress():
    with patch.object(sns, "_suppress") as mock:
        process_ses_notification(_bounce("Undetermined", ["a@b.com"]))
    mock.assert_not_called()


def test_multiple_recipients_all_suppressed():
    with patch.object(sns, "_suppress") as mock:
        result = process_ses_notification(
            _bounce("Permanent", ["a@b.com", "c@d.com"]))
    assert mock.call_count == 2
    assert sorted(result["suppressed"]) == ["a@b.com", "c@d.com"]


# ============================================
# SNS: COMPLAINTS / UNSUBSCRIBE
# ============================================

def test_complaint_suppresses_with_complaint_reason():
    payload = {"notificationType": "Complaint",
               "complaint": {"complainedRecipients": [{"emailAddress": "a@b.com"}]}}
    with patch.object(sns, "_suppress") as mock:
        result = process_ses_notification(payload)
    mock.assert_called_once_with("a@b.com", "complaint")
    assert result["suppressed"] == ["a@b.com"]


def test_unsubscribe_suppresses():
    with patch.object(sns, "_suppress") as mock:
        assert process_unsubscribe("a@b.com") is True
    mock.assert_called_once_with("a@b.com", "unsubscribed")


def test_unsubscribe_rejects_garbage():
    with patch.object(sns, "_suppress") as mock:
        assert process_unsubscribe("") is False
        assert process_unsubscribe("not-an-email") is False
    mock.assert_not_called()


# ============================================
# SNS: ROBUSTNESS
# ============================================

def test_unknown_notification_type_ignored():
    with patch.object(sns, "_suppress") as mock:
        result = process_ses_notification({"notificationType": "Delivery"})
    mock.assert_not_called()
    assert result["type"] == "Delivery"


def test_malformed_payload_never_raises():
    for payload in ({}, {"bounce": "not a dict"}, {"notificationType": "Bounce"}):
        process_ses_notification(payload)  # must not raise


def test_envelope_unwrap():
    inner = {"notificationType": "Bounce"}
    body = {"Type": "Notification", "Message": json.dumps(inner)}
    assert unwrap_sns_envelope(body) == inner


def test_envelope_unwrap_rejects_non_notification():
    assert unwrap_sns_envelope({"Type": "SubscriptionConfirmation"}) is None


def test_envelope_unwrap_survives_bad_message():
    assert unwrap_sns_envelope({"Type": "Notification", "Message": "{bad"}) is None
