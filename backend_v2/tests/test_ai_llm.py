"""
Slice 11 — `app.ai.llm.GpuBrokerLLMProvider`: the fifth Protocol-boundary
implementation in this codebase, tested the same way as the other four — real
behavior, faked transport, no network call.
"""

import httpx
import pytest

from app.ai import gpu_broker as gb
from app.ai import gpu_lease as gl
from app.ai.llm import GpuBrokerLLMProvider, LLMUnavailable, LocalLlamaCppProvider, get_llm_provider

ORG = "org-A"


class FakeCollection:
    def __init__(self):
        self.doc = None

    async def find_one(self, query):
        return dict(self.doc) if self.doc else None

    async def update_one(self, query, update, upsert=False):
        class Result:
            modified_count = 1
            upserted_id = None

        if self.doc is None and upsert:
            self.doc = {"_id": gb.REGISTRY_ID, **update.get("$set", {})}
            for key, delta in update.get("$inc", {}).items():
                self.doc[key] = delta
            return Result()
        self.doc.update(update.get("$set", {}))
        for key, delta in update.get("$inc", {}).items():
            self.doc[key] = self.doc.get(key, 0) + delta
        return Result()

    async def delete_one(self, query):
        self.doc = None


@pytest.fixture(autouse=True)
def _broker_enabled(monkeypatch):
    monkeypatch.setenv("GPU_BROKER_ENABLED", "true")


async def _ready_broker() -> gb.GpuBroker:
    broker = gb.GpuBroker(FakeCollection(), health_check_transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []})))
    await broker._publish(gl.Lease(pod_id="pod-1", name="n", base_url="https://fake/v1", api_key="k", model="GLM-5.2"))
    return broker


@pytest.mark.asyncio
async def test_chat_returns_content_and_touches_the_broker():
    broker = await _ready_broker()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    provider = GpuBrokerLLMProvider(broker, transport=httpx.MockTransport(handler))
    doc_before_calls = broker._collection.doc.get("calls", 0)

    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "hello"
    assert response.model == "GLM-5.2"
    assert broker._collection.doc["calls"] == doc_before_calls + 1  # touch() ran


@pytest.mark.asyncio
async def test_chat_raises_llm_unavailable_when_broker_disabled(monkeypatch):
    monkeypatch.delenv("GPU_BROKER_ENABLED", raising=False)
    broker = gb.GpuBroker(FakeCollection())
    provider = GpuBrokerLLMProvider(broker)

    with pytest.raises(LLMUnavailable):
        await provider.chat(messages=[{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_raises_llm_unavailable_on_malformed_model_response():
    broker = await _ready_broker()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    provider = GpuBrokerLLMProvider(broker, transport=httpx.MockTransport(handler))
    with pytest.raises(LLMUnavailable):
        await provider.chat(messages=[{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_raises_llm_unavailable_on_transport_error():
    broker = await _ready_broker()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = GpuBrokerLLMProvider(broker, transport=httpx.MockTransport(handler))
    with pytest.raises(LLMUnavailable):
        await provider.chat(messages=[{"role": "user", "content": "hi"}])


# --------------------------------------------------------------------------- LocalLlamaCppProvider
# The always-on, self-owned inference path — no lease, no broker, no idle timer.
# Same fake-transport discipline as GpuBrokerLLMProvider above: real behavior,
# no network call in the unit suite. The genuine, non-mocked local model is
# exercised separately (see docs/LOCAL_LLM_RUNBOOK.md's live-verification test).


@pytest.mark.asyncio
async def test_local_provider_returns_content_and_usage():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "hello"}}], "model": "qwen2.5-0.5b-instruct",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    provider = LocalLlamaCppProvider(base_url="http://127.0.0.1:8003/v1", model="qwen2.5-0.5b-instruct", api_key="k", transport=httpx.MockTransport(handler))
    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "hello"
    assert response.model == "qwen2.5-0.5b-instruct"
    assert response.prompt_tokens == 10
    assert response.total_tokens == 15


@pytest.mark.asyncio
async def test_local_provider_sends_the_api_key_as_a_bearer_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = LocalLlamaCppProvider(base_url="http://127.0.0.1:8003/v1", model="m", api_key="secret-key", transport=httpx.MockTransport(handler))
    await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert seen["auth"] == "Bearer secret-key"


@pytest.mark.asyncio
async def test_local_provider_works_without_an_api_key():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = LocalLlamaCppProvider(base_url="http://127.0.0.1:8003/v1", model="m", transport=httpx.MockTransport(handler))
    response = await provider.chat(messages=[{"role": "user", "content": "hi"}])
    assert response.content == "ok"


@pytest.mark.asyncio
async def test_local_provider_raises_llm_unavailable_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = LocalLlamaCppProvider(base_url="http://127.0.0.1:8003/v1", model="m", transport=httpx.MockTransport(handler))
    with pytest.raises(LLMUnavailable):
        await provider.chat(messages=[{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_local_provider_raises_llm_unavailable_on_malformed_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    provider = LocalLlamaCppProvider(base_url="http://127.0.0.1:8003/v1", model="m", transport=httpx.MockTransport(handler))
    with pytest.raises(LLMUnavailable):
        await provider.chat(messages=[{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_local_provider_raises_llm_unavailable_on_http_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal"})

    provider = LocalLlamaCppProvider(base_url="http://127.0.0.1:8003/v1", model="m", transport=httpx.MockTransport(handler))
    with pytest.raises(LLMUnavailable):
        await provider.chat(messages=[{"role": "user", "content": "hi"}])


# --------------------------------------------------------------------------- get_llm_provider() selection


def test_get_llm_provider_prefers_local_when_configured(monkeypatch):
    from app.config import Settings

    fake_settings = Settings(mongo_uri="mongodb://x", mongo_db_name="x", local_llm_base_url="http://127.0.0.1:8003/v1", local_llm_api_key="k", local_llm_model_name="qwen2.5-0.5b-instruct")
    monkeypatch.setattr("app.config.get_settings", lambda: fake_settings)

    provider = get_llm_provider(db={"ai_gpu_leases": None})
    assert isinstance(provider, LocalLlamaCppProvider)


def test_get_llm_provider_falls_back_to_the_runpod_broker_when_local_is_not_configured(monkeypatch):
    from app.config import Settings

    fake_settings = Settings(mongo_uri="mongodb://x", mongo_db_name="x", local_llm_base_url=None)
    monkeypatch.setattr("app.config.get_settings", lambda: fake_settings)

    provider = get_llm_provider(db={"ai_gpu_leases": FakeCollection()})
    assert isinstance(provider, GpuBrokerLLMProvider)
