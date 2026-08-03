"""
BATCH INFERENCE + SES SNS TESTS
===============================

Batch: JSONL record construction, config validation, native-response text
extraction. SNS: bounce/complaint routing into the suppression list, the
transient-bounce rule, envelope unwrapping.

No AWS calls anywhere.

Run with: pytest backend/tests/test_batch_and_sns.py -v
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import ses_notifications as sns
from leads.bedrock_client import (
    BedrockError,
    _extract_native_text,
    batch_config,
    build_batch_records,
)
from leads.ses_notifications import (
    process_ses_notification,
    process_unsubscribe,
    unwrap_sns_envelope,
)


# ============================================
# BATCH RECORDS
# ============================================

def test_batch_records_are_valid_jsonl(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_CHEAP", "test.cheap-v1:0")
    lines = build_batch_records(
        [("lead1", "sys", "extract this"), ("lead2", "", "and this")],
        role="cheap", max_tokens=512, temperature=0.0)

    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["recordId"] == "lead1"
    assert first["modelInput"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "extract this"},
    ]
    assert first["modelInput"]["max_tokens"] == 512

    second = json.loads(lines[1])
    assert second["modelInput"]["messages"][0]["role"] == "user"  # no system


def test_record_id_is_capped_at_64_chars():
    lines = build_batch_records([("x" * 100, "s", "u")], role="cheap")
    assert len(json.loads(lines[0])["recordId"]) == 64


def test_batch_config_requires_bucket_and_role(monkeypatch):
    monkeypatch.delenv("BEDROCK_BATCH_S3_BUCKET", raising=False)
    monkeypatch.delenv("BEDROCK_BATCH_ROLE_ARN", raising=False)
    with pytest.raises(BedrockError) as excinfo:
        batch_config()
    assert "BEDROCK_BATCH_S3_BUCKET" in str(excinfo.value)


def test_batch_config_reads_env(monkeypatch):
    monkeypatch.setenv("BEDROCK_BATCH_S3_BUCKET", "my-bucket")
    monkeypatch.setenv("BEDROCK_BATCH_ROLE_ARN", "arn:aws:iam::1:role/x")
    cfg = batch_config()
    assert cfg["bucket"] == "my-bucket"
    assert cfg["prefix"] == "batch-inference"


@pytest.mark.parametrize("output,expected", [
    ({"choices": [{"message": {"content": '{"a":1}'}}]}, '{"a":1}'),
    ({"output": {"message": {"content": [{"text": "hello"}]}}}, "hello"),
    ({"generation": "gen text"}, "gen text"),
    ({}, ""),
])
def test_native_text_extraction_shapes(output, expected):
    assert _extract_native_text(output) == expected


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
