"""
Request Source Middleware.

Detects the origin of each inbound request (internal vs external) and
attaches ``request.state.request_source`` for downstream use.

Detection priority:
  1. ``X-Request-Source`` header (trusted internal header)
  2. API-key prefix (``torpedo_internal_``)
  3. ``origin_tag`` query parameter
  4. Default: ``external_direct``
"""

from __future__ import annotations

import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

VALID_SOURCES = frozenset({
    "internal_operations",
    "internal_sales",
    "internal_finance",
    "external_vendor",
    "external_direct",
})

INTERNAL_KEY_PREFIX = os.getenv("INTERNAL_API_KEY_PREFIX", "torpedo_internal_")


class RequestSourceMiddleware(BaseHTTPMiddleware):
    """Attach ``request.state.request_source`` to every request."""

    async def dispatch(self, request: Request, call_next):
        source = self._detect_source(request)
        request.state.request_source = source
        response = await call_next(request)
        response.headers["X-Request-Source"] = source
        return response

    @staticmethod
    def _detect_source(request: Request) -> str:
        # 1. Explicit header
        header_val = (request.headers.get("x-request-source") or "").strip().lower()
        if header_val in VALID_SOURCES:
            return header_val

        # 2. API key prefix
        auth = request.headers.get("authorization") or request.headers.get("x-api-key") or ""
        if auth.startswith(INTERNAL_KEY_PREFIX):
            return "internal_operations"

        # 3. Query param
        origin = (request.query_params.get("origin_tag") or "").strip().lower()
        if origin in VALID_SOURCES:
            return origin

        return "external_direct"
