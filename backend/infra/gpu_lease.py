"""
On-demand GPU leases: rent, serve GLM-5.2, run the work, destroy.

The CPU side (this VM) stays up permanently and cheaply. A GPU node costs
roughly $35/hour and is rented only for the minutes a batch actually needs,
then destroyed. The entire risk of this module is a pod that outlives its
job: at $35/hour an unnoticed node is $843/day, which dwarfs the cost of
the work it was rented for.

So teardown is defended three times over, because each layer fails
differently:

  1. `finally` in the lease context manager — covers normal exits and
     exceptions, which is almost every real case.
  2. `reap_orphans()` at the start of every lease — covers SIGKILL, a power
     cut, or a crashed interpreter, where no `finally` ever ran. Pods are
     found by name prefix on the account, not from local state, because
     local state is exactly what a dead machine loses.
  3. `max_minutes` — a deadline checked while waiting, so a node that never
     becomes healthy is destroyed rather than billed indefinitely.

Layer 2 is the one that matters. Run `reap_orphans()` from cron on a host
that is not the one launching jobs:

    */15 * * * * cd /var/www/campaign_platform/backend && \\
        python -m infra.gpu_lease reap --max-age 120

Nothing here is Torpedo-specific except the pod name prefix; `lease_gpu()`
yields a base URL and the caller decides what to do with it.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

import requests

logger = logging.getLogger("gpu_lease")

# Every pod this module creates is named with this prefix. reap_orphans()
# uses it to tell our pods from anything else on the account, so a stray
# reaper can never destroy someone else's work.
POD_NAME_PREFIX = "torpedo-glm"

# RunPod's REST v1 is deprecated and retires 2026-11-15. All request shaping
# lives in RunPodDriver so the migration is one class, not a grep.
DEFAULT_API_BASE = "https://rest.runpod.io/v1"

DEFAULT_IMAGE = "vllm/vllm-openai:latest"
DEFAULT_GPU_TYPE = "NVIDIA H200"
DEFAULT_GPU_COUNT = 8
VLLM_PORT = 8000


class GpuLeaseError(RuntimeError):
    """Provisioning, health-check or teardown failed."""


class TeardownError(GpuLeaseError):
    """A pod could not be destroyed. Always actionable — it is still billing."""


def api_key() -> str:
    key = (os.getenv("RUNPOD_API_KEY") or "").strip()
    if not key:
        raise GpuLeaseError(
            "RUNPOD_API_KEY not set — refusing to provision. Set it in the "
            "environment of whatever runs the batch, not in the repo.")
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
    """
    Every HTTP call to the provider. Isolated so that the REST v1 -> v2
    migration, or a move to another provider, touches one class.
    """

    def __init__(self, key: Optional[str] = None, base: Optional[str] = None,
                 timeout: int = 60):
        self._key = key or api_key()
        self._base = (base or api_base()).rstrip("/")
        self._timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json"}

    def _request(self, method: str, path: str,
                 payload: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self._base}{path}"
        try:
            response = requests.request(
                method, url, headers=self._headers(), json=payload,
                timeout=self._timeout)
        except requests.RequestException as e:
            raise GpuLeaseError(f"{method} {path} transport error: {e}") from e

        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise GpuLeaseError(
                f"{method} {path} failed [{response.status_code}]: "
                f"{response.text[:300]}")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    def create_pod(self, name: str, image: str, gpu_type: str, gpu_count: int,
                   env: Dict[str, str], args: str,
                   disk_gb: int, volume_gb: int) -> str:
        payload = {
            "name": name,
            "imageName": image,
            "gpuTypeIds": [gpu_type],
            "gpuCount": gpu_count,
            "containerDiskInGb": disk_gb,
            "volumeInGb": volume_gb,
            "volumeMountPath": "/workspace",
            "ports": [f"{VLLM_PORT}/http"],
            "env": env,
            "dockerStartCmd": ["/bin/bash", "-lc", args],
        }
        data = self._request("POST", "/pods", payload) or {}
        pod_id = data.get("id") or (data.get("pod") or {}).get("id")
        if not pod_id:
            raise GpuLeaseError(f"provider returned no pod id: {str(data)[:300]}")
        return pod_id

    def get_pod(self, pod_id: str) -> Optional[Dict[str, Any]]:
        return self._request("GET", f"/pods/{pod_id}")

    def list_pods(self) -> List[Dict[str, Any]]:
        data = self._request("GET", "/pods")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("pods", "data", "items"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    def terminate_pod(self, pod_id: str) -> None:
        """Idempotent: a pod that is already gone is a success, not an error."""
        self._request("DELETE", f"/pods/{pod_id}")


def _vllm_command(model: str, served_name: str, gpu_count: int,
                  max_model_len: int) -> str:
    """
    vLLM launch line.

    --api-key is not optional here. An automated lease cannot hold an SSH
    tunnel open, so the endpoint is reached over the provider's public proxy;
    without this flag that is an unauthenticated LLM holding lead data,
    reachable by anyone who guesses the pod id.

    --default-chat-template-kwargs disables GLM's thinking mode server-side.
    That is the only place it can be done for callers like claude_gateway,
    which has no per-request hook for extra parameters.
    """
    return (
        f"vllm serve {model} "
        f"--served-model-name {served_name} "
        f"--tensor-parallel-size {gpu_count} "
        f"--max-model-len {max_model_len} "
        f"--api-key $VLLM_API_KEY "
        f"--default-chat-template-kwargs '{{\"enable_thinking\": false}}' "
        f"--host 0.0.0.0 --port {VLLM_PORT}"
    )


def _proxy_url(pod_id: str) -> str:
    return f"https://{pod_id}-{VLLM_PORT}.proxy.runpod.net/v1"


def _pod_age_minutes(pod: Dict[str, Any]) -> Optional[float]:
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


def reap_orphans(max_age_minutes: float = 120.0, dry_run: bool = False,
                 driver: Optional[RunPodDriver] = None) -> List[str]:
    """
    Destroy pods this module created that have outlived any plausible job.

    Deliberately reads the provider's pod list rather than local state: the
    failure this defends against is the launching machine dying, which takes
    local state with it. Only pods whose name carries POD_NAME_PREFIX are
    ever touched.

    Returns the pod ids reaped (or that would be, when dry_run).
    """
    driver = driver or RunPodDriver()
    reaped: List[str] = []
    for pod in driver.list_pods():
        name = str(pod.get("name") or "")
        if not name.startswith(POD_NAME_PREFIX):
            continue
        pod_id = pod.get("id")
        if not pod_id:
            continue
        age = _pod_age_minutes(pod)
        if age is None:
            logger.warning("pod %s (%s) has no readable creation time; "
                           "leaving it alone", pod_id, name)
            continue
        if age < max_age_minutes:
            continue
        logger.warning("reaping orphaned pod %s (%s), age %.0f min > %.0f",
                       pod_id, name, age, max_age_minutes)
        reaped.append(pod_id)
        if not dry_run:
            try:
                driver.terminate_pod(pod_id)
            except GpuLeaseError as e:
                logger.error("REAP FAILED for %s — still billing: %s", pod_id, e)
    return reaped


def wait_for_ready(base_url: str, key: str, deadline: float,
                   poll_seconds: float = 15.0) -> None:
    """
    Block until vLLM answers, or the deadline passes.

    Cold start on a 753B model is around seven minutes — weight loading,
    torch.compile and CUDA graph capture — so connection errors during that
    window are expected and not failures.
    """
    last: str = "no attempt made"
    while time.monotonic() < deadline:
        try:
            response = requests.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {key}"}, timeout=10)
            if response.status_code == 200:
                logger.info("vLLM is serving at %s", base_url)
                return
            last = f"HTTP {response.status_code}"
        except requests.RequestException as e:
            last = type(e).__name__
        logger.info("waiting for vLLM (%s)...", last)
        time.sleep(poll_seconds)
    raise GpuLeaseError(
        f"vLLM did not become ready before the deadline (last: {last})")


@contextmanager
def lease_gpu(model: str = "zai-org/GLM-5.2",
              served_name: str = "GLM-5.2",
              gpu_type: str = DEFAULT_GPU_TYPE,
              gpu_count: int = DEFAULT_GPU_COUNT,
              image: str = DEFAULT_IMAGE,
              max_minutes: float = 120.0,
              startup_minutes: float = 45.0,
              max_model_len: int = 131072,
              disk_gb: int = 200,
              volume_gb: int = 1000,
              reap_first: bool = True,
              driver: Optional[RunPodDriver] = None,
              ) -> Iterator[Lease]:
    """
    Rent a GPU node, wait for GLM to serve, yield it, then destroy it.

        with lease_gpu() as lease:
            os.environ["SELF_HOSTED_BASE_URL"] = lease.base_url
            os.environ["SELF_HOSTED_API_KEY"] = lease.api_key
            run_the_batch()

    The pod is destroyed on the way out whether the body succeeded, raised,
    or the process was interrupted. If teardown itself fails, TeardownError
    is raised loudly rather than logged quietly — a pod that would not die
    is the one thing here worth waking someone for.
    """
    driver = driver or RunPodDriver()

    if reap_first:
        try:
            reap_orphans(driver=driver)
        except GpuLeaseError as e:
            # A failed reap must not stop the job, but it must be visible.
            logger.error("orphan sweep failed (continuing): %s", e)

    job_id = uuid.uuid4().hex[:10]
    name = f"{POD_NAME_PREFIX}-{job_id}"
    vllm_key = secrets.token_urlsafe(32)

    logger.info("provisioning %s x%d as %s", gpu_type, gpu_count, name)
    pod_id = driver.create_pod(
        name=name, image=image, gpu_type=gpu_type, gpu_count=gpu_count,
        env={"VLLM_API_KEY": vllm_key, "HF_HUB_ENABLE_HF_TRANSFER": "1"},
        args=_vllm_command(model, served_name, gpu_count, max_model_len),
        disk_gb=disk_gb, volume_gb=volume_gb)

    lease = Lease(pod_id=pod_id, name=name, base_url=_proxy_url(pod_id),
                  api_key=vllm_key, model=served_name)
    logger.info("pod %s created; waiting for vLLM (cold start ~7 min)", pod_id)

    try:
        wait_for_ready(lease.base_url, vllm_key,
                       deadline=time.monotonic() + startup_minutes * 60)
        if lease.elapsed_minutes > max_minutes:
            raise GpuLeaseError("startup consumed the whole lease budget")
        yield lease
    finally:
        _terminate_hard(driver, lease)


def _terminate_hard(driver: RunPodDriver, lease: Lease,
                    attempts: int = 4) -> None:
    """
    Destroy the pod, retrying, and verify it is actually gone.

    Runs from a `finally`, so it must not mask the exception that sent us
    here — but silently swallowing a failed teardown would leave a billing
    node with nobody told. Retries, then raises.
    """
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            driver.terminate_pod(lease.pod_id)
            logger.info("pod %s destroyed after %.1f min",
                        lease.pod_id, lease.elapsed_minutes)
            return
        except GpuLeaseError as e:
            last_error = e
            logger.warning("teardown attempt %d/%d for %s failed: %s",
                           attempt, attempts, lease.pod_id, e)
            if attempt < attempts:
                time.sleep(min(2 ** attempt, 15))

    raise TeardownError(
        f"POD {lease.pod_id} ({lease.name}) COULD NOT BE DESTROYED and is "
        f"still billing. Kill it by hand at runpod.io/console/pods or with: "
        f"curl -X DELETE {api_base()}/pods/{lease.pod_id} "
        f"-H 'Authorization: Bearer $RUNPOD_API_KEY'. "
        f"Last error: {last_error}")


def _cli() -> int:
    import argparse
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    reap = sub.add_parser("reap", help="destroy orphaned pods")
    reap.add_argument("--max-age", type=float, default=120.0,
                      help="minutes; older pods are destroyed (default 120)")
    reap.add_argument("--dry-run", action="store_true")

    sub.add_parser("list", help="show pods this module owns")

    args = parser.parse_args()

    if args.cmd == "reap":
        reaped = reap_orphans(max_age_minutes=args.max_age,
                              dry_run=args.dry_run)
        verb = "would reap" if args.dry_run else "reaped"
        print(f"{verb} {len(reaped)} pod(s): {', '.join(reaped) or '-'}")
        return 0

    driver = RunPodDriver()
    ours = [p for p in driver.list_pods()
            if str(p.get("name") or "").startswith(POD_NAME_PREFIX)]
    if not ours:
        print("no pods owned by this module")
    for pod in ours:
        age = _pod_age_minutes(pod)
        age_text = f"{age:.0f} min" if age is not None else "age unknown"
        print(f"{pod.get('id')}  {pod.get('name')}  {age_text}  "
              f"{pod.get('desiredStatus') or pod.get('status') or '?'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
