"""
BEDROCK CLIENT TESTS (Converse API)
===================================

Covers:
1. parse_json_strict() against malformed output — fences, trailing text,
   invalid JSON, empty
2. Role -> model ID resolution from environment
3. Converse request shape (Converse API, never invoke_model)
4. Throttling retry with exponential backoff
5. Startup model-access validation
6. converse_json one-retry-with-reminder behaviour
7. The architectural rule: only this module touches boto3 / model IDs

No AWS calls: the boto3 clients are patched.

Run with: pytest backend/tests/test_bedrock_client.py -v
"""

import json
import os
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import bedrock_client as bc
from leads.bedrock_client import (
    BedrockError,
    DEFAULT_MODEL_CHEAP,
    DEFAULT_MODEL_SMART,
    DEFAULT_REGION,
    JSONParseError,
    ModelAccessError,
    converse,
    converse_json,
    converse_string_list,
    get_region,
    model_for_role,
    parse_json_strict,
    validate_model_access,
)


def _response(text: str, tokens=(10, 20)):
    return {
        "output": {"message": {"content": [{"text": text}]}},
        "usage": {"inputTokens": tokens[0], "outputTokens": tokens[1],
                  "totalTokens": sum(tokens)},
    }


@pytest.fixture(autouse=True)
def clean_clients():
    bc.reset_clients()
    yield
    bc.reset_clients()


# ============================================
# parse_json_strict — WELL-FORMED
# ============================================

def test_parses_plain_object():
    assert parse_json_strict('{"a": 1}') == {"a": 1}


def test_parses_plain_array():
    assert parse_json_strict('["a", "b"]') == ["a", "b"]


@pytest.mark.parametrize("fenced", [
    '```json\n{"a": 1}\n```',
    '```\n{"a": 1}\n```',
    '```JSON\n{"a": 1}\n```',
    '  ```json\n{"a": 1}\n```  ',
])
def test_strips_markdown_fences(fenced):
    assert parse_json_strict(fenced) == {"a": 1}


def test_ignores_leading_prose():
    assert parse_json_strict('Sure! Here you go:\n{"a": 1}') == {"a": 1}


def test_ignores_trailing_text():
    assert parse_json_strict('{"a": 1}\n\nHope that helps!') == {"a": 1}


def test_handles_prose_around_array():
    assert parse_json_strict('Here: ["x", "y"] done') == ["x", "y"]


# ============================================
# parse_json_strict — MALFORMED
# ============================================

@pytest.mark.parametrize("bad", [
    "", "   ", None,
    "not json at all",
    "{",
    '{"a": ',
    '{"a": 1',
    "[unquoted, tokens]",
    "I'm sorry, I can't help with that.",
    '{"a": 1,}',
])
def test_malformed_raises_json_parse_error(bad):
    with pytest.raises(JSONParseError):
        parse_json_strict(bad)


def test_truncated_response_raises():
    """The common real failure: output cut off by maxTokens."""
    with pytest.raises(JSONParseError):
        parse_json_strict('{"queries": ["site:linkedin.com/in/ BIM", "site:link')


def test_error_message_includes_a_snippet():
    with pytest.raises(JSONParseError) as excinfo:
        parse_json_strict("total nonsense here")
    assert "nonsense" in str(excinfo.value)


# ============================================
# ROLE -> MODEL RESOLUTION
# ============================================

def test_both_roles_default_to_qwen(monkeypatch):
    """Qwen-only policy: no model other than Qwen may be reachable by default,
    on either role."""
    monkeypatch.delenv("BEDROCK_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("BEDROCK_MODEL_SMART", raising=False)
    assert model_for_role("cheap") == DEFAULT_MODEL_CHEAP == "qwen.qwen3-32b-v1:0"
    assert model_for_role("smart") == DEFAULT_MODEL_SMART == "qwen.qwen3-32b-v1:0"


def test_no_non_qwen_model_appears_in_any_default_chain(monkeypatch):
    """Guards the policy against a stray fallback creeping back in."""
    for var in ("BEDROCK_MODEL_CHEAP", "BEDROCK_MODEL_SMART",
                "BEDROCK_FALLBACKS_CHEAP", "BEDROCK_FALLBACKS_SMART"):
        monkeypatch.delenv(var, raising=False)
    bc._demoted.clear()

    for role in ("cheap", "smart"):
        for model_id in bc.models_for_role(role):
            assert "qwen" in model_id.lower(), (
                f"non-Qwen model {model_id!r} in the default {role} chain")


def test_default_region_is_mumbai(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    assert get_region() == DEFAULT_REGION == "ap-south-1"


def test_models_are_swappable_by_env_alone(monkeypatch):
    """Changing model must require only an env var."""
    monkeypatch.setenv("BEDROCK_MODEL_CHEAP", "amazon.nova-lite-v1:0")
    monkeypatch.setenv("BEDROCK_MODEL_SMART", "anthropic.claude-haiku-4-5")
    assert model_for_role("cheap") == "amazon.nova-lite-v1:0"
    assert model_for_role("smart") == "anthropic.claude-haiku-4-5"


def test_unknown_role_rejected():
    with pytest.raises(ValueError):
        model_for_role("medium")


# ============================================
# CONVERSE REQUEST SHAPE
# ============================================

def test_uses_converse_not_invoke_model(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_CHEAP", "test.model")
    client = MagicMock()
    client.converse.return_value = _response('{"ok": true}')

    with patch.object(bc, "_get_runtime_client", return_value=client):
        converse("cheap", "sys", "user", max_tokens=256, temperature=0.3)

    client.converse.assert_called_once()
    assert not client.invoke_model.called
    kwargs = client.converse.call_args.kwargs
    assert kwargs["modelId"] == "test.model"
    assert kwargs["messages"] == [{"role": "user", "content": [{"text": "user"}]}]
    assert kwargs["system"] == [{"text": "sys"}]
    assert kwargs["inferenceConfig"] == {"maxTokens": 256, "temperature": 0.3}


def test_system_omitted_when_empty():
    client = MagicMock()
    client.converse.return_value = _response("hi")
    with patch.object(bc, "_get_runtime_client", return_value=client):
        converse("cheap", "", "user")
    assert "system" not in client.converse.call_args.kwargs


def test_no_reasoning_config_sent():
    """Qwen must run in non-thinking mode — reasoning bills as output."""
    client = MagicMock()
    client.converse.return_value = _response("hi")
    with patch.object(bc, "_get_runtime_client", return_value=client):
        converse("smart", "sys", "user")
    kwargs = client.converse.call_args.kwargs
    assert "additionalModelRequestFields" not in kwargs
    assert "reasoning_config" not in json.dumps(kwargs)


def test_empty_response_raises():
    client = MagicMock()
    client.converse.return_value = _response("")
    with patch.object(bc, "_get_runtime_client", return_value=client):
        with pytest.raises(BedrockError):
            converse("cheap", "sys", "user")


def test_usage_is_logged_at_info(caplog):
    client = MagicMock()
    client.converse.return_value = _response("hi", tokens=(111, 222))
    with patch.object(bc, "_get_runtime_client", return_value=client):
        with caplog.at_level("INFO", logger="bedrock_client"):
            converse("cheap", "sys", "user")
    logged = caplog.text
    assert "input_tokens=111" in logged
    assert "output_tokens=222" in logged
    assert "latency=" in logged


# ============================================
# RETRIES
# ============================================

def _throttle():
    err = Exception("throttled")
    err.response = {"Error": {"Code": "ThrottlingException"}}
    return err


def test_retries_on_throttling_then_succeeds():
    client = MagicMock()
    client.converse.side_effect = [_throttle(), _throttle(), _response("ok")]
    with patch.object(bc, "_get_runtime_client", return_value=client), \
         patch.object(bc.time, "sleep") as sleep:
        assert converse("cheap", "s", "u") == "ok"
    assert client.converse.call_count == 3
    # Exponential backoff: 1s then 2s
    assert [c.args[0] for c in sleep.call_args_list] == [1, 2]


def test_raises_after_exhausting_retries(monkeypatch):
    """Throttles retry on the same model; with no fallbacks the chain ends there."""
    monkeypatch.setenv("BEDROCK_MAX_RETRIES", "3")
    monkeypatch.setenv("BEDROCK_FALLBACKS_CHEAP", "")   # single-model chain
    bc._demoted.clear()
    client = MagicMock()
    client.converse.side_effect = [_throttle(), _throttle(), _throttle()]
    with patch.object(bc, "_get_runtime_client", return_value=client), \
         patch.object(bc.time, "sleep"):
        with pytest.raises(BedrockError):
            converse("cheap", "s", "u")
    assert client.converse.call_count == 3


def test_non_retryable_error_does_not_retry_same_model(monkeypatch):
    """
    A non-retryable error must not burn the retry budget on the same model.
    With fallbacks disabled the chain is one model, so exactly one call.
    """
    monkeypatch.setenv("BEDROCK_FALLBACKS_CHEAP", "")
    bc._demoted.clear()
    err = Exception("denied")
    err.response = {"Error": {"Code": "AccessDeniedException"}}
    client = MagicMock()
    client.converse.side_effect = err
    with patch.object(bc, "_get_runtime_client", return_value=client):
        with pytest.raises(BedrockError):
            converse("cheap", "s", "u")
    assert client.converse.call_count == 1


def test_falls_over_to_next_model_on_unusable_error(monkeypatch):
    """An unusable primary hands off to the fallback, which answers."""
    monkeypatch.setenv("BEDROCK_MODEL_CHEAP", "primary-model")
    monkeypatch.setenv("BEDROCK_FALLBACKS_CHEAP", "fallback-model")
    bc._demoted.clear()

    err = Exception("Operation not allowed")
    err.response = {"Error": {"Code": "ValidationException"}}
    client = MagicMock()
    client.converse.side_effect = [err, _response("hello")]

    with patch.object(bc, "_get_runtime_client", return_value=client):
        text, meta = bc.converse_meta("cheap", "s", "u")

    assert text == "hello"
    assert meta["model_id"] == "fallback-model"
    assert meta["is_fallback"] is True
    assert meta["fallback_position"] == 1
    assert client.converse.call_count == 2


def test_all_models_failing_names_every_one(monkeypatch):
    """
    When the whole chain fails the error lists each model — the signature of a
    credential/account problem rather than a model problem.
    """
    monkeypatch.setenv("BEDROCK_MODEL_CHEAP", "m1")
    monkeypatch.setenv("BEDROCK_FALLBACKS_CHEAP", "m2,m3")
    bc._demoted.clear()

    err = Exception("Operation not allowed")
    err.response = {"Error": {"Code": "ValidationException"}}
    client = MagicMock()
    client.converse.side_effect = err

    with patch.object(bc, "_get_runtime_client", return_value=client):
        with pytest.raises(BedrockError) as excinfo:
            converse("cheap", "s", "u")

    message = str(excinfo.value)
    assert "all 3 models failed" in message
    for model_id in ("m1", "m2", "m3"):
        assert model_id in message
    assert client.converse.call_count == 3


def test_demoted_model_moves_to_back_of_chain(monkeypatch):
    """After failing over, the dead primary is tried last, not first."""
    monkeypatch.setenv("BEDROCK_MODEL_CHEAP", "primary-model")
    monkeypatch.setenv("BEDROCK_FALLBACKS_CHEAP", "fallback-model")
    bc._demoted.clear()

    assert bc.models_for_role("cheap")[0] == "primary-model"
    bc._demote("primary-model")
    assert bc.models_for_role("cheap") == ["fallback-model", "primary-model"]
    bc._demoted.clear()


# ============================================
# STARTUP VALIDATION
# ============================================

def test_validate_passes_when_models_present(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_CHEAP", "qwen.qwen3-32b-v1:0")
    monkeypatch.setenv("BEDROCK_MODEL_SMART", "deepseek.v3-v1:0")
    control = MagicMock()
    control.list_foundation_models.return_value = {"modelSummaries": [
        {"modelId": "qwen.qwen3-32b-v1:0"}, {"modelId": "deepseek.v3-v1:0"}]}
    with patch.object(bc, "_get_control_client", return_value=control):
        assert validate_model_access() == {
            "cheap": "qwen.qwen3-32b-v1:0", "smart": "deepseek.v3-v1:0"}


def test_validate_fails_fast_on_missing_model(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_CHEAP", "qwen.qwen3-32b-v1:0")
    monkeypatch.setenv("BEDROCK_MODEL_SMART", "deepseek.v3-v1:0")
    control = MagicMock()
    control.list_foundation_models.return_value = {"modelSummaries": [
        {"modelId": "qwen.qwen3-32b-v1:0"}]}
    with patch.object(bc, "_get_control_client", return_value=control):
        with pytest.raises(ModelAccessError) as excinfo:
            validate_model_access()
    assert "deepseek" in str(excinfo.value).lower()
    assert "model access" in str(excinfo.value).lower()


def test_validate_surfaces_credential_failure():
    control = MagicMock()
    control.list_foundation_models.side_effect = RuntimeError("no credentials")
    with patch.object(bc, "_get_control_client", return_value=control):
        with pytest.raises(ModelAccessError):
            validate_model_access()


# ============================================
# converse_json RETRY-WITH-REMINDER
# ============================================

def test_converse_json_retries_once_with_reminder():
    client = MagicMock()
    client.converse.side_effect = [_response("not json"), _response('{"a": 1}')]
    with patch.object(bc, "_get_runtime_client", return_value=client):
        assert converse_json("cheap", "sys", "user") == {"a": 1}

    assert client.converse.call_count == 2
    second_user = client.converse.call_args_list[1].kwargs["messages"][0]["content"][0]["text"]
    assert "only valid json" in second_user.lower()


def test_converse_json_raises_if_retry_also_fails():
    client = MagicMock()
    client.converse.side_effect = [_response("nope"), _response("still nope")]
    with patch.object(bc, "_get_runtime_client", return_value=client):
        with pytest.raises(JSONParseError):
            converse_json("cheap", "sys", "user")
    assert client.converse.call_count == 2


def test_string_list_from_wrapped_object():
    client = MagicMock()
    client.converse.return_value = _response('{"queries": ["a", "b"]}')
    with patch.object(bc, "_get_runtime_client", return_value=client):
        assert converse_string_list("cheap", "s", "u", key="queries") == ["a", "b"]


def test_string_list_drops_non_strings():
    client = MagicMock()
    client.converse.return_value = _response('{"queries": ["a", 5, null, "  "]}')
    with patch.object(bc, "_get_runtime_client", return_value=client):
        assert converse_string_list("cheap", "s", "u", key="queries") == ["a"]


def test_string_list_returns_none_when_unusable():
    client = MagicMock()
    client.converse.return_value = _response('{"queries": []}')
    with patch.object(bc, "_get_runtime_client", return_value=client):
        assert converse_string_list("cheap", "s", "u", key="queries") is None


# ============================================
# ARCHITECTURAL RULES
# ============================================

def test_no_credentials_in_source():
    import inspect
    source = inspect.getsource(bc)
    for marker in ("AKIA", "aws_secret_access_key", "aws_access_key_id"):
        assert marker not in source


def test_only_bedrock_client_imports_boto3_for_models():
    """
    No other lead-pipeline module may import boto3 for Bedrock or name a model
    ID. (outreach_mailer is permitted boto3 solely for the SES transport.)
    """
    import pathlib
    leads_dir = pathlib.Path(__file__).parent.parent / "leads"
    offenders = []
    for path in leads_dir.glob("*.py"):
        if path.name == "bedrock_client.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "bedrock-runtime" in text or "invoke_model" in text:
            offenders.append(f"{path.name}: bedrock access")
        for model_marker in ("qwen.", "deepseek.", "anthropic.claude", "amazon.nova"):
            if model_marker in text:
                offenders.append(f"{path.name}: model id {model_marker!r}")
    assert not offenders, f"model/bedrock access outside bedrock_client: {offenders}"
