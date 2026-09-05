"""
Slice 11 — `app.ai.llm.GpuBrokerLLMProvider`: the fifth Protocol-boundary
implementation in this codebase, tested the same way as the other four — real
behavior, faked transport, no network call.
"""

import httpx
import pytest

from app.ai import gpu_broker as gb
from app.ai import gpu_lease as gl
from app.ai.llm import GpuBrokerLLMProvider, LLMUnavailable

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
