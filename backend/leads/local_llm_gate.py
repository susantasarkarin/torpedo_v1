"""
LOCAL LLM CONCURRENCY GATE
==========================

Bounded, cross-process admission control for the local Qwen2.5-0.5B server
(torpedo-v2-llm.service, 127.0.0.1:8003, `--parallel 1`). Multiple Celery worker
*processes* can call the "cheap" role independently -- nothing at the HTTP layer
stopped two of them hitting the single-slot server at once, which is exactly what
caused the 2026-09-16 incident (VM load average ~107 on a 2-vCPU box): unbounded
concurrent callers, each retrying a queued/timed-out request, compounding into
swap-thrashing. An in-process threading.Semaphore would only protect one
interpreter -- Celery's forked workers are separate processes, so the gate has
to live somewhere all of them can see it. Redis is already running as Celery's
own broker (see celery_app.py), so no new infrastructure is needed.

Implemented as a Redis list pre-seeded with LOCAL_LLM_MAX_CONCURRENCY tokens:
  - acquire = BLPOP -- a real blocking wait with a native timeout, not a polling
    loop, so "queue timeout" (how long a caller waits for a slot) falls out for
    free.
  - release = LPUSH the token back, always in a `finally`, so a crash mid-
    inference can't leak the gate closed forever.

Usage:
    from leads.local_llm_gate import acquire_local_llm_slot, LocalLLMQueueTimeout

    try:
        with acquire_local_llm_slot():
            ...call the local model...
    except LocalLLMQueueTimeout:
        ...fail fast; do not retry the same overloaded instance...
"""

import os
from contextlib import contextmanager
from typing import Optional

from redis import Redis, WatchError

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_GATE_KEY = "local_llm_gate:slots"
# Tracks what capacity the list was LAST seeded to -- deliberately separate
# from the list's live length. The list's length falls whenever a slot is
# checked out; if seeding just topped it back up to `capacity` on every
# acquire, a slot in active use would look identical to "never seeded" and a
# concurrent caller would get a freshly-minted token instead of genuinely
# waiting -- silently defeating the capacity=1 guarantee. Seeding logic must
# react only to the configured capacity actually changing, never to normal
# checkout/release traffic.
_CAPACITY_KEY = "local_llm_gate:capacity"

_MAX_CONCURRENCY_ENV = "LOCAL_LLM_MAX_CONCURRENCY"
_QUEUE_TIMEOUT_ENV = "LOCAL_LLM_QUEUE_TIMEOUT_SECONDS"

# Bounded retries on WATCH conflict, not an assumption every attempt succeeds
# on the first try -- concurrent processes seeding at once can and will
# occasionally collide.
_SEED_RETRY_ATTEMPTS = 5

_client: Optional[Redis] = None


def _get_client() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(REDIS_URL, decode_responses=True)
    return _client


def max_concurrency() -> int:
    try:
        return max(1, int(os.getenv(_MAX_CONCURRENCY_ENV, "1")))
    except (TypeError, ValueError):
        return 1


def queue_timeout_seconds() -> float:
    try:
        return max(0.1, float(os.getenv(_QUEUE_TIMEOUT_ENV, "5")))
    except (TypeError, ValueError):
        return 5.0


class LocalLLMQueueTimeout(Exception):
    """Raised when no inference slot became free within the queue timeout.
    Callers must fail fast, not retry the same overloaded instance -- see
    bedrock_client.py's _FAILOVER_CODES, where this is classified accordingly."""


def _ensure_seeded(client: Redis, capacity: int) -> None:
    """
    Make sure the list has been initialized for `capacity` -- but ONLY acts
    when the capacity marker doesn't already match, never based on the
    list's current length (see _CAPACITY_KEY's docstring for why that
    distinction matters). Atomic via WATCH/MULTI: EXEC aborts if the marker
    changed since WATCH (caught as WatchError, retried), so two processes
    racing to initialize at once can't both push and leave the list holding
    more tokens than intended.

    Runs on every acquire (GET is O(1)) rather than once at import, since a
    forked Celery worker shouldn't depend on import-time ordering, and
    capacity is env-configurable per restart -- but the common case (marker
    already matches) is a single cheap GET, not a list rewrite.
    """
    for _ in range(_SEED_RETRY_ATTEMPTS):
        with client.pipeline() as pipe:
            try:
                pipe.watch(_CAPACITY_KEY)
                marker = pipe.get(_CAPACITY_KEY)
                marker_val = int(marker) if marker is not None else None
                if marker_val == capacity:
                    pipe.reset()
                    return  # already initialized for this capacity -- leave real usage alone
                pipe.multi()
                if marker_val is None:
                    # First-ever initialization: create exactly `capacity` tokens.
                    for i in range(capacity):
                        pipe.rpush(_GATE_KEY, f"slot-{i}")
                elif capacity > marker_val:
                    # Capacity raised: add only the NEW tokens: existing
                    # checked-out/available ones are untouched either way.
                    for i in range(marker_val, capacity):
                        pipe.rpush(_GATE_KEY, f"slot-{i}")
                else:
                    # Capacity lowered: trim available tokens down. Best
                    # effort -- one currently checked out isn't forcibly
                    # reclaimed, so real concurrency stays at the old, higher
                    # capacity until enough slots are released naturally.
                    pipe.ltrim(_GATE_KEY, 0, max(capacity - 1, -1))
                pipe.set(_CAPACITY_KEY, capacity)
                pipe.execute()
                return
            except WatchError:
                continue
    # Every attempt collided with another process seeding at the same moment
    # -- proceed with whatever the list currently holds rather than blocking
    # the caller on seeding specifically; the next acquire tries again.


@contextmanager
def acquire_local_llm_slot(timeout: Optional[float] = None):
    """
    Blocks (via Redis BLPOP, not polling) until a slot is free or `timeout`
    (default: LOCAL_LLM_QUEUE_TIMEOUT_SECONDS) elapses. Raises
    LocalLLMQueueTimeout on timeout rather than hanging indefinitely.
    """
    client = _get_client()
    capacity = max_concurrency()
    wait = queue_timeout_seconds() if timeout is None else timeout
    _ensure_seeded(client, capacity)

    result = client.blpop([_GATE_KEY], timeout=wait)
    if result is None:
        raise LocalLLMQueueTimeout(
            f"no local-LLM inference slot free within {wait}s "
            f"(max_concurrency={capacity}) -- server is at capacity")

    _, token = result
    try:
        yield
    finally:
        client.lpush(_GATE_KEY, token)
