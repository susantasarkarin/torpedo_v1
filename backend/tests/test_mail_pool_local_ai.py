"""
Covers sales/mail_pool_local_ai.py -- the local-Qwen call path that replaced
Bedrock for sales/mail_pool_ai.py (2026-09-19, Bedrock unavailable, its DO
fallback never had working credentials in production either).

No network calls: leads/local_slm_client.py's chat_json() is patched.
"""
from unittest.mock import patch

import pytest

import sales.mail_pool_local_ai as m
from leads import local_slm_client as slm


def test_converse_json_meta_returns_parsed_and_meta():
    with patch.object(slm, "chat_json", return_value={"a": 1}) as chat_json:
        parsed, meta = m.converse_json_meta("cheap", "sys", "user", max_tokens=500)

    assert parsed == {"a": 1}
    assert meta["model_id"] == m.MODEL_ID
    assert meta["provider"] == "local"
    assert meta["role"] == "cheap"
    assert meta["is_fallback"] is False
    chat_json.assert_called_once()
    _, kwargs = chat_json.call_args
    assert kwargs["system"] == "sys"
    assert kwargs["user"] == "user"
    assert kwargs["max_tokens"] == 500


def test_converse_json_meta_retries_once_on_malformed_response():
    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise slm.LocalSLMMalformedResponse("bad json")
        return {"a": 2}

    with patch.object(slm, "chat_json", side_effect=flaky):
        parsed, _meta = m.converse_json_meta("cheap", "sys", "user")

    assert parsed == {"a": 2}
    assert calls["n"] == 2


def test_converse_json_meta_raises_local_mail_ai_error_after_malformed_retry_fails():
    with patch.object(slm, "chat_json", side_effect=slm.LocalSLMMalformedResponse("bad")):
        with pytest.raises(m.LocalMailAIError):
            m.converse_json_meta("cheap", "sys", "user")


def test_converse_json_meta_raises_local_mail_ai_error_when_unavailable():
    with patch.object(slm, "chat_json", side_effect=slm.LocalSLMUnavailable("down")):
        with pytest.raises(m.LocalMailAIError):
            m.converse_json_meta("cheap", "sys", "user")


def test_converse_json_meta_uses_module_scoped_timeout(monkeypatch):
    monkeypatch.setenv("MAIL_POOL_LOCAL_TIMEOUT_SECONDS", "45")
    with patch.object(slm, "chat_json", return_value={}) as chat_json:
        m.converse_json_meta("cheap", "sys", "user")
    _, kwargs = chat_json.call_args
    assert kwargs["timeout"] == 45.0


def test_converse_json_object_returns_none_for_non_dict():
    with patch.object(m, "converse_json_meta", return_value=([1, 2, 3], {})):
        assert m.converse_json_object("cheap", "sys", "user") is None


def test_converse_json_object_returns_dict():
    with patch.object(m, "converse_json_meta", return_value=({"x": 1}, {})):
        assert m.converse_json_object("cheap", "sys", "user") == {"x": 1}
