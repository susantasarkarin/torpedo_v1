"""
Bedrock Converse retry and failover behaviour (leads/bedrock_client.py).

The DigitalOcean and self-hosted fallbacks were removed 2026-11-15; these tests
cover what remains: transient throttles retry on the same model, and startup
validation fails fast when Bedrock cannot list models.
"""

import pytest

# Import by the SAME path production uses (backend/ as cwd, so `leads` is
# top-level).
from leads import bedrock_client as bc


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Isolate from any real credentials and from failover cooldown state."""
    for var in ("BEDROCK_MODEL_CHEAP", "BEDROCK_MODEL_SMART",
                "BEDROCK_FALLBACKS_CHEAP", "BEDROCK_FALLBACKS_SMART",
                "BEDROCK_MAX_RETRIES"):
        monkeypatch.delenv(var, raising=False)
    bc._demoted.clear()
    yield
    bc._demoted.clear()


# ---------- retry ----------

def test_bedrock_throttle_retries_before_leaving_the_provider(monkeypatch):
    """A throttle is transient: retry the same model, don't fail over."""
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


# ---------- startup validation ----------

def test_validation_still_fails_when_bedrock_cannot_list_models(monkeypatch):
    def _boom():
        raise RuntimeError("AccessDeniedException: ListFoundationModels")

    monkeypatch.setattr(bc, "_get_control_client",
                        lambda: type("C", (), {"list_foundation_models": staticmethod(_boom)})())

    with pytest.raises(bc.ModelAccessError) as excinfo:
        bc.validate_model_access(("cheap",))

    assert "AccessDeniedException" in str(excinfo.value)
