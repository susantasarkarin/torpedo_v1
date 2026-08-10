"""
Cross-provider failover: AWS Bedrock primary -> DigitalOcean fallback.

These cover the behaviour the old Bedrock-only chain did NOT have. On
2026-08-09 the Bedrock API key expired and every model in the qwen -> deepseek
-> haiku chain failed with the same ValidationException inside 0.6s, because
they all authenticated with one account credential. The point of these tests is
that a total Bedrock failure now still produces an answer.
"""

import pytest

from backend.leads import bedrock_client as bc


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Isolate from any real credentials and from failover cooldown state."""
    for var in ("BEDROCK_MODEL_CHEAP", "BEDROCK_MODEL_SMART",
                "BEDROCK_FALLBACKS_CHEAP", "BEDROCK_FALLBACKS_SMART",
                "DO_INFERENCE_API_KEY", "DIGITALOCEAN_INFERENCE_KEY",
                "BEDROCK_MAX_RETRIES"):
        monkeypatch.delenv(var, raising=False)
    bc._demoted.clear()
    yield
    bc._demoted.clear()


def _bedrock_fails(monkeypatch, code="ValidationException"):
    """Make every Bedrock call fail the way an expired key does."""
    class _Err(Exception):
        def __init__(self):
            super().__init__("Operation not allowed")
            self.response = {"Error": {"Code": code}}

    def _boom(*_a, **_kw):
        raise _Err()

    monkeypatch.setattr(bc, "_get_runtime_client",
                        lambda: type("C", (), {"converse": staticmethod(_boom)})())


# ---------- chain shape ----------

def test_default_chain_is_one_model_per_provider():
    cheap = bc.models_for_role("cheap")
    smart = bc.models_for_role("smart")

    assert len(cheap) == 2 and len(smart) == 2
    assert bc.provider_of(cheap[0]) == "bedrock"
    assert bc.provider_of(cheap[1]) == "digitalocean"
    assert bc.provider_of(smart[0]) == "bedrock"
    assert bc.provider_of(smart[1]) == "digitalocean"


def test_do_entries_are_recognised_by_prefix():
    assert bc.is_do_model("do:alibaba-qwen3-32b")
    assert not bc.is_do_model("qwen.qwen3-32b-v1:0")
    assert bc.provider_of("do:anything") == "digitalocean"


# ---------- failover ----------

def test_bedrock_failure_falls_through_to_digitalocean(monkeypatch):
    _bedrock_fails(monkeypatch)
    monkeypatch.setenv("DO_INFERENCE_API_KEY", "test-key")

    called = {}

    def _fake_chat(model, system, user, max_tokens=1024, temperature=0.0):
        called["model"] = model
        return "classified", {"inputTokens": 10, "outputTokens": 3, "totalTokens": 13}, 0.2

    monkeypatch.setattr("backend.leads.do_inference_client.chat", _fake_chat)

    text, meta = bc.converse_meta("cheap", "sys", "user")

    assert text == "classified"
    assert meta["provider"] == "digitalocean"
    assert meta["is_fallback"] is True
    # The `do:` prefix is routing metadata and must be stripped before the
    # slug reaches DigitalOcean.
    assert called["model"] == "alibaba-qwen3-32b"


def test_unconfigured_fallback_reports_itself_clearly(monkeypatch):
    """With no DO key the run still fails — but the error must say WHY, not
    look like a model problem."""
    _bedrock_fails(monkeypatch)

    with pytest.raises(bc.BedrockError) as excinfo:
        bc.converse_meta("cheap", "sys", "user")

    message = str(excinfo.value)
    assert "DOFallbackNotConfigured" in message
    assert "ValidationException" in message


def test_bedrock_throttle_retries_before_leaving_the_provider(monkeypatch):
    """A throttle is transient: retry Bedrock, don't burn the fallback."""
    monkeypatch.setenv("DO_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("BEDROCK_MAX_RETRIES", "2")
    monkeypatch.setattr(bc.time, "sleep", lambda *_: None)

    attempts = {"n": 0}

    class _Throttle(Exception):
        def __init__(self):
            super().__init__("slow down")
            self.response = {"Error": {"Code": "ThrottlingException"}}

    def _converse(**_kw):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _Throttle()
        return {
            "output": {"message": {"content": [{"text": "ok"}]}},
            "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
        }

    monkeypatch.setattr(bc, "_get_runtime_client",
                        lambda: type("C", (), {"converse": staticmethod(_converse)})())

    text, meta = bc.converse_meta("cheap", "sys", "user")

    assert text == "ok"
    assert meta["provider"] == "bedrock"
    assert meta["is_fallback"] is False
    assert attempts["n"] == 2


def test_do_throttle_is_retried_not_treated_as_dead(monkeypatch):
    _bedrock_fails(monkeypatch)
    monkeypatch.setenv("DO_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("BEDROCK_MAX_RETRIES", "2")
    monkeypatch.setattr(bc.time, "sleep", lambda *_: None)

    from backend.leads import do_inference_client as do

    calls = {"n": 0}

    def _flaky(model, system, user, max_tokens=1024, temperature=0.0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise do.DOThrottled("429")
        return "recovered", {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2}, 0.1

    monkeypatch.setattr("backend.leads.do_inference_client.chat", _flaky)

    text, meta = bc.converse_meta("cheap", "sys", "user")

    assert text == "recovered"
    assert meta["provider"] == "digitalocean"
    assert calls["n"] == 2


def test_bad_do_key_is_not_retried(monkeypatch):
    """An auth failure will fail identically every time — retrying it just
    delays the error."""
    _bedrock_fails(monkeypatch)
    monkeypatch.setenv("DO_INFERENCE_API_KEY", "bad-key")
    monkeypatch.setenv("BEDROCK_MAX_RETRIES", "3")

    from backend.leads import do_inference_client as do

    calls = {"n": 0}

    def _unauthorised(*_a, **_kw):
        calls["n"] += 1
        raise do.DOAuthError("401")

    monkeypatch.setattr("backend.leads.do_inference_client.chat", _unauthorised)

    with pytest.raises(bc.BedrockError):
        bc.converse_meta("cheap", "sys", "user")

    assert calls["n"] == 1


# ---------- startup validation ----------

def test_validation_survives_dead_bedrock_when_fallback_is_configured(monkeypatch):
    """Bedrock being unreachable must not halt the run when DO can serve —
    otherwise the fallback is useless at startup, which is precisely when the
    expired-key outage was discovered."""
    monkeypatch.setenv("DO_INFERENCE_API_KEY", "test-key")

    def _boom():
        raise RuntimeError("AccessDeniedException: ListFoundationModels")

    monkeypatch.setattr(bc, "_get_control_client",
                        lambda: type("C", (), {"list_foundation_models": staticmethod(_boom)})())

    assert bc.validate_model_access(("cheap",)) == {"cheap": bc.model_for_role("cheap")}


def test_validation_still_fails_when_neither_provider_can_serve(monkeypatch):
    def _boom():
        raise RuntimeError("AccessDeniedException: ListFoundationModels")

    monkeypatch.setattr(bc, "_get_control_client",
                        lambda: type("C", (), {"list_foundation_models": staticmethod(_boom)})())

    with pytest.raises(bc.ModelAccessError) as excinfo:
        bc.validate_model_access(("cheap",))

    assert "DO_INFERENCE_API_KEY" in str(excinfo.value)


def test_config_summary_flags_an_unusable_fallback():
    summary = bc.config_summary()
    assert summary["primary_provider"] == "bedrock"
    assert summary["fallback_provider"] == "digitalocean"
    assert summary["do_fallback_configured"] is False
