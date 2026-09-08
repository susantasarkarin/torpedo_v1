"""
One shared GPU node, brokered across every process in backend_v2 that needs AI.

**Ported from `backend/infra/gpu_broker.py` (v1)** — same reasoning as
`gpu_lease.py`'s port: separate venvs/processes rule out a direct import, so the
registry-based single-flight/idle-sweep design is re-implemented here against v2's
own async Motor stack rather than v1's synchronous pymongo one.

`gpu_lease.lease_gpu()` rents a GPU for one job, inside one `with` block, in one
process — the right shape for a one-off batch, the wrong shape for a FastAPI worker
answering requests: if every worker leased its own node, backend_v2 would pay for
several nodes at once and eat a multi-minute cold start per worker. So the node
lives in Mongo instead of in a process: `ai_gpu_leases` (this codebase's own
collection, not v1's `torpedo_settings.gpu_leases` — kept separate deliberately, so
v2's isolation from v1 holds even for this shared-infrastructure concept; the
tradeoff is that v1 and v2 could each rent their own node if both are ever enabled
at once, accepted explicitly here rather than reached for a cross-codebase share).

**Deliberate, narrow exception to "every write goes through `CanonicalRepository`"
(I-6)**, same shape as `app.outreach.budget.BudgetService` and
`app.finance.sequence.SequenceService`: this registry document is operational
infrastructure state, not a business entity with an audit trail, and single-flight
provisioning needs a conditional atomic `update_one` `CanonicalRepository.update()`'s
version-guard can't express (there is no prior version to guard against — the whole
point is deciding whether a claim already exists).

Three things here are load-bearing, each guarding a different way to lose money or
correctness:

  1. **Single-flight provisioning.** Many FastAPI workers waking to the same need
     must produce one node, not many. The winner is decided by an atomic
     conditional update on the registry document, not by a lock the application
     holds, because the process holding it can die mid-start.
  2. **Idle shutdown driven by `last_used_at`, not by age.** A shared node is
     legitimately older than any single job, so `gpu_lease.reap_orphans()`'s age
     rule would kill a busy node. `sweep()` is the primary reaper and uses
     idleness; age survives only as an absolute ceiling.
  3. **A registry entry is a claim, not proof.** Every state here is reconciled
     against the provider before it is trusted, because the failure that costs
     real money is a document saying "no node" while a node bills on.

`acquire(wait=False)` is the form request handlers should use: it raises
`GpuNotReady` rather than blocking on a cold start. The caller should queue the
work and answer the caller — Phase 14's scheduler (built 2026-09-06,
`app.scheduler.orchestrator.EventOrchestrator`) is that drain, one level up:
`app.ai.llm.GpuBrokerLLMProvider.chat()` already catches `GpuLeaseError`
(`GpuNotReady`'s parent) and re-raises as `LLMUnavailable`, which the
orchestrator's recoverable-error set does retry — records it on the `Event`,
picks it back up next tick once the node is ready. No separate queue built;
`GpuNotReady` itself never has to reach the orchestrator directly.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from motor.motor_asyncio import AsyncIOMotorCollection

from app.ai.gpu_lease import (
    GpuLeaseError,
    RunPodDriver,
    TeardownError,
    destroy as _destroy_pod,
    provision as _provision,
    reap_orphans,
)

logger = logging.getLogger("app.ai.gpu_broker")

REGISTRY_ID = "active"  # one node at a time — a second document id would be a second billing node
STATE_STARTING = "starting"
STATE_READY = "ready"


class GpuNotReady(GpuLeaseError):
    """No node is serving yet. Not an error in itself — the expected answer to
    `acquire(wait=False)` during a cold start. Queue the work and retry."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: Any) -> datetime | None:
    """Motor (this codebase, tz_aware=True) already returns aware datetimes, but
    this stays defensive against a document written by something that isn't."""
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        logger.warning("%s is not a number; using %s", name, default)
        return default


def idle_minutes() -> float:
    """How long the node may sit unused before it is destroyed. The trade-off is
    one cold start against however long an idle node is kept alive."""
    return _env_float("GPU_IDLE_MINUTES", 10.0)


def max_lifetime_minutes() -> float:
    """Absolute ceiling regardless of use — bounds the worst case of a bug that
    keeps touching the registry to a known number of dollars."""
    return _env_float("GPU_MAX_LIFETIME_MINUTES", 240.0)


def startup_grace_minutes() -> float:
    """How long a `starting` claim is honoured before another process may take it
    over. Must exceed a real cold start, or two processes will both provision."""
    return _env_float("GPU_STARTUP_GRACE_MINUTES", 50.0)


def enabled() -> bool:
    """Master switch, off by default: with this false, nothing in backend_v2 can
    provision a GPU, whatever else is misconfigured. Turning AI inference on is a
    deliberate act, not a side effect of an import."""
    return (os.getenv("GPU_BROKER_ENABLED", "") or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Endpoint:
    """Where to send OpenAI-compatible calls, and what to call the model."""

    base_url: str
    api_key: str
    model: str
    pod_id: str


def _endpoint_from(doc: dict[str, Any]) -> Endpoint:
    return Endpoint(base_url=doc["base_url"], api_key=doc["api_key"], model=doc["model"], pod_id=doc["pod_id"])


def _owner_tag() -> str:
    return f"{socket.gethostname()}/{os.getpid()}/{uuid.uuid4().hex[:6]}"


class GpuBroker:
    """Instantiated with the `ai_gpu_leases` collection — same dependency-injection
    discipline as every canonical service in this codebase, even though this one
    isn't a `CanonicalRepository` (see module docstring)."""

    def __init__(self, collection: AsyncIOMotorCollection, *, health_check_transport: httpx.BaseTransport | None = None):
        self._collection = collection
        # Test-only injection point — see gpu_lease.RunPodDriver's identical
        # `transport` parameter for why: httpx.MockTransport fakes the health
        # check without a real network call.
        self._health_check_transport = health_check_transport

    async def current(self) -> dict[str, Any] | None:
        """The registry document, or None. No provider calls, no side effects."""
        return await self._collection.find_one({"_id": REGISTRY_ID})

    async def touch(self, pod_id: str = "") -> None:
        """Record that the node was just used, deferring its idle shutdown. Call
        this after a successful model call, not before — a failed call against a
        dead node must not extend that node's life."""
        query: dict[str, Any] = {"_id": REGISTRY_ID}
        if pod_id:
            query["pod_id"] = pod_id  # don't resurrect the clock of a since-replaced node
        try:
            await self._collection.update_one(query, {"$set": {"last_used_at": _now()}, "$inc": {"calls": 1}})
        except Exception as e:
            logger.warning("could not record GPU use: %s", e)

    async def _claim_start(self) -> bool:
        """Try to become the process that provisions. True for exactly one caller —
        Mongo evaluates the condition atomically, so concurrent workers cannot both
        match."""
        stale_before = _now() - timedelta(minutes=startup_grace_minutes())
        try:
            result = await self._collection.update_one(
                {
                    "_id": REGISTRY_ID,
                    "$or": [
                        {"state": {"$exists": False}},
                        {"state": {"$nin": [STATE_READY, STATE_STARTING]}},
                        {"state": STATE_STARTING, "started_at": {"$lt": stale_before}},
                    ],
                },
                {
                    "$set": {
                        "state": STATE_STARTING, "owner": _owner_tag(), "started_at": _now(),
                        "last_used_at": _now(), "pod_id": "", "base_url": "", "api_key": "", "model": "", "calls": 0,
                    }
                },
                upsert=True,
            )
        except Exception as e:
            logger.info("did not win the provisioning claim: %s", e)
            return False
        return bool(result.upserted_id or result.modified_count)

    async def _publish(self, lease) -> None:
        await self._collection.update_one(
            {"_id": REGISTRY_ID},
            {
                "$set": {
                    "state": STATE_READY, "pod_id": lease.pod_id, "name": lease.name, "base_url": lease.base_url,
                    "api_key": lease.api_key, "model": lease.model, "ready_at": _now(), "last_used_at": _now(),
                }
            },
            upsert=True,
        )

    async def _clear(self, pod_id: str = "") -> None:
        """Forget the registry entry. Only ever called after the pod is gone —
        clearing while a pod lives would strand a billing node nothing knows to kill."""
        query: dict[str, Any] = {"_id": REGISTRY_ID}
        if pod_id:
            query["pod_id"] = pod_id
        await self._collection.delete_one(query)

    async def _is_healthy(self, doc: dict[str, Any], timeout: float = 8.0) -> bool:
        """Ask the node itself, rather than trusting the document — a pod can be
        evicted or OOM behind our back."""
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self._health_check_transport) as client:
                response = await client.get(f"{doc['base_url'].rstrip('/')}/models", headers={"Authorization": f"Bearer {doc['api_key']}"})
            return response.status_code == 200
        except httpx.HTTPError as e:
            logger.info("health check on pod %s failed: %s", doc.get("pod_id"), type(e).__name__)
            return False

    async def acquire(self, *, wait: bool = True, timeout_minutes: float | None = None, poll_seconds: float = 10.0, **provision_kwargs) -> Endpoint:
        """Return an endpoint for the shared node, starting it if necessary.
        Raises `GpuNotReady` when `wait` is false and the node isn't serving yet,
        `GpuLeaseError` if provisioning genuinely failed."""
        if not enabled():
            raise GpuLeaseError("GPU_BROKER_ENABLED is not set — refusing to provision. This is the switch that keeps a misconfigured deploy from renting GPUs.")

        deadline = time.monotonic() + (timeout_minutes if timeout_minutes is not None else startup_grace_minutes()) * 60

        while True:
            doc = await self.current()

            if doc and doc.get("state") == STATE_READY and doc.get("base_url"):
                if await self._is_healthy(doc):
                    return _endpoint_from(doc)
                logger.warning("registered pod %s is not serving; replacing it", doc.get("pod_id"))
                await self._retire(doc)
                continue

            if await self._claim_start():
                return await self._provision_and_publish(**provision_kwargs)

            if not wait:
                raise GpuNotReady("GPU node is starting (cold start is several minutes). Queue this work and retry rather than holding the request open.")
            if time.monotonic() >= deadline:
                raise GpuLeaseError("timed out waiting for another process to bring up the GPU")

            await asyncio.sleep(poll_seconds)

    async def _provision_and_publish(self, **provision_kwargs) -> Endpoint:
        """Bring up a node under a claim we already hold, and publish it. On
        failure the claim is released — `provision()` destroys its own pod when
        start-up fails, so there is nothing left billing at this point."""
        if os.getenv("GPU_NETWORK_VOLUME_ID"):
            provision_kwargs.setdefault("network_volume_id", os.getenv("GPU_NETWORK_VOLUME_ID"))
        if os.getenv("GPU_MODEL"):
            provision_kwargs.setdefault("model", os.getenv("GPU_MODEL"))
        if os.getenv("GPU_SERVED_MODEL_NAME"):
            provision_kwargs.setdefault("served_name", os.getenv("GPU_SERVED_MODEL_NAME"))

        try:
            lease = await _provision(**provision_kwargs)
        except BaseException:
            await self._clear()
            raise
        await self._publish(lease)
        logger.info("GPU node %s published to the registry", lease.pod_id)
        return _endpoint_from({"base_url": lease.base_url, "api_key": lease.api_key, "model": lease.model, "pod_id": lease.pod_id})

    async def _retire(self, doc: dict[str, Any]) -> None:
        """Destroy the node in `doc` and drop it from the registry, in that order
        — clearing first and then failing to destroy leaves a node nothing will
        ever reap by name."""
        pod_id = doc.get("pod_id") or ""
        if pod_id:
            try:
                await _destroy_pod(pod_id, doc.get("name") or "")
            except TeardownError:
                logger.critical("could not destroy pod %s — it is still billing; leaving the registry entry in place so the next sweep retries", pod_id)
                raise
        await self._clear(pod_id)

    async def sweep(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Shut the node down when it is idle, over its ceiling, or already dead.
        Runs on a schedule (`POST /internal/gpu/sweep`, `torpedo-v2-gpu-sweep.timer`,
        every 5 minutes, built 2026-09-08) for this to be pay-per-use rather
        than a GPU that quietly runs — and bills — all month."""
        outcome: dict[str, Any] = {"action": "none", "pod_id": "", "reaped": []}
        doc = await self.current()

        if doc and doc.get("pod_id"):
            outcome["pod_id"] = doc["pod_id"]
            reason = self._shutdown_reason(doc)
            if reason:
                outcome["action"] = reason
                logger.info("shutting down pod %s: %s", doc["pod_id"], reason)
                if not dry_run:
                    await self._retire(doc)
                doc = None
            elif doc.get("state") == STATE_STARTING:
                outcome["action"] = "starting"

        try:
            outcome["reaped"] = await reap_orphans(
                max_age_minutes=max_lifetime_minutes(), dry_run=dry_run,
                skip_ids=[doc["pod_id"]] if doc and doc.get("pod_id") else [],
            )
        except GpuLeaseError as e:
            logger.error("orphan sweep failed: %s", e)
            outcome["reap_error"] = str(e)

        return outcome

    def _shutdown_reason(self, doc: dict[str, Any]) -> str:
        """Why this node should die now, or "" to leave it running."""
        now = _now()
        state = doc.get("state")

        started = _as_aware(doc.get("started_at"))
        if started and (now - started).total_seconds() / 60.0 > max_lifetime_minutes():
            return "over-max-lifetime"

        if state == STATE_STARTING:
            return ""

        last_used = _as_aware(doc.get("last_used_at")) or _as_aware(doc.get("ready_at"))
        if last_used and (now - last_used).total_seconds() / 60.0 > idle_minutes():
            return "idle"

        return ""

    async def shutdown_now(self) -> dict[str, Any]:
        """Destroy the node immediately, whatever its state. The kill switch."""
        doc = await self.current()
        if not doc or not doc.get("pod_id"):
            await self._clear()
            return {"action": "nothing-running"}
        await self._retire(doc)
        return {"action": "destroyed", "pod_id": doc["pod_id"]}

    async def status(self) -> dict[str, Any]:
        """Human-readable registry state, for an ops endpoint."""
        doc = await self.current()
        if not doc:
            return {"state": "off", "detail": "no node registered"}

        now = _now()
        started = _as_aware(doc.get("started_at"))
        last_used = _as_aware(doc.get("last_used_at"))
        up_minutes = (now - started).total_seconds() / 60.0 if started else None
        hourly = _env_float("GPU_HOURLY_RATE", 35.12)

        return {
            "state": doc.get("state"),
            "pod_id": doc.get("pod_id"),
            "model": doc.get("model"),
            "calls": doc.get("calls", 0),
            "up_minutes": round(up_minutes, 1) if up_minutes is not None else None,
            "idle_minutes": round((now - last_used).total_seconds() / 60.0, 1) if last_used else None,
            "cost_so_far": round(hourly * up_minutes / 60.0, 2) if up_minutes is not None else None,
            "shuts_down_because": self._shutdown_reason(doc) or "-",
        }
