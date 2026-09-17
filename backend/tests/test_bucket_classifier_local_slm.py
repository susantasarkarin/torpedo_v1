"""
BUCKET CLASSIFIER — LOCAL SLM OPT-IN PATH

Covers the BUCKET_CLASSIFIER_USE_LOCAL_SLM routing added 2026-09-17: the
first-pass ("cheap") role can be pointed at the local Qwen2.5-0.5B via
local_slm_client.chat_json() instead of bedrock_client, entirely opt-in
(off by default) and never applied to the escalation ("smart") role.

No live server: local_slm_client.chat_json is patched, same convention as
test_bucket_classifier.py patching bedrock_client.converse.
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import bedrock_client, bucket_classifier, local_slm_client
from leads.bucket_classifier import classify_lead
from leads.outreach_config import REVIEW_BUCKET

QUALIFIED = {
    "_id": "abc123",
    "name": "Asha Rao",
    "title": "Head of BIM",
    "company": "Larsen & Toubro",
    "company_industry": "Construction",
    "country": "India",
    "seniority_level": "Head",
}


@pytest.fixture
def local_slm_enabled(monkeypatch):
    """Flip the module-level flag directly -- it's read at import time, so
    monkeypatching the env var alone (after import) would have no effect."""
    monkeypatch.setattr(bucket_classifier, "USE_LOCAL_SLM_FOR_FIRST_PASS", True)


def test_flag_off_by_default():
    """The whole point of an opt-in flag: importing the module with no env
    var set must leave Bedrock as the path, not silently switch providers."""
    assert bucket_classifier.USE_LOCAL_SLM_FOR_FIRST_PASS is False


def test_first_pass_uses_local_when_enabled(local_slm_enabled):
    payload = {"bucket": "BIM", "confidence": 0.9, "reason": "clear match"}
    with patch.object(local_slm_client, "chat_json", return_value=payload) as local_mock, \
         patch.object(bedrock_client, "converse") as bedrock_mock:
        result = classify_lead(QUALIFIED, threshold=0.7)

    assert result["bucket"] == "BIM"
    assert result["method"] == "cheap"
    local_mock.assert_called_once()
    bedrock_mock.assert_not_called()  # Bedrock never touched when local handles it


def test_escalation_never_uses_local_even_when_flag_enabled(local_slm_enabled, monkeypatch):
    """The flag only ever applies to the first-pass role -- escalation
    (smart) must stay on bedrock_client unconditionally, per standing
    instruction not to touch smart-role routing."""
    monkeypatch.setenv("BEDROCK_MODEL_CHEAP", "qwen.qwen3-32b-v1:0")
    monkeypatch.setenv("BEDROCK_MODEL_SMART", "qwen.qwen3-235b-v1:0")

    local_payload = {"bucket": "BIM", "confidence": 0.55, "reason": "thin"}
    smart_response = '{"bucket": "BIM", "confidence": 0.88, "reason": "confirmed"}'

    with patch.object(local_slm_client, "chat_json", return_value=local_payload) as local_mock, \
         patch.object(bedrock_client, "converse", return_value=smart_response) as bedrock_mock:
        result = classify_lead(QUALIFIED, threshold=0.7)

    local_mock.assert_called_once()   # first pass -> local
    bedrock_mock.assert_called_once()  # escalation -> still Bedrock
    called_role = bedrock_mock.call_args.kwargs.get("role") or bedrock_mock.call_args.args[0]
    assert called_role == "smart"
    assert result["method"] == "smart_escalation"
    assert result["confidence"] == 0.88


def test_local_slm_error_routes_to_review_not_a_crash(local_slm_enabled):
    with patch.object(
        local_slm_client, "chat_json",
        side_effect=local_slm_client.LocalSLMUnavailable("queue timeout"),
    ):
        result = classify_lead(QUALIFIED, threshold=0.7)

    assert result["bucket"] == REVIEW_BUCKET
    assert result["method"] == "error"


def test_local_slm_malformed_response_routes_to_review(local_slm_enabled):
    with patch.object(
        local_slm_client, "chat_json",
        side_effect=local_slm_client.LocalSLMMalformedResponse("bad json"),
    ):
        result = classify_lead(QUALIFIED, threshold=0.7)

    assert result["bucket"] == REVIEW_BUCKET
    assert result["method"] == "error"


def test_local_response_still_goes_through_validate_result(local_slm_enabled):
    """An unknown bucket from the local model must be rejected exactly like
    an unknown bucket from Bedrock would be -- same validate_result() call,
    same contract, regardless of which provider answered."""
    payload = {"bucket": "NOT_A_REAL_BUCKET", "confidence": 0.9, "reason": "??"}
    with patch.object(local_slm_client, "chat_json", return_value=payload):
        result = classify_lead(QUALIFIED, threshold=0.7)

    assert result["bucket"] == REVIEW_BUCKET
