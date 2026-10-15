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
  - release = LPUSH the token back, always in a `finally`, so a normal
    exception mid-inference can't leak the gate closed forever.

The `finally` alone is NOT enough against every failure mode -- confirmed
live on 2026-09-19: a benchmark process was killed (SIGTERM, via `pkill`)
while blocked inside a synchronous HTTP call holding the slot. A process
blocked in a C-level system call can be torn down before Python ever gets
to run the pending `finally` (signals are only checked between bytecode
instructions), so the token was gone from the list permanently -- every
subsequent caller queue-timed-out ("server is at capacity") even though
nothing was actually running. Fixed with a per-checkout Redis key holding
a TTL "lease": if a token's lease expires without the token reappearing in
the list, whoever calls _reclaim_orphaned_slots() next (every acquire)
tops the list back up. A crash can delay recovery by at most the lease
TTL; it can no longer wedge the gate forever.

Usage:
    from leads.local_llm_gate import acquire_local_llm_slot, LocalLLMQueueTimeout

    try:
        with acquire_local_llm_slot():
            ...call the local model...
    except LocalLLMQueueTimeout:
        ...fail fast; do not retry the same overloaded instance...
"""

import logging
import os
import time
import uuid
from contextlib import contextmanager
from typing import Optional

from redis import Redis, WatchError

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_GATE_KEY = "local_llm_gate:slots"
_LEASE_KEY_PREFIX = "local_llm_gate:lease:"
_LEASE_TTL_ENV = "LOCAL_LLM_LEASE_TTL_SECONDS"
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


def lease_ttl_seconds() -> float:
    # Must comfortably exceed the longest legitimate single call through
    # this gate (mail_pool_ai's local timeout, currently 90s) -- too short
    # and a slow-but-healthy call gets its slot reclaimed out from under
    # it; too long and a real crash takes longer to self-heal. 180s gives
    # 2x margin over that longest known caller.
    try:
        return max(10.0, float(os.getenv(_LEASE_TTL_ENV, "180")))
    except (TypeError, ValueError):
        return 180.0


def _reclaim_orphaned_slots(client: Redis, capacity: int) -> None:
    """
    A token whose lease key has expired without the token reappearing in
    _GATE_KEY means its holder crashed (or was killed) before its `finally`
    could run -- top the list back up to `capacity` minus however many
    leases are still genuinely active. Never reclaims a slot that's still
    legitimately checked out (its lease key would still exist).

    Not wrapped in WATCH/MULTI: two callers racing this at the exact
    moment a stale lease expires could both compute the same `missing`
    count and each push a recovery token, briefly over-provisioning by one
    slot. Accepted trade-off for a capacity=1-2 gate -- self-corrects once
    the extra in-flight calls finish, and is a far smaller problem than
    the permanent deadlock this function exists to fix.
    """
    list_len = client.llen(_GATE_KEY)
    active_leases = len(client.keys(f"{_LEASE_KEY_PREFIX}*"))
    missing = capacity - list_len - active_leases
    for _ in range(max(0, missing)):
        client.rpush(_GATE_KEY, f"slot-recovered-{client.incr('local_llm_gate:recovery_counter')}")


import contextlib
import contextvars

# A caller that runs off the event loop and would rather wait than lose its
# work can raise the queue wait for its own calls only. Lead extraction does:
# with the default 5s it lost the slot to every 10-60s mail job and its search
# results -- already paid for in CSE quota -- were set aside. Context-local,
# so asyncio.to_thread carries it into the worker thread and nothing else is
# affected.
_queue_wait_override: contextvars.ContextVar = contextvars.ContextVar(
    "local_llm_queue_wait", default=None)
# Same idea for how long one inference may run: extracting ten leads as JSON
# on the CPU model takes 60-120s, past the 60s default, so every real
# extraction was cut off and reported as "model unavailable".
_inference_timeout_override: contextvars.ContextVar = contextvars.ContextVar(
    "local_llm_inference_timeout", default=None)


@contextlib.contextmanager
def queue_wait(seconds: float, inference_seconds: Optional[float] = None,
               priority: Optional[str] = None):
    token = _queue_wait_override.set(float(seconds))
    itoken = _inference_timeout_override.set(
        float(inference_seconds) if inference_seconds is not None else None)
    ptoken = _priority.set(priority) if priority else None
    try:
        yield
    finally:
        _queue_wait_override.reset(token)
        _inference_timeout_override.reset(itoken)
        if ptoken is not None:
            _priority.reset(ptoken)


def inference_timeout_override() -> Optional[float]:
    return _inference_timeout_override.get()


def queue_timeout_seconds() -> float:
    override = _queue_wait_override.get()
    if override is not None:
        return max(0.1, override)
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


# ---------------------------------------------------------------------------
# Priority (2026-10-14)
# ---------------------------------------------------------------------------
# The slot used to go to whichever waiter BLPOP happened to wake: lead
# extraction (search results already paid for) queued behind bulk lead
# classification and mail summaries, and every caller looked the same in the
# logs. Waiters now register in a sorted set and only the front of the line
# may take a token.
#
# Order: interactive -> rfq -> extraction -> bulk. Fairness by aging: a
# waiter's place is its arrival time plus PRIORITY_RANK x the aging step, so a
# bulk job that has waited 3 steps longer than a newly arrived interactive call
# is ahead of it -- a stream of high-priority work delays bulk work, it never
# starves it. Priority is separate from capacity: this changes WHO gets the
# next slot, never how many slots exist (LOCAL_LLM_MAX_CONCURRENCY).
PRIORITY_RANK = {"interactive": 0, "rfq": 1, "extraction": 2, "bulk": 3}
DEFAULT_PRIORITY = "interactive"
_WAITERS_KEY = "local_llm_gate:waiters"
_WAITER_ALIVE_PREFIX = "local_llm_gate:waiter:"
_STATS_KEY_PREFIX = "local_llm_gate:stats:"
_AGING_ENV = "LOCAL_LLM_PRIORITY_AGING_SECONDS"
# A waiter refreshes its heartbeat every poll; a crashed waiter's entry is
# dropped once the heartbeat lapses, so it cannot hold the front of the line.
_WAITER_TTL_SECONDS = 10
_POLL_SECONDS = 0.2

_priority: contextvars.ContextVar = contextvars.ContextVar("local_llm_priority", default=None)


@contextlib.contextmanager
def llm_priority(name: str):
    """Run the enclosed local-model calls at this priority (see PRIORITY_RANK)."""
    if name not in PRIORITY_RANK:
        raise ValueError(f"unknown local-LLM priority {name!r}")
    token = _priority.set(name)
    try:
        yield
    finally:
        _priority.reset(token)


def current_priority() -> str:
    return _priority.get() or DEFAULT_PRIORITY


def aging_seconds() -> float:
    try:
        return max(0.0, float(os.getenv(_AGING_ENV, "120")))
    except (TypeError, ValueError):
        return 120.0


def _prune_dead_waiters(client: Redis) -> None:
    members = client.zrange(_WAITERS_KEY, 0, -1)
    if not members:
        return
    pipe = client.pipeline()
    for m in members:
        pipe.exists(f"{_WAITER_ALIVE_PREFIX}{m}")
    dead = [m for m, alive in zip(members, pipe.execute()) if not alive]
    if dead:
        client.zrem(_WAITERS_KEY, *dead)


def _record(client: Redis, priority: str, outcome: str, waited: float) -> None:
    """Per-day counters (calls / timeouts / total wait) per priority; best effort."""
    try:
        key = _STATS_KEY_PREFIX + time.strftime("%Y%m%d", time.gmtime())
        pipe = client.pipeline()
        pipe.hincrby(key, f"{priority}:{outcome}", 1)
        pipe.hincrbyfloat(key, f"{priority}:wait_s", round(waited, 3))
        pipe.expire(key, 14 * 86400)
        pipe.execute()
    except Exception:
        pass


def daily_stats(day: Optional[str] = None) -> dict:
    """{'rfq:calls': 12, 'rfq:timeouts': 0, 'rfq:wait_s': 33.1, ...} for a UTC day (YYYYMMDD)."""
    day = day or time.strftime("%Y%m%d", time.gmtime())
    return _get_client().hgetall(_STATS_KEY_PREFIX + day)


@contextmanager
def acquire_local_llm_slot(timeout: Optional[float] = None, priority: Optional[str] = None):
    """
    Waits in priority order until a slot is free or `timeout` (default:
    LOCAL_LLM_QUEUE_TIMEOUT_SECONDS) elapses. Raises LocalLLMQueueTimeout on
    timeout rather than hanging indefinitely.
    """
    client = _get_client()
    capacity = max_concurrency()
    wait = queue_timeout_seconds() if timeout is None else timeout
    prio = priority or current_priority()
    _ensure_seeded(client, capacity)
    _reclaim_orphaned_slots(client, capacity)

    waiter = uuid.uuid4().hex
    alive_key = f"{_WAITER_ALIVE_PREFIX}{waiter}"
    score = time.time() + PRIORITY_RANK.get(prio, PRIORITY_RANK["bulk"]) * aging_seconds()
    started = time.monotonic()
    deadline = started + wait
    token = None
    client.set(alive_key, prio, ex=_WAITER_TTL_SECONDS)
    client.zadd(_WAITERS_KEY, {waiter: score})
    try:
        while True:
            _prune_dead_waiters(client)
            rank = client.zrank(_WAITERS_KEY, waiter)
            if rank is None:  # pruned during a stall longer than the heartbeat: rejoin
                client.zadd(_WAITERS_KEY, {waiter: score})
                rank = client.zrank(_WAITERS_KEY, waiter)
            if rank is not None and rank < capacity:
                token = client.lpop(_GATE_KEY)
                if token is not None:
                    break
            if time.monotonic() >= deadline:
                break
            client.set(alive_key, prio, ex=_WAITER_TTL_SECONDS)
            time.sleep(_POLL_SECONDS)
    finally:
        client.zrem(_WAITERS_KEY, waiter)
        client.delete(alive_key)

    waited = time.monotonic() - started
    if token is None:
        _record(client, prio, "timeouts", waited)
        logger.warning("local-llm gate: queue timeout priority=%s waited=%.1fs capacity=%d waiting=%d",
                       prio, waited, capacity, client.zcard(_WAITERS_KEY))
        raise LocalLLMQueueTimeout(
            f"no local-LLM inference slot free within {wait}s "
            f"(max_concurrency={capacity}, priority={prio}) -- server is at capacity")

    _record(client, prio, "calls", waited)
    logger.info("local-llm gate: slot acquired priority=%s waited=%.1fs", prio, waited)
    lease_key = f"{_LEASE_KEY_PREFIX}{token}"
    client.set(lease_key, "1", ex=int(lease_ttl_seconds()))
    try:
        yield
    finally:
        client.lpush(_GATE_KEY, token)
        client.delete(lease_key)
