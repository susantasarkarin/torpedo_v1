#!/usr/bin/env python
"""
Run a Torpedo batch against a GPU rented for exactly as long as it takes.

    python scripts/run_on_gpu.py --job enrich --limit 500
    python scripts/run_on_gpu.py --dry-run        # lease + smoke test only
    python scripts/run_on_gpu.py --reap-only      # kill orphaned pods

The CPU host stays up; the GPU exists only inside the `with` block. On the
way out the pod is destroyed whether the job succeeded, raised, or was
interrupted — see infra/gpu_lease.py for why teardown is defended three
separate ways.

Both AI paths are pointed at the lease, because they read different
variables: leads/bedrock_client.py uses SELF_HOSTED_*, while the CRM's
ai_governance/claude_gateway.py builds its own client from
BEDROCK_MANTLE_BASE_URL. Setting only one silently leaves half the
application talking to Bedrock.
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from infra.gpu_lease import (  # noqa: E402
    GpuLeaseError, TeardownError, lease_gpu, reap_orphans,
)

logger = logging.getLogger("run_on_gpu")

# Published on-demand rate for 8xH200; used only for the cost line in the
# summary, so a stale value misreports the log and nothing else.
HOURLY_RATE = float(os.getenv("GPU_HOURLY_RATE", "35.12"))


def point_torpedo_at(base_url: str, key: str, model: str) -> None:
    """Route both AI paths at the leased node for this process only."""
    os.environ["SELF_HOSTED_BASE_URL"] = base_url
    os.environ["SELF_HOSTED_API_KEY"] = key
    os.environ["BEDROCK_MODEL_CHEAP"] = f"local:{model}"
    os.environ["BEDROCK_MODEL_SMART"] = f"local:{model}"

    # claude_gateway (CRM) reads these instead, and raises on a blank key
    # even though vLLM ignores the value.
    os.environ["BEDROCK_MANTLE_BASE_URL"] = base_url
    os.environ["BEDROCK_MODEL_PREMIUM"] = model
    os.environ.setdefault("AWS_BEARER_TOKEN_BEDROCK", key)

    # Thinking is disabled on the vLLM server itself, so no per-request
    # parameter is needed. Clearing this avoids sending Z.ai's key shape
    # to a server that would reject it.
    os.environ.pop("SELF_HOSTED_EXTRA_PARAMS", None)


def smoke_test(base_url: str, key: str, model: str) -> None:
    """
    One real call before committing a batch to the node.

    Checks the failure this pipeline actually hits: a reasoning model that
    spends its whole budget thinking and returns empty content. A non-empty
    answer with a large completion_tokens means thinking is still on.
    """
    import requests
    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "max_tokens": 64, "temperature": 0.0,
              "messages": [{"role": "user",
                            "content": 'Reply with only this JSON: {"ok":true}'}]},
        timeout=120)
    response.raise_for_status()
    body = response.json()
    content = ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    used = (body.get("usage") or {}).get("completion_tokens")

    if not content.strip():
        raise GpuLeaseError(
            f"model returned empty content ({used} completion tokens) — "
            "thinking is still enabled; --default-chat-template-kwargs did "
            "not take. Aborting before the batch bills for reasoning.")
    logger.info("smoke test ok: %r (%s completion tokens)", content[:80], used)


def run_job(name: str, limit: int, dry_run: bool) -> int:
    """
    Dispatch to the real batch. Returns the number of records processed.

    backfill_enrich checkpoints as it goes, which matters here: a leased
    node can vanish mid-run (provider eviction, a failed health check), and
    the next lease resumes rather than reprocessing from the top.
    """
    import asyncio

    if name == "enrich":
        from leads import backfill_enrich
        stats = asyncio.run(backfill_enrich.run(
            dry_run=dry_run,
            limit=limit or None,
            do_enrich=True,
            checkpoint_path=backfill_enrich.DEFAULT_CHECKPOINT,
            reset=False,
        ))
        for key in sorted(stats):
            logger.info("  %-18s %s", key, stats[key])
        return int(stats.get("processed") or stats.get("updated") or 0)

    raise SystemExit(f"unknown job: {name!r} (known: enrich)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", default="enrich",
                        help="batch to run (known: enrich)")
    parser.add_argument("--limit", type=int, default=0, help="0 = all pending")
    parser.add_argument("--gpu-count", type=int, default=8)
    parser.add_argument("--gpu-type", default="NVIDIA H200")
    parser.add_argument("--max-minutes", type=float, default=120.0)
    parser.add_argument("--dry-run", action="store_true",
                        help="lease and smoke-test, then tear down without "
                             "running the batch")
    parser.add_argument("--reap-only", action="store_true",
                        help="destroy orphaned pods and exit")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.reap_only:
        reaped = reap_orphans()
        print(f"reaped {len(reaped)} pod(s)")
        return 0

    started = time.monotonic()
    processed = 0
    try:
        with lease_gpu(gpu_type=args.gpu_type, gpu_count=args.gpu_count,
                       max_minutes=args.max_minutes) as lease:
            point_torpedo_at(lease.base_url, lease.api_key, lease.model)
            smoke_test(lease.base_url, lease.api_key, lease.model)

            if args.dry_run:
                logger.info("dry run — node is healthy, skipping the batch")
            else:
                processed = run_job(args.job, args.limit, dry_run=False)

            logger.info("job done after %.1f min on the node",
                        lease.elapsed_minutes)
    except TeardownError:
        # Never swallowed: the pod is still billing and needs a human.
        logger.critical("TEARDOWN FAILED — see the error above and kill the "
                        "pod by hand before doing anything else")
        raise
    except GpuLeaseError as e:
        logger.error("lease failed: %s", e)
        return 1

    minutes = (time.monotonic() - started) / 60.0
    logger.info("total %.1f min, ~$%.2f, %d record(s)",
                minutes, HOURLY_RATE * minutes / 60.0, processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
