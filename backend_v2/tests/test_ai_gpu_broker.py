"""
Slice 11 — AI infrastructure, part 2: `app.ai.gpu_broker`, ported from v1's
`backend/infra/gpu_broker.py` against v2's own async Motor stack (a fake collection
here, not v1's synchronous pymongo one). The bugs worth testing, in the same order
v1's own test suite named them: two processes each provisioning a node, a node
nothing shuts down, a busy node shut down mid-batch, the registry pointing at a pod
that no longer exists. Everything is faked; nothing may reach RunPod or Mongo.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.ai import gpu_broker as gb
from app.ai import gpu_lease as gl


class FakeCollection:
    """Enough Mongo to exercise the claim. `update_one` is deliberately faithful
    about the one thing that matters: it applies the update only when the document
    matches the filter, and reports whether it did — single-flight provisioning
    rests entirely on that being atomic and conditional."""

    def __init__(self):
        self.doc: dict | None = None

    async def find_one(self, query):
        return dict(self.doc) if self.doc else None

    def _matches(self, query):
        if self.doc is None:
            return False
        for key, cond in query.items():
            if key == "_id":
                continue
            if key == "$or":
                if not any(self._matches({**{"_id": 1}, **c}) for c in cond):
                    return False
                continue
            value = self.doc.get(key)
            if isinstance(cond, dict):
                for op, operand in cond.items():
                    if op == "$exists" and (key in self.doc) != operand:
                        return False
                    if op == "$nin" and value in operand:
                        return False
                    if op == "$lt" and not (value is not None and value < operand):
                        return False
            elif value != cond:
                return False
        return True

    async def update_one(self, query, update, upsert=False):
        class Result:
            def __init__(self, modified=0, upserted=None):
                self.modified_count = modified
                self.upserted_id = upserted

        if self._matches(query):
            self.doc.update(update.get("$set", {}))
            for key, delta in update.get("$inc", {}).items():
                self.doc[key] = self.doc.get(key, 0) + delta
            return Result(modified=1)
        if self.doc is None and upsert:
            self.doc = {"_id": gb.REGISTRY_ID, **update.get("$set", {})}
            for key, delta in update.get("$inc", {}).items():
                self.doc[key] = delta
            return Result(upserted=gb.REGISTRY_ID)
        return Result()

    async def delete_one(self, query):
        if self._matches(query):
            self.doc = None


@pytest.fixture(autouse=True)
def _broker_enabled(monkeypatch):
    monkeypatch.setenv("GPU_BROKER_ENABLED", "true")


@pytest.fixture
def broker() -> gb.GpuBroker:
    return gb.GpuBroker(FakeCollection())


def _healthy_transport() -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}))


def _unhealthy_transport() -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(500))


@pytest.mark.asyncio
async def test_acquire_refuses_when_broker_disabled(monkeypatch, broker):
    monkeypatch.delenv("GPU_BROKER_ENABLED", raising=False)
    with pytest.raises(gl.GpuLeaseError):
        await broker.acquire(wait=False)


@pytest.mark.asyncio
async def test_single_flight_second_caller_does_not_provision_too(monkeypatch, broker):
    """The load-bearing invariant: many workers waking to the same need must
    produce one node, not many."""
    provision_calls = []

    async def fake_provision(**kwargs):
        provision_calls.append(kwargs)
        return gl.Lease(pod_id="pod-1", name="n", base_url="https://fake/v1", api_key="k", model="GLM-5.2")

    monkeypatch.setattr(gb, "_provision", fake_provision)

    first_claim = await broker._claim_start()
    assert first_claim is True

    second_claim = await broker._claim_start()
    assert second_claim is False  # already claimed by "another process"

    with pytest.raises(gb.GpuNotReady):
        await broker.acquire(wait=False)
    assert provision_calls == []  # acquire() never called provision — the claim already existed


@pytest.mark.asyncio
async def test_acquire_provisions_and_publishes_when_nothing_registered(monkeypatch, broker):
    async def fake_provision(**kwargs):
        return gl.Lease(pod_id="pod-1", name="torpedo-v2-glm-1", base_url="https://fake/v1", api_key="k", model="GLM-5.2")

    monkeypatch.setattr(gb, "_provision", fake_provision)

    endpoint = await broker.acquire(wait=False)
    assert endpoint.pod_id == "pod-1"

    doc = await broker.current()
    assert doc["state"] == gb.STATE_READY


@pytest.mark.asyncio
async def test_acquire_returns_existing_healthy_node_without_reprovisioning(monkeypatch):
    broker = gb.GpuBroker(FakeCollection(), health_check_transport=_healthy_transport())
    provision_calls = []

    async def fake_provision(**kwargs):
        provision_calls.append(kwargs)
        raise AssertionError("must not re-provision a healthy registered node")

    monkeypatch.setattr(gb, "_provision", fake_provision)

    await broker._publish(gl.Lease(pod_id="pod-1", name="n", base_url="https://fake/v1", api_key="k", model="GLM-5.2"))

    endpoint = await broker.acquire(wait=False)
    assert endpoint.pod_id == "pod-1"
    assert provision_calls == []


@pytest.mark.asyncio
async def test_acquire_replaces_a_registered_but_unhealthy_node(monkeypatch):
    """'A registry entry is a claim, not proof' — the node itself is asked, not
    just the document."""
    broker = gb.GpuBroker(FakeCollection(), health_check_transport=_unhealthy_transport())
    destroyed = []

    async def fake_destroy(pod_id, name=""):
        destroyed.append(pod_id)

    async def fake_provision(**kwargs):
        return gl.Lease(pod_id="pod-2", name="n2", base_url="https://fake/v1", api_key="k2", model="GLM-5.2")

    monkeypatch.setattr(gb, "_destroy_pod", fake_destroy)
    monkeypatch.setattr(gb, "_provision", fake_provision)

    await broker._publish(gl.Lease(pod_id="pod-1", name="n1", base_url="https://fake/v1", api_key="k", model="GLM-5.2"))

    endpoint = await broker.acquire(wait=False)
    assert endpoint.pod_id == "pod-2"
    assert destroyed == ["pod-1"]


@pytest.mark.asyncio
async def test_touch_does_not_resurrect_a_replaced_nodes_clock(broker):
    await broker._publish(gl.Lease(pod_id="pod-1", name="n", base_url="https://fake/v1", api_key="k", model="GLM-5.2"))
    doc_before = await broker.current()

    await broker.touch(pod_id="some-other-pod-id")  # not the currently registered pod

    doc_after = await broker.current()
    assert doc_after["last_used_at"] == doc_before["last_used_at"]


@pytest.mark.asyncio
async def test_sweep_shuts_down_an_idle_node(monkeypatch, broker):
    destroyed = []

    async def fake_destroy(pod_id, name=""):
        destroyed.append(pod_id)

    async def fake_reap(**kwargs):
        return []

    monkeypatch.setattr(gb, "_destroy_pod", fake_destroy)
    monkeypatch.setattr(gb, "reap_orphans", fake_reap)
    monkeypatch.setenv("GPU_IDLE_MINUTES", "10")

    lease = gl.Lease(pod_id="pod-1", name="n", base_url="https://fake/v1", api_key="k", model="GLM-5.2")
    await broker._publish(lease)
    # Force last_used_at far enough in the past to be idle.
    broker._collection.doc["last_used_at"] = datetime.now(timezone.utc) - timedelta(minutes=20)

    outcome = await broker.sweep()
    assert outcome["action"] == "idle"
    assert destroyed == ["pod-1"]


@pytest.mark.asyncio
async def test_sweep_never_shuts_down_a_busy_node_mid_batch(monkeypatch, broker):
    destroyed = []

    async def fake_destroy(pod_id, name=""):
        destroyed.append(pod_id)

    async def fake_reap(**kwargs):
        return []

    monkeypatch.setattr(gb, "_destroy_pod", fake_destroy)
    monkeypatch.setattr(gb, "reap_orphans", fake_reap)
    monkeypatch.setenv("GPU_IDLE_MINUTES", "10")

    lease = gl.Lease(pod_id="pod-1", name="n", base_url="https://fake/v1", api_key="k", model="GLM-5.2")
    await broker._publish(lease)
    await broker.touch(pod_id="pod-1")  # just used — recent

    outcome = await broker.sweep()
    assert outcome["action"] == "none"
    assert destroyed == []


@pytest.mark.asyncio
async def test_sweep_enforces_the_max_lifetime_ceiling_even_while_starting(monkeypatch, broker):
    destroyed = []

    async def fake_destroy(pod_id, name=""):
        destroyed.append(pod_id)

    async def fake_reap(**kwargs):
        return []

    monkeypatch.setattr(gb, "_destroy_pod", fake_destroy)
    monkeypatch.setattr(gb, "reap_orphans", fake_reap)
    monkeypatch.setenv("GPU_MAX_LIFETIME_MINUTES", "60")

    await broker._claim_start()
    broker._collection.doc["pod_id"] = "pod-stuck"
    broker._collection.doc["started_at"] = datetime.now(timezone.utc) - timedelta(minutes=120)

    outcome = await broker.sweep()
    assert outcome["action"] == "over-max-lifetime"
    assert destroyed == ["pod-stuck"]


@pytest.mark.asyncio
async def test_shutdown_now_is_a_real_kill_switch(monkeypatch, broker):
    destroyed = []

    async def fake_destroy(pod_id, name=""):
        destroyed.append(pod_id)

    monkeypatch.setattr(gb, "_destroy_pod", fake_destroy)

    await broker._publish(gl.Lease(pod_id="pod-1", name="n", base_url="https://fake/v1", api_key="k", model="GLM-5.2"))
    outcome = await broker.shutdown_now()

    assert outcome == {"action": "destroyed", "pod_id": "pod-1"}
    assert destroyed == ["pod-1"]
    assert await broker.current() is None


@pytest.mark.asyncio
async def test_status_reports_cost_estimate(broker):
    lease = gl.Lease(pod_id="pod-1", name="n", base_url="https://fake/v1", api_key="k", model="GLM-5.2")
    await broker._publish(lease)
    broker._collection.doc["started_at"] = datetime.now(timezone.utc) - timedelta(minutes=30)

    status = await broker.status()
    assert status["state"] == gb.STATE_READY
    assert status["cost_so_far"] is not None
    assert status["up_minutes"] == pytest.approx(30.0, abs=0.5)
