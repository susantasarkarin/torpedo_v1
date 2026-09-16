"""
LOCAL SLM CONCURRENCY, TIMEOUT, RETRY AND SECURITY TESTS
=========================================================

Covers the fix for the 2026-09-16 incident: routing v1's "cheap" role to the
local Qwen2.5-0.5B (torpedo-v2-llm.service, --parallel 1) with no admission
control let concurrent Celery worker processes overload it, pushing VM load
average to ~107. These tests guard the fix -- a cross-process Redis-backed
concurrency gate (max 1 by default), a queue timeout separate from the
inference timeout, and retry classification that fails over instead of
hammering the same overloaded instance.

Uses fakeredis (in-memory, no live Redis needed) -- consistent with this
codebase's convention of mocking the transport/infrastructure, not depending
on it being live. Real Redis semantics (WATCH/MULTI/BLPOP) are standard core
commands fakeredis implements faithfully; only EVAL/Lua isn't supported by the
installed version, which is why local_llm_gate.py's seeding uses a WATCH/MULTI
transaction instead of a Lua script.

Bedrock/smart-role behavior is untouched by this work -- see the "config"
section below for the structural assertions proving that, and
test_outreach_send_caps.py for the existing outreach/kill-switch coverage
this must not regress.
"""

import contextlib
import time

import fakeredis
import pytest


# ============================================
# CONFIG: smart role untouched, cheap role local-only
# ============================================

def test_smart_role_never_resolves_to_local(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_SMART", raising=False)
    monkeypatch.delenv("BEDROCK_FALLBACKS_SMART", raising=False)
    from leads import bedrock_client as bc
    chain = bc.models_for_role("smart")
    assert not any(m.startswith("local:") for m in chain)


def test_cheap_role_can_be_local_only(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_CHEAP", "local:qwen2.5-0.5b-instruct")
    monkeypatch.setenv("BEDROCK_FALLBACKS_CHEAP", "")  # explicitly empty: no Bedrock/DO fallback
    from leads import bedrock_client as bc
    assert bc.models_for_role("cheap") == ["local:qwen2.5-0.5b-instruct"]


def test_only_one_local_model_configured(monkeypatch):
    # The chain resolves whatever BEDROCK_MODEL_CHEAP names -- this asserts
    # the *intended* production value is the one model this work is scoped
    # to, not a stand-in for "any local model is fine."
    monkeypatch.setenv("BEDROCK_MODEL_CHEAP", "local:qwen2.5-0.5b-instruct")
    monkeypatch.setenv("BEDROCK_FALLBACKS_CHEAP", "")
    from leads import bedrock_client as bc
    chain = bc.models_for_role("cheap")
    assert chain == ["local:qwen2.5-0.5b-instruct"]
    assert not any("qwen3" in m or "32b" in m for m in chain if m.startswith("local:"))


# ============================================
# GATE: concurrency, queue timeout
# ============================================

@pytest.fixture
def gate(monkeypatch):
    """Point the gate at an isolated fakeredis instance instead of real Redis."""
    from leads import local_llm_gate
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(local_llm_gate, "_client", fake)
    monkeypatch.setattr(local_llm_gate, "_get_client", lambda: fake)
    yield local_llm_gate
    fake.flushall()


def test_max_concurrency_defaults_to_one(monkeypatch, gate):
    monkeypatch.delenv("LOCAL_LLM_MAX_CONCURRENCY", raising=False)
    assert gate.max_concurrency() == 1


def test_second_caller_blocks_while_first_holds_the_slot(monkeypatch, gate):
    monkeypatch.setenv("LOCAL_LLM_MAX_CONCURRENCY", "1")
    with gate.acquire_local_llm_slot(timeout=5):
        # Capacity is 1 and already held -- a second acquire must wait, not
        # succeed immediately. Use a short timeout so the test itself is fast;
        # it proves blocking, not the full default queue timeout.
        t0 = time.monotonic()
        with pytest.raises(gate.LocalLLMQueueTimeout):
            with gate.acquire_local_llm_slot(timeout=0.5):
                pass
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.4  # actually waited, didn't fail instantly


def test_slot_is_released_after_use(monkeypatch, gate):
    monkeypatch.setenv("LOCAL_LLM_MAX_CONCURRENCY", "1")
    with gate.acquire_local_llm_slot(timeout=1):
        pass
    # Must be immediately available again -- no leak.
    t0 = time.monotonic()
    with gate.acquire_local_llm_slot(timeout=1):
        elapsed = time.monotonic() - t0
    assert elapsed < 0.5


def test_slot_is_released_even_on_exception(monkeypatch, gate):
    monkeypatch.setenv("LOCAL_LLM_MAX_CONCURRENCY", "1")
    with pytest.raises(ValueError):
        with gate.acquire_local_llm_slot(timeout=1):
            raise ValueError("caller blew up mid-inference")
    # A crash inside the `with` block must not leak the gate closed forever.
    t0 = time.monotonic()
    with gate.acquire_local_llm_slot(timeout=1):
        elapsed = time.monotonic() - t0
    assert elapsed < 0.5


def test_queue_timeout_raises_specific_exception_not_a_hang(monkeypatch, gate):
    monkeypatch.setenv("LOCAL_LLM_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("LOCAL_LLM_QUEUE_TIMEOUT_SECONDS", "0.3")
    with gate.acquire_local_llm_slot():
        t0 = time.monotonic()
        with pytest.raises(gate.LocalLLMQueueTimeout):
            with gate.acquire_local_llm_slot():
                pass
        elapsed = time.monotonic() - t0
        # Bounded by the configured queue timeout, not the default 5s or a hang.
        assert elapsed < 1.5


def test_reseeding_shrinks_capacity_if_lowered(monkeypatch, gate):
    monkeypatch.setenv("LOCAL_LLM_MAX_CONCURRENCY", "3")
    gate._ensure_seeded(gate._get_client(), 3)
    assert gate._get_client().llen(gate._GATE_KEY) == 3
    gate._ensure_seeded(gate._get_client(), 1)
    assert gate._get_client().llen(gate._GATE_KEY) == 1


# ============================================
# INFERENCE TIMEOUT vs QUEUE TIMEOUT (distinct failure modes)
# ============================================

def test_inference_timeout_is_separate_from_queue_timeout(monkeypatch, gate):
    """A slow backend (not a busy gate) must trigger the INFERENCE timeout,
    and the caller must be able to tell the two apart -- they're different
    problems (server too busy to even start vs. server hung mid-response)."""
    monkeypatch.setenv("SELF_HOSTED_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("SELF_HOSTED_API_KEY", "test-key-not-a-real-secret")
    monkeypatch.setenv("LOCAL_LLM_INFERENCE_TIMEOUT_SECONDS", "0.3")
    monkeypatch.setenv("LOCAL_LLM_MAX_CONCURRENCY", "1")

    from leads import bedrock_client as bc, do_inference_client as oai

    def _slow_chat(*a, timeout=None, **kw):
        # Mocking do_inference_client.chat() wholesale bypasses its own
        # requests.post(timeout=...) enforcement -- simulate that enforcement
        # explicitly instead of actually sleeping for real in a unit test.
        if timeout is not None and timeout < 1.0:
            raise oai.DOThrottled(f"local inference timed out after {timeout}s")
        return "too slow", {}, 2.0

    monkeypatch.setattr(oai, "chat", _slow_chat)

    t0 = time.monotonic()
    with pytest.raises(bc.LocalLLMUnavailable) as exc:
        bc._call_self_hosted("local:qwen2.5-0.5b-instruct", "s", "u", 10, 0.0)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.5  # bounded by the 0.3s inference timeout, not the 2s sleep
    assert "inference" in str(exc.value).lower()


# ============================================
# RETRY CLASSIFICATION: fail over, never retry the same overloaded instance
# ============================================

def test_local_llm_unavailable_is_failover_not_retryable():
    from leads import bedrock_client as bc
    assert "LocalLLMUnavailable" in bc._FAILOVER_CODES
    assert "LocalLLMUnavailable" not in bc._RETRYABLE_CODES


def test_queue_timeout_fails_over_without_sleeping(monkeypatch, gate):
    """converse_meta()'s retry loop must not time.sleep()-and-retry the SAME
    local model on a queue timeout -- that's the exact storm that caused the
    incident. It should move to the next chain entry (or exhaust immediately
    if local is the only entry) with no backoff sleep."""
    monkeypatch.setenv("BEDROCK_MODEL_CHEAP", "local:qwen2.5-0.5b-instruct")
    monkeypatch.setenv("BEDROCK_FALLBACKS_CHEAP", "")
    monkeypatch.setenv("SELF_HOSTED_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LOCAL_LLM_MAX_CONCURRENCY", "1")

    from leads import bedrock_client as bc

    # A spy, not a no-op stub: fakeredis's own BLPOP polls internally using
    # time.sleep, so replacing it with something that never actually pauses
    # turns that poll into a busy-spin instead of a bounded wait. Record
    # calls but still delegate to a (much shorter) real sleep.
    slept = []
    _real_sleep = time.sleep

    def _spy_sleep(seconds):
        slept.append(seconds)
        _real_sleep(min(seconds, 0.01))

    monkeypatch.setattr(time, "sleep", _spy_sleep)

    # Hold the only slot for the whole test, forcing every acquire to time out.
    with gate.acquire_local_llm_slot(timeout=5):
        monkeypatch.setenv("LOCAL_LLM_QUEUE_TIMEOUT_SECONDS", "0.2")
        with pytest.raises(bc.BedrockError):
            bc.converse("cheap", "s", "u", max_tokens=10)

    # fakeredis's own BLPOP polls internally at a fixed ~0.5s granularity --
    # expected infrastructure noise, not a retry. What must NOT appear is a
    # bedrock_client backoff sleep (2**(attempt-1): 1s, 2s, 4s...) against
    # the same overloaded local model -- those start at 1.0s, well clear of
    # fakeredis's own polling tick.
    assert all(s < 0.9 for s in slept), f"a backoff-shaped sleep occurred: {slept}"


# ============================================
# SECURITY: the API key never leaks into logs/exceptions
# ============================================

def test_api_key_never_appears_in_failure_exception(monkeypatch, gate):
    secret = "sk-totally-fake-test-value-do-not-use-1234567890"
    monkeypatch.setenv("SELF_HOSTED_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("SELF_HOSTED_API_KEY", secret)
    monkeypatch.setenv("LOCAL_LLM_INFERENCE_TIMEOUT_SECONDS", "0.2")

    from leads import bedrock_client as bc, do_inference_client as oai

    def _boom(*a, **kw):
        raise oai.DOInferenceError(f"transport error calling {kw.get('base_url')}")

    monkeypatch.setattr(oai, "chat", _boom)

    with pytest.raises(bc.LocalLLMUnavailable) as exc:
        bc._call_self_hosted("local:qwen2.5-0.5b-instruct", "s", "u", 10, 0.0)

    assert secret not in str(exc.value)
    assert secret not in repr(exc.value)
