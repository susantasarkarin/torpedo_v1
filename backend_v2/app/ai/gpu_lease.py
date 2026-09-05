"""
On-demand GPU leases: rent, serve a local model, run the work, destroy.

**Ported from `backend/infra/gpu_lease.py` (v1), not imported from it.** v1 and v2
run in separate venvs, separate worktrees, separate processes — there is no runtime
path by which v2 could `from infra import gpu_lease` without breaking the isolation
this whole rebuild is built on. The algorithm here is the same one v1 already
proved out (rent-per-job, three-layer teardown, orphan reaping by name prefix); only
the surrounding glue changed — including one real bug this port fixes rather than
carries forward.

**`POD_NAME_PREFIX` is `torpedo-v2-glm`, deliberately distinct from v1's
`torpedo-glm`.** Both codebases may share the same RunPod account and
`RUNPOD_API_KEY` — they're renting from the same provider either way — but
`reap_orphans()` finds pods by name prefix on the whole account. Sharing one prefix
would mean v2's reaper could destroy a live v1 node, or vice versa. Distinct
prefixes make each system's reaper blind to the other's pods by construction.

**Bug found while porting, fixed here rather than carried forward**: v1's version
used `requests` (blocking) and `time.sleep()` in `wait_for_ready`'s poll loop and
`_terminate_hard`'s retry backoff. That's fine called from a synchronous Celery
worker, which is v1's context — but v2 is FastAPI/Motor, fully async, one event loop
per worker. A blocking `time.sleep()` inside a coroutine doesn't just pause that
one call, it freezes every other request that worker is serving — for a cold start,
that's up to 45 minutes of a stalled process. This port uses `httpx.AsyncClient` and
`asyncio.sleep` throughout so provisioning can run inside a request handler without
taking the whole worker down with it.

The CPU side (this VM, or whichever VM runs backend_v2) stays up permanently and
cheaply. A GPU node costs real money per hour and is rented only for the minutes a
job actually needs, then destroyed. The entire risk of this module is a pod that
outlives its job — teardown is defended three times over, because each layer fails
differently:

  1. `finally` in the lease context manager — covers normal exits and exceptions,
     which is almost every real case.
  2. `reap_orphans()` at the start of every lease — covers a crashed process, where
     no `finally` ever ran. Pods are found by name prefix on the account, not from
     local state, because local state is exactly what a dead process loses.
  3. `max_minutes` — a deadline checked while waiting, so a node that never becomes
     healthy is destroyed rather than billed indefinitely.

`RUNPOD_API_KEY` has no default and is read fresh, never baked into a default —
an unset key raises `GpuLeaseError` immediately, refusing to provision rather than
silently no-op'ing. As of this port (2026-09-06), no key is configured anywhere in
this environment — every function here is real and tested against fakes, but
actually renting a node needs that credential supplied first.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger("app.ai.gpu_lease")

POD_NAME_PREFIX = "torpedo-v2-glm"

# RunPod's REST v1 is deprecated and retires 2026-11-15 (per v1's own note on the
# module this was ported from). All request shaping lives in RunPodDriver so a
# migration is one class, not a grep.
DEFAULT_API_BASE = "https://rest.runpod.io/v1"

DEFAULT_IMAGE = "vllm/vllm-openai:latest"
DEFAULT_GPU_TYPE = "NVIDIA H200"
DEFAULT_GPU_COUNT = 8
VLLM_PORT = 8000


class GpuLeaseError(RuntimeError):
    """Provisioning, health-check, or teardown failed."""


class TeardownError(GpuLeaseError):
    """A pod could not be destroyed. Always actionable — it is still billing."""


def api_key() -> str:
    key = (os.getenv("RUNPOD_API_KEY") or "").strip()
    if not key:
        raise GpuLeaseError(
            "RUNPOD_API_KEY not set — refusing to provision. Set it in the "
            "environment of whatever runs backend_v2, not in the repo."
        )
    return key


def api_base() -> str:
    return (os.getenv("RUNPOD_API_BASE") or DEFAULT_API_BASE).rstrip("/")


@dataclass
class Lease:
    """A live GPU node. `base_url` is an OpenAI-compatible /v1 endpoint."""

    pod_id: str
    name: str
    base_url: str
    api_key: str
    model: str
    started_at: float = field(default_factory=time.monotonic)

    @property
    def elapsed_minutes(self) -> float:
        return (time.monotonic() - self.started_at) / 60.0

    def cost_estimate(self, hourly_rate: float) -> float:
        return hourly_rate * (self.elapsed_minutes / 60.0)


class RunPodDriver:
    """Every HTTP call to the provider. Isolated so a provider migration touches
    one class. Async throughout — see the module docstring for why.

    `transport` exists purely for tests — `httpx.MockTransport` lets the test
    suite fake every provider response without a real network call, the same
    "nothing here may reach RunPod" discipline the module this was ported from
    already held."""

    def __init__(self, key: str | None = None, base: str | None = None, timeout: float = 60.0, transport: httpx.BaseTransport | None = None):
        self._key = key or api_key()
        self._base = (base or api_base()).rstrip("/")
        self._timeout = timeout
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self._base}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.request(method, url, headers=self._headers(), json=payload)
        except httpx.HTTPError as e:
            raise GpuLeaseError(f"{method} {path} transport error: {e}") from e

        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise GpuLeaseError(f"{method} {path} failed [{response.status_code}]: {response.text[:300]}")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    async def create_pod(
        self, name: str, image: str, gpu_type: str, gpu_count: int, env: dict[str, str], args: str,
        disk_gb: int, volume_gb: int, network_volume_id: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "name": name, "imageName": image, "gpuTypeIds": [gpu_type], "gpuCount": gpu_count,
            "containerDiskInGb": disk_gb, "volumeInGb": volume_gb, "volumeMountPath": "/workspace",
            "ports": [f"{VLLM_PORT}/http"], "env": env, "dockerStartCmd": ["/bin/bash", "-lc", args],
        }
        if network_volume_id:
            payload["networkVolumeId"] = network_volume_id
            payload.pop("volumeInGb", None)
        data = await self._request("POST", "/pods", payload) or {}
        pod_id = data.get("id") or (data.get("pod") or {}).get("id")
        if not pod_id:
            raise GpuLeaseError(f"provider returned no pod id: {str(data)[:300]}")
        return pod_id

    async def get_pod(self, pod_id: str) -> dict[str, Any] | None:
        return await self._request("GET", f"/pods/{pod_id}")

    async def list_pods(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/pods")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("pods", "data", "items"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    async def terminate_pod(self, pod_id: str) -> None:
        """Idempotent: a pod that is already gone is a success, not an error."""
        await self._request("DELETE", f"/pods/{pod_id}")


def _vllm_command(model: str, served_name: str, gpu_count: int, max_model_len: int) -> str:
    return (
        f"vllm serve {model} --served-model-name {served_name} --tensor-parallel-size {gpu_count} "
        f"--max-model-len {max_model_len} --api-key $VLLM_API_KEY "
        f"--default-chat-template-kwargs '{{\"enable_thinking\": false}}' --host 0.0.0.0 --port {VLLM_PORT}"
    )


def _proxy_url(pod_id: str) -> str:
    return f"https://{pod_id}-{VLLM_PORT}.proxy.runpod.net/v1"


def _pod_age_minutes(pod: dict[str, Any]) -> float | None:
    raw = pod.get("createdAt") or pod.get("created_at")
    if not raw:
        return None
    try:
        created = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created).total_seconds() / 60.0


async def reap_orphans(
    max_age_minutes: float = 120.0, dry_run: bool = False, driver: RunPodDriver | None = None,
    skip_ids: list[str] | None = None,
) -> list[str]:
    """Destroy pods this module created that have outlived any plausible job.
    Only pods whose name carries `POD_NAME_PREFIX` are ever touched."""
    driver = driver or RunPodDriver()
    spared = set(skip_ids or ())
    reaped: list[str] = []
    for pod in await driver.list_pods():
        name = str(pod.get("name") or "")
        if not name.startswith(POD_NAME_PREFIX):
            continue
        pod_id = pod.get("id")
        if not pod_id:
            continue
        if pod_id in spared:
            logger.debug("pod %s is registered as in use; not reaping", pod_id)
            continue
        age = _pod_age_minutes(pod)
        if age is None:
            logger.warning("pod %s (%s) has no readable creation time; leaving it alone", pod_id, name)
            continue
        if age < max_age_minutes:
            continue
        logger.warning("reaping orphaned pod %s (%s), age %.0f min > %.0f", pod_id, name, age, max_age_minutes)
        reaped.append(pod_id)
        if not dry_run:
            try:
                await driver.terminate_pod(pod_id)
            except GpuLeaseError as e:
                logger.error("REAP FAILED for %s — still billing: %s", pod_id, e)
    return reaped


async def wait_for_ready(base_url: str, key: str, deadline: float, poll_seconds: float = 15.0, transport: httpx.BaseTransport | None = None) -> None:
    """Block (this coroutine only, never the event loop) until the model server
    answers, or the deadline passes."""
    last = "no attempt made"
    async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"})
                if response.status_code == 200:
                    logger.info("model server is serving at %s", base_url)
                    return
                last = f"HTTP {response.status_code}"
            except httpx.HTTPError as e:
                last = type(e).__name__
            logger.info("waiting for model server (%s)...", last)
            await asyncio.sleep(poll_seconds)
    raise GpuLeaseError(f"model server did not become ready before the deadline (last: {last})")


@asynccontextmanager
async def lease_gpu(
    model: str = "zai-org/GLM-5.2", served_name: str = "GLM-5.2", gpu_type: str = DEFAULT_GPU_TYPE,
    gpu_count: int = DEFAULT_GPU_COUNT, image: str = DEFAULT_IMAGE, max_minutes: float = 120.0,
    startup_minutes: float = 45.0, max_model_len: int = 131072, disk_gb: int = 200, volume_gb: int = 1000,
    reap_first: bool = True, driver: RunPodDriver | None = None,
) -> AsyncIterator[Lease]:
    """Rent a GPU node, wait for the model to serve, yield it, then destroy it —
    whether the body succeeded, raised, or the process was interrupted."""
    driver = driver or RunPodDriver()
    lease = await provision(
        model=model, served_name=served_name, gpu_type=gpu_type, gpu_count=gpu_count, image=image,
        startup_minutes=startup_minutes, max_model_len=max_model_len, disk_gb=disk_gb, volume_gb=volume_gb,
        reap_first=reap_first, driver=driver,
    )
    try:
        if lease.elapsed_minutes > max_minutes:
            raise GpuLeaseError("startup consumed the whole lease budget")
        yield lease
    finally:
        await _terminate_hard(driver, lease)


async def provision(
    model: str = "zai-org/GLM-5.2", served_name: str = "GLM-5.2", gpu_type: str = DEFAULT_GPU_TYPE,
    gpu_count: int = DEFAULT_GPU_COUNT, image: str = DEFAULT_IMAGE, startup_minutes: float = 45.0,
    max_model_len: int = 131072, disk_gb: int = 200, volume_gb: int = 1000,
    network_volume_id: str | None = None, reap_first: bool = True, driver: RunPodDriver | None = None,
    ready_transport: httpx.BaseTransport | None = None,
) -> Lease:
    """Create a node and block until it serves, WITHOUT arranging teardown.
    `lease_gpu()` is the safe way to use this; this bare form exists for a node
    meant to outlive the process that started it (see `gpu_broker.py`)."""
    driver = driver or RunPodDriver()

    if reap_first:
        try:
            await reap_orphans(driver=driver)
        except GpuLeaseError as e:
            logger.error("orphan sweep failed (continuing): %s", e)

    job_id = uuid.uuid4().hex[:10]
    name = f"{POD_NAME_PREFIX}-{job_id}"
    vllm_key = secrets.token_urlsafe(32)

    logger.info("provisioning %s x%d as %s", gpu_type, gpu_count, name)
    pod_id = await driver.create_pod(
        name=name, image=image, gpu_type=gpu_type, gpu_count=gpu_count,
        env={"VLLM_API_KEY": vllm_key, "HF_HUB_ENABLE_HF_TRANSFER": "1"},
        args=_vllm_command(model, served_name, gpu_count, max_model_len),
        disk_gb=disk_gb, volume_gb=volume_gb, network_volume_id=network_volume_id,
    )

    lease = Lease(pod_id=pod_id, name=name, base_url=_proxy_url(pod_id), api_key=vllm_key, model=served_name)
    logger.info("pod %s created; waiting for model server (cold start ~7 min)", pod_id)

    try:
        await wait_for_ready(lease.base_url, vllm_key, deadline=time.monotonic() + startup_minutes * 60, transport=ready_transport)
    except BaseException:
        await _terminate_hard(driver, lease)
        raise
    return lease


async def destroy(pod_id: str, name: str = "", driver: RunPodDriver | None = None) -> None:
    """Destroy a pod by id, retrying, raising TeardownError if it survives."""
    driver = driver or RunPodDriver()
    await _terminate_hard(driver, Lease(pod_id=pod_id, name=name or pod_id, base_url="", api_key="", model=""))


async def _terminate_hard(driver: RunPodDriver, lease: Lease, attempts: int = 4) -> None:
    """Destroy the pod, retrying, and verify it is actually gone. Runs from a
    `finally`, so it must not mask the exception that sent us here — but silently
    swallowing a failed teardown would leave a billing node with nobody told."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            await driver.terminate_pod(lease.pod_id)
            logger.info("pod %s destroyed after %.1f min", lease.pod_id, lease.elapsed_minutes)
            return
        except GpuLeaseError as e:
            last_error = e
            logger.warning("teardown attempt %d/%d for %s failed: %s", attempt, attempts, lease.pod_id, e)
            if attempt < attempts:
                await asyncio.sleep(min(2**attempt, 15))

    raise TeardownError(
        f"POD {lease.pod_id} ({lease.name}) COULD NOT BE DESTROYED and is still billing. "
        f"Kill it by hand at runpod.io/console/pods or with: "
        f"curl -X DELETE {api_base()}/pods/{lease.pod_id} -H 'Authorization: Bearer $RUNPOD_API_KEY'. "
        f"Last error: {last_error}"
    )
