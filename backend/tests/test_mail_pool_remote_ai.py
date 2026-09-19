"""
Covers sales/mail_pool_remote_ai.py -- the DigitalOcean-hosted call path
that replaced sales/mail_pool_local_ai.py (2026-09-19, same day) after real
production calls against the local Qwen model measured ~1.1 tokens/second
on this VM (severe CPU starvation, read straight from llama-server's own
timing log during a live failed call) -- no timeout fix could make that
viable, so this pipeline now calls the DigitalOcean-hosted fallback
(alibaba-qwen3-32b) instead, the same model its own Bedrock fallback chain
already pointed at.

No network calls: leads/do_inference_client.py's chat()/is_configured()
are patched.
"""
from unittest.mock import patch

import pytest

import sales.mail_pool_remote_ai as m
from leads import do_inference_client as do


def test_converse_json_meta_returns_parsed_and_meta():
    with patch.object(do, "is_configured", return_value=True), \
         patch.object(do, "chat", return_value=('{"a": 1}', {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}, 2.5)) as chat:
        parsed, meta = m.converse_json_meta("cheap", "sys", "user", max_tokens=500)

    assert parsed == {"a": 1}
    assert meta["model_id"] == m.MODEL_ID
    assert meta["provider"] == "digitalocean"
    assert meta["role"] == "cheap"
    assert meta["input_tokens"] == 10
    assert meta["latency_s"] == 2.5
    chat.assert_called_once()
    args, kwargs = chat.call_args
    assert args[0] == m.MODEL_ID
    assert kwargs["max_tokens"] == 500


def test_converse_json_meta_strips_markdown_fences():
    with patch.object(do, "is_configured", return_value=True), \
         patch.object(do, "chat", return_value=('```json\n{"a": 2}\n```', {}, 1.0)):
        parsed, _meta = m.converse_json_meta("cheap", "sys", "user")
    assert parsed == {"a": 2}


def test_converse_json_meta_raises_when_not_configured():
    with patch.object(do, "is_configured", return_value=False):
        with pytest.raises(m.RemoteMailAIError):
            m.converse_json_meta("cheap", "sys", "user")


def test_converse_json_meta_retries_once_on_malformed_response():
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return "not json at all", {}, 1.0
        return '{"a": 3}', {}, 1.0

    with patch.object(do, "is_configured", return_value=True), \
         patch.object(do, "chat", side_effect=flaky):
        parsed, _meta = m.converse_json_meta("cheap", "sys", "user")

    assert parsed == {"a": 3}
    assert calls["n"] == 2


def test_converse_json_meta_raises_after_malformed_retry_fails():
    with patch.object(do, "is_configured", return_value=True), \
         patch.object(do, "chat", return_value=("still not json", {}, 1.0)):
        with pytest.raises(m.RemoteMailAIError):
            m.converse_json_meta("cheap", "sys", "user")


def test_converse_json_meta_raises_on_transport_error():
    with patch.object(do, "is_configured", return_value=True), \
         patch.object(do, "chat", side_effect=do.DOThrottled("rate limited")):
        with pytest.raises(m.RemoteMailAIError):
            m.converse_json_meta("cheap", "sys", "user")


def test_converse_json_object_returns_none_for_non_dict():
    with patch.object(m, "converse_json_meta", return_value=([1, 2, 3], {})):
        assert m.converse_json_object("cheap", "sys", "user") is None


def test_converse_json_object_returns_dict():
    with patch.object(m, "converse_json_meta", return_value=({"x": 1}, {})):
        assert m.converse_json_object("cheap", "sys", "user") == {"x": 1}
