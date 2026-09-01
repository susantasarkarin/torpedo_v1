"""
Request rate limiting for the endpoints anyone on the internet can reach.

There was none anywhere in the stack — not in the app, not in nginx — so
`POST /login/` was open to unlimited credential stuffing and
`POST /api/crm/web-to-lead` (no auth dependency at all) could be used to write
unbounded documents into crm_db.leads, each one firing a notification. See
TOR-10.

Two layers, because they fail differently:

  * nginx `limit_req` (deploy/configs/nginx_campaign_platform.conf) sheds load
    before it reaches Python at all — the right place for volumetric abuse.
  * this dependency enforces the per-identity policy the app actually cares
    about and returns a proper JSON 429 with Retry-After.

Counters live in Redis when it is available so the limit holds across workers
and restarts, and fall back to a bounded in-process dict otherwise. The
fallback is deliberately still enforced: a single-worker deployment (which is
what runs today) gets full protection from it, and a multi-worker one gets
N times the limit, which is far better than none.
"""

import logging
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() in (
    "1", "true", "yes", "on")

# Bounded so a flood of distinct keys cannot itself become the memory leak.
_MAX_TRACKED_KEYS = 10_000
_buckets: Dict[str, Deque[float]] = defaultdict(deque)


def client_key(request: Request) -> str:
    """
    Identify the caller. Behind nginx and Cloudflare the socket address is
    always the proxy, so prefer the forwarded headers — nginx sets both, and
    CF-Connecting-IP is the one Cloudflare guarantees.
    """
    for header in ("cf-connecting-ip", "x-real-ip"):
        value = request.headers.get(header)
        if value:
            return value.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prune() -> None:
    if len(_buckets) <= _MAX_TRACKED_KEYS:
        return
    now = time.time()
    for key in [k for k, v in _buckets.items() if not v or now - v[-1] > 3600]:
        _buckets.pop(key, None)
    # Still oversized (a genuine flood of distinct sources): drop the oldest
    # half rather than grow without bound.
    if len(_buckets) > _MAX_TRACKED_KEYS:
        for key in sorted(_buckets, key=lambda k: _buckets[k][-1])[:_MAX_TRACKED_KEYS // 2]:
            _buckets.pop(key, None)


async def _redis_allow(bucket: str, limit: int, window: int) -> Optional[bool]:
    """
    Redis fixed-window counter. Returns None when Redis is unavailable so the
    caller can fall back rather than fail the request.
    """
    try:
        try:
            from session_store import SessionStore
        except ImportError:
            from .session_store import SessionStore
        store = await SessionStore.get_instance()
        if not store.is_available:
            return None
        redis = store._client
        key = f"ratelimit:{bucket}:{int(time.time() // window)}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window)
        return count <= limit
    except Exception:
        return None


def rate_limit(limit: int, window_seconds: int, name: str):
    """
    Dependency factory: at most `limit` requests per `window_seconds` per
    caller on the routes that depend on it.

        @router.post("/login/", dependencies=[Depends(rate_limit(10, 60, "login"))])
    """

    async def dependency(request: Request) -> None:
        if not RATE_LIMIT_ENABLED:
            return

        key = client_key(request)
        bucket = f"{name}:{key}"

        allowed = await _redis_allow(bucket, limit, window_seconds)
        if allowed is None:
            # In-process sliding window fallback.
            now = time.time()
            hits = _buckets[bucket]
            cutoff = now - window_seconds
            while hits and hits[0] < cutoff:
                hits.popleft()
            allowed = len(hits) < limit
            if allowed:
                hits.append(now)
            _prune()

        if not allowed:
            logger.warning("rate limit hit: %s from %s (%d/%ds)",
                           name, key, limit, window_seconds)
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Try again in {window_seconds} seconds.",
                headers={"Retry-After": str(window_seconds)},
            )

    return dependency


# Named policies, so the numbers live in one place and are easy to argue about.
# Login is the tightest: a human types a password wrong three times, not thirty.
login_rate_limit = rate_limit(10, 300, "login")            # 10 per 5 min
web_lead_rate_limit = rate_limit(5, 3600, "web_to_lead")   # 5 per hour
signup_rate_limit = rate_limit(5, 3600, "panel_signup")    # 5 per hour
password_reset_rate_limit = rate_limit(5, 3600, "password_reset")
