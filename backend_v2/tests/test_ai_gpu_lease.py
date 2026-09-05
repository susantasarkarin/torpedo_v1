"""
Slice 11 — AI infrastructure, part 1: `app.ai.gpu_lease`, ported from v1's
`backend/infra/gpu_lease.py` (fixing a real bug found during the port: v1's
`time.sleep()` polling would freeze a whole async worker for the length of a cold
start). Everything here is faked — nothing may reach RunPod over the network, the
same discipline v1's own test suite for this module already held.
"""

import time

import httpx
import pytest

from app.ai import gpu_lease as gl


@pytest.fixture(autouse=True)
def _fake_api_key(monkeypatch):
    monkeypatch.setenv("RUNPOD_API_KEY", "fake-key-for-tests")


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_api_key_missing_raises(monkeypatch):
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    with pytest.raises(gl.GpuLeaseError):
        gl.api_key()


@pytest.mark.asyncio
async def test_create_pod_returns_pod_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(200, json={"id": "pod-1"})

    driver = gl.RunPodDriver(transport=_transport(handler))
    pod_id = await driver.create_pod(name="torpedo-v2-glm-x", image="img", gpu_type="H200", gpu_count=1, env={}, args="run", disk_gb=1, volume_gb=1)
    assert pod_id == "pod-1"


@pytest.mark.asyncio
async def test_create_pod_missing_id_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    driver = gl.RunPodDriver(transport=_transport(handler))
    with pytest.raises(gl.GpuLeaseError):
        await driver.create_pod(name="x", image="img", gpu_type="H200", gpu_count=1, env={}, args="run", disk_gb=1, volume_gb=1)


@pytest.mark.asyncio
async def test_terminate_pod_is_idempotent_on_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    driver = gl.RunPodDriver(transport=_transport(handler))
    await driver.terminate_pod("already-gone")  # must not raise


@pytest.mark.asyncio
async def test_reap_orphans_only_touches_prefixed_old_pods():
    old_ts = "2020-01-01T00:00:00Z"
    pods = [
        {"id": "ours-old", "name": f"{gl.POD_NAME_PREFIX}-a", "createdAt": old_ts},
        {"id": "ours-new", "name": f"{gl.POD_NAME_PREFIX}-b", "createdAt": _iso_now()},
        {"id": "not-ours", "name": "someone-elses-pod", "createdAt": old_ts},
    ]
    terminated: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/pods"):
            return httpx.Response(200, json=pods)
        if request.method == "DELETE":
            terminated.append(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    driver = gl.RunPodDriver(transport=_transport(handler))
    reaped = await gl.reap_orphans(max_age_minutes=120.0, driver=driver)

    assert reaped == ["ours-old"]
    assert terminated == ["ours-old"]


@pytest.mark.asyncio
async def test_reap_orphans_spares_registered_ids():
    old_ts = "2020-01-01T00:00:00Z"
    pods = [{"id": "in-use", "name": f"{gl.POD_NAME_PREFIX}-a", "createdAt": old_ts}]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=pods)
        raise AssertionError("should never terminate a spared pod")

    driver = gl.RunPodDriver(transport=_transport(handler))
    reaped = await gl.reap_orphans(max_age_minutes=120.0, driver=driver, skip_ids=["in-use"])
    assert reaped == []


@pytest.mark.asyncio
async def test_reap_orphans_dry_run_does_not_terminate():
    old_ts = "2020-01-01T00:00:00Z"
    pods = [{"id": "would-reap", "name": f"{gl.POD_NAME_PREFIX}-a", "createdAt": old_ts}]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=pods)
        raise AssertionError("dry_run must never call DELETE")

    driver = gl.RunPodDriver(transport=_transport(handler))
    reaped = await gl.reap_orphans(max_age_minutes=120.0, dry_run=True, driver=driver)
    assert reaped == ["would-reap"]


@pytest.mark.asyncio
async def test_wait_for_ready_succeeds_once_model_responds():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    await gl.wait_for_ready("https://fake/v1", "key", deadline=time.monotonic() + 5, transport=_transport(handler))


@pytest.mark.asyncio
async def test_wait_for_ready_raises_once_deadline_has_passed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(gl.GpuLeaseError):
        await gl.wait_for_ready("https://fake/v1", "key", deadline=time.monotonic() - 1, transport=_transport(handler))


@pytest.mark.asyncio
async def test_terminate_hard_retries_then_raises_teardown_error(monkeypatch):
    async def instant_sleep(_seconds):
        return None

    monkeypatch.setattr(gl.asyncio, "sleep", instant_sleep)

    class AlwaysFailsDriver:
        async def terminate_pod(self, pod_id):
            raise gl.GpuLeaseError("provider is down")

    lease = gl.Lease(pod_id="p1", name="n1", base_url="", api_key="", model="")
    with pytest.raises(gl.TeardownError):
        await gl._terminate_hard(AlwaysFailsDriver(), lease, attempts=2)


def _iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
