"""
LOCAL SLM CLIENT TESTS -- Torpedo v1 Local Intelligence Layer, Phase 1

Covers leads/local_slm_client.py: the standalone client Phase 2's migration
targets (historical_classifier.py, reply_sentiment.py, reply_intent.py,
gemini_enrichment.py, lead_gen_mcp, email_crm_pipeline) will use instead of
their current independent transports (claude_gateway, direct anthropic,
google.generativeai, direct boto3).

No live network, no live Redis -- the transport (do_inference_client.chat)
and the admission gate (acquire_local_llm_slot) are both monkeypatched, same
convention as test_local_llm_gate.py and test_bedrock_client.py.
"""

import json

import pytest

from leads import local_slm_client as slm
from leads.local_llm_gate import LocalLLMQueueTimeout
from leads.do_inference_client import DOInferenceError


@pytest.fixture(autouse=True)
def _configure_endpoint(monkeypatch):
    monkeypatch.setenv("SELF_HOSTED_BASE_URL", "http://127.0.0.1:8003/v1")
    monkeypatch.setenv("SELF_HOSTED_API_KEY", "test-key")


@pytest.fixture
def no_gate(monkeypatch):
    """Bypass the real Redis-backed gate for tests that only exercise
    classify()'s own request-building/response-parsing logic."""
    import contextlib

    @contextlib.contextmanager
    def _fake_acquire(timeout=None):
        yield

    monkeypatch.setattr(slm, "acquire_local_llm_slot", _fake_acquire)


def _fake_chat(response_text, usage=None, latency=0.5):
    def _chat(model, system, user, max_tokens=1024, temperature=0.0,
              base_url=None, api_key=None, extra_params=None, timeout=None):
        return response_text, usage or {}, latency
    return _chat


# ============================================================
# JSON mode (response_format), behind a flag -- 2026-09-19
# ============================================================

def test_json_mode_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_JSON_MODE", raising=False)
    assert slm._json_mode_enabled() is False


def test_json_mode_enabled_by_env_flag(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_JSON_MODE", "true")
    assert slm._json_mode_enabled() is True


def test_chat_json_omits_response_format_when_flag_is_off(monkeypatch, no_gate):
    monkeypatch.delenv("LOCAL_LLM_JSON_MODE", raising=False)
    calls = []

    def _chat(model, system, user, max_tokens=1024, temperature=0.0,
             base_url=None, api_key=None, extra_params=None, timeout=None):
        calls.append(extra_params)
        return '{"a": 1}', {}, 0.1
    monkeypatch.setattr(slm._transport, "chat", _chat)

    slm.chat_json(system="s", user="u")
    assert calls == [None]


def test_chat_json_requests_json_object_format_when_flag_is_on(monkeypatch, no_gate):
    monkeypatch.setenv("LOCAL_LLM_JSON_MODE", "true")
    calls = []

    def _chat(model, system, user, max_tokens=1024, temperature=0.0,
             base_url=None, api_key=None, extra_params=None, timeout=None):
        calls.append(extra_params)
        return '{"a": 1}', {}, 0.1
    monkeypatch.setattr(slm._transport, "chat", _chat)

    slm.chat_json(system="s", user="u")
    assert calls == [{"response_format": {"type": "json_object"}}]


# ============================================================
# Happy path
# ============================================================

def test_classify_rejects_a_model_that_answers_under_the_wrong_key(monkeypatch, no_gate):
    # classify() prompts for a "category" field -- a model that answers with
    # "classification" instead (a real mistake a 0.5B model could make) must
    # be rejected as malformed, not silently accepted under a different key.
    monkeypatch.setattr(
        slm._transport, "chat",
        _fake_chat(json.dumps({"classification": "SALES_LEAD", "confidence": 0.87})),
    )
    with pytest.raises(slm.LocalSLMMalformedResponse, match="not one of"):
        slm.classify(
            task_description="Classify this email.",
            categories=["SALES_LEAD", "NOT_SALES_LEAD"],
            content="Would you have capacity to help with fieldwork next quarter?",
        )


def test_classify_happy_path_with_correct_key(monkeypatch, no_gate):
    monkeypatch.setattr(
        slm._transport, "chat",
        _fake_chat(json.dumps({"category": "SALES_LEAD", "confidence": 0.87})),
    )
    result = slm.classify(
        task_description="Classify this email.",
        categories=["SALES_LEAD", "NOT_SALES_LEAD"],
        content="Would you have capacity to help with fieldwork next quarter?",
    )
    assert result.category == "SALES_LEAD"
    assert result.confidence == 0.87
    assert result.extra_fields == {}
    assert result.latency_seconds == 0.5


def test_classify_extracts_requested_extra_fields(monkeypatch, no_gate):
    monkeypatch.setattr(
        slm._transport, "chat",
        _fake_chat(json.dumps({
            "category": "SALES_LEAD", "confidence": 0.9, "urgency": "high",
        })),
    )
    result = slm.classify(
        task_description="Classify.", categories=["SALES_LEAD", "NOT_SALES_LEAD"],
        content="...", extra_fields={"urgency": "high|medium|low"},
    )
    assert result.extra_fields == {"urgency": "high"}


def test_classify_strips_markdown_code_fences(monkeypatch, no_gate):
    monkeypatch.setattr(
        slm._transport, "chat",
        _fake_chat('```json\n{"category": "SALES_LEAD", "confidence": 0.5}\n```'),
    )
    result = slm.classify(
        task_description="Classify.", categories=["SALES_LEAD", "NOT_SALES_LEAD"],
        content="...",
    )
    assert result.category == "SALES_LEAD"


# ============================================================
# The structural guardrail -- rejected BEFORE calling the model
# ============================================================

def test_classify_rejects_too_many_extra_fields_without_calling_model(monkeypatch, no_gate):
    called = []
    monkeypatch.setattr(slm._transport, "chat", lambda *a, **k: called.append(1))
    with pytest.raises(ValueError, match="caps extra fields"):
        slm.classify(
            task_description="Classify.", categories=["A", "B"], content="...",
            extra_fields={"f1": "x", "f2": "x", "f3": "x", "f4": "x"},
        )
    assert called == []  # never reached the transport


def test_classify_rejects_empty_category_list(no_gate):
    with pytest.raises(ValueError, match="non-empty category list"):
        slm.classify(task_description="Classify.", categories=[], content="...")


# ============================================================
# Malformed responses -- the model answered, but wrongly
# ============================================================

def test_classify_raises_on_non_json_output(monkeypatch, no_gate):
    monkeypatch.setattr(slm._transport, "chat", _fake_chat("not json at all"))
    with pytest.raises(slm.LocalSLMMalformedResponse):
        slm.classify(task_description="Classify.", categories=["A", "B"], content="...")


def test_classify_raises_on_category_outside_enum(monkeypatch, no_gate):
    monkeypatch.setattr(
        slm._transport, "chat",
        _fake_chat(json.dumps({"category": "MAYBE", "confidence": 0.5})),
    )
    with pytest.raises(slm.LocalSLMMalformedResponse, match="not one of"):
        slm.classify(task_description="Classify.", categories=["A", "B"], content="...")


def test_classify_raises_on_out_of_range_confidence(monkeypatch, no_gate):
    monkeypatch.setattr(
        slm._transport, "chat",
        _fake_chat(json.dumps({"category": "A", "confidence": 1.5})),
    )
    with pytest.raises(slm.LocalSLMMalformedResponse, match="invalid confidence"):
        slm.classify(task_description="Classify.", categories=["A", "B"], content="...")


def test_classify_raises_on_non_numeric_confidence(monkeypatch, no_gate):
    monkeypatch.setattr(
        slm._transport, "chat",
        _fake_chat(json.dumps({"category": "A", "confidence": "high"})),
    )
    with pytest.raises(slm.LocalSLMMalformedResponse, match="invalid confidence"):
        slm.classify(task_description="Classify.", categories=["A", "B"], content="...")


def test_classify_raises_on_bool_confidence(monkeypatch, no_gate):
    # bool is a subclass of int in Python -- isinstance(True, int) is True --
    # this guards against "confidence": true slipping past the numeric check.
    monkeypatch.setattr(
        slm._transport, "chat",
        _fake_chat(json.dumps({"category": "A", "confidence": True})),
    )
    with pytest.raises(slm.LocalSLMMalformedResponse, match="invalid confidence"):
        slm.classify(task_description="Classify.", categories=["A", "B"], content="...")


def test_classify_raises_on_non_object_json(monkeypatch, no_gate):
    monkeypatch.setattr(slm._transport, "chat", _fake_chat(json.dumps(["A", "B"])))
    with pytest.raises(slm.LocalSLMMalformedResponse, match="non-object"):
        slm.classify(task_description="Classify.", categories=["A", "B"], content="...")


# ============================================================
# Unavailability -- the server didn't answer at all
# ============================================================

def test_classify_raises_local_slm_unavailable_on_transport_error(monkeypatch, no_gate):
    def _raise(*a, **k):
        raise DOInferenceError("connection refused")
    monkeypatch.setattr(slm._transport, "chat", _raise)
    with pytest.raises(slm.LocalSLMUnavailable):
        slm.classify(task_description="Classify.", categories=["A", "B"], content="...")


def test_transport_error_message_never_says_digitalocean(monkeypatch, no_gate):
    """2026-09-19: do_inference_client.py is a shared transport reused for
    both the real DigitalOcean endpoint and this local server -- its
    exception messages say "DigitalOcean" unconditionally, which was
    confirmed live to make LOCAL timeouts confusingly show up in logs as
    "DigitalOcean inference timed out" even though nothing ever left the
    VM. The local path must relabel this before it reaches a caller."""
    def _raise(*a, **k):
        raise DOInferenceError("DigitalOcean inference timed out after 90.0s")
    monkeypatch.setattr(slm._transport, "chat", _raise)
    with pytest.raises(slm.LocalSLMUnavailable) as exc_info:
        slm.classify(task_description="Classify.", categories=["A", "B"], content="...")
    message = str(exc_info.value)
    assert "DigitalOcean" not in message
    assert "local model" in message
    assert "90.0s" in message  # real detail preserved, just relabeled


def test_classify_raises_local_slm_unavailable_on_queue_timeout(monkeypatch):
    import contextlib

    @contextlib.contextmanager
    def _timeout_gate(timeout=None):
        raise LocalLLMQueueTimeout("no slot free within 5s")
        yield  # pragma: no cover

    monkeypatch.setattr(slm, "acquire_local_llm_slot", _timeout_gate)
    with pytest.raises(slm.LocalSLMUnavailable, match="queue timeout"):
        slm.classify(task_description="Classify.", categories=["A", "B"], content="...")


def test_classify_raises_local_slm_unavailable_when_base_url_unset(monkeypatch, no_gate):
    monkeypatch.delenv("SELF_HOSTED_BASE_URL", raising=False)
    called = []
    monkeypatch.setattr(slm._transport, "chat", lambda *a, **k: called.append(1))
    with pytest.raises(slm.LocalSLMUnavailable, match="SELF_HOSTED_BASE_URL"):
        slm.classify(task_description="Classify.", categories=["A", "B"], content="...")
    assert called == []  # never reached the transport without a base URL


# ============================================================
# The gate is actually mandatory -- not bypassable by accident
# ============================================================

# ============================================================
# chat_json() -- the low-level primitive for callers with their own prompt
# ============================================================

def test_chat_json_returns_the_parsed_object(monkeypatch, no_gate):
    monkeypatch.setattr(
        slm._transport, "chat",
        _fake_chat(json.dumps({"bucket": "BIM", "confidence": 0.9, "reason": "match"})),
    )
    result = slm.chat_json(system="sys prompt", user="user prompt")
    assert result == {"bucket": "BIM", "confidence": 0.9, "reason": "match"}


def test_chat_json_strips_markdown_fences(monkeypatch, no_gate):
    monkeypatch.setattr(
        slm._transport, "chat",
        _fake_chat('```json\n{"bucket": "REJECT", "confidence": 1.0, "reason": "x"}\n```'),
    )
    result = slm.chat_json(system="sys", user="user")
    assert result["bucket"] == "REJECT"


def test_chat_json_raises_on_non_json(monkeypatch, no_gate):
    monkeypatch.setattr(slm._transport, "chat", _fake_chat("not json"))
    with pytest.raises(slm.LocalSLMMalformedResponse):
        slm.chat_json(system="sys", user="user")


def test_chat_json_raises_on_non_object_json(monkeypatch, no_gate):
    monkeypatch.setattr(slm._transport, "chat", _fake_chat(json.dumps(["a", "b"])))
    with pytest.raises(slm.LocalSLMMalformedResponse, match="non-object"):
        slm.chat_json(system="sys", user="user")


def test_chat_json_raises_local_slm_unavailable_on_transport_error(monkeypatch, no_gate):
    def _raise(*a, **k):
        raise DOInferenceError("connection refused")
    monkeypatch.setattr(slm._transport, "chat", _raise)
    with pytest.raises(slm.LocalSLMUnavailable):
        slm.chat_json(system="sys", user="user")


def test_chat_json_does_not_impose_a_field_schema(monkeypatch, no_gate):
    """Unlike classify(), chat_json() has no category/confidence contract of
    its own -- it's the caller's job (e.g. bucket_classifier.validate_result)
    to validate the shape. Any well-formed JSON object passes through."""
    monkeypatch.setattr(
        slm._transport, "chat",
        _fake_chat(json.dumps({"anything": "goes", "no_category_key": True})),
    )
    result = slm.chat_json(system="sys", user="user")
    assert result == {"anything": "goes", "no_category_key": True}


def test_classify_goes_through_the_admission_gate(monkeypatch):
    """Unlike the other tests, this one does NOT install `no_gate` -- it
    proves acquire_local_llm_slot is actually called on the request path,
    not just available for tests to skip."""
    calls = []
    import contextlib

    @contextlib.contextmanager
    def _tracking_gate(timeout=None):
        calls.append("acquired")
        yield

    monkeypatch.setattr(slm, "acquire_local_llm_slot", _tracking_gate)
    monkeypatch.setattr(
        slm._transport, "chat",
        _fake_chat(json.dumps({"category": "A", "confidence": 0.5})),
    )
    slm.classify(task_description="Classify.", categories=["A", "B"], content="...")
    assert calls == ["acquired"]
