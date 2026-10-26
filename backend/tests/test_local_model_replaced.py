"""Owner 2026-10-26: with ladder.replace_local_model on, chat_json callers get Haiku/Sonnet, not the 1.5B."""
import pytest

from leads import local_slm_client as slm
from platform_core import ladder


def test_chat_json_goes_to_the_cloud_ladder(monkeypatch):
    monkeypatch.setattr(ladder, "cfg", lambda: {**ladder.DEFAULTS, "replace_local_model": True})
    seen = {}

    def fake_escalate(**kw):
        seen.update(kw)
        return {"type": "client"}, "haiku", [{"tier": "haiku", "status": "ok"}]
    monkeypatch.setattr(ladder, "escalate_json", fake_escalate)
    monkeypatch.setattr(slm, "_call", lambda *a, **k: pytest.fail("local model called"))
    assert slm.chat_json(system="s", user="u", max_tokens=120) == {"type": "client"}
    assert seen["task"] == "legacy:test_local_model_replaced" and seen["max_tokens"] == 300


def test_no_cloud_answer_is_unavailable_like_before(monkeypatch):
    monkeypatch.setattr(ladder, "cfg", lambda: {**ladder.DEFAULTS, "replace_local_model": True})
    monkeypatch.setattr(ladder, "escalate_json", lambda **kw: (None, None, [{"tier": "haiku", "problems": ["budget"]}]))
    with pytest.raises(slm.LocalSLMUnavailable):
        slm.chat_json(system="s", user="u")


def test_every_task_is_cloud_first():
    assert all("qwen" not in t for t in ladder.DEFAULTS["task_tiers"].values())
    assert "qwen" not in ladder.DEFAULTS["default_tiers"]
