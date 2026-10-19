"""
Login required for every data-changing request (2026-10-19).

Found live: an outside scanner (178.63.197.160, 797 requests) called
POST /api/cold-outreach/dual-fit/enroll with no login and got 200 -- it
enrolled 817 old leads with guessed addresses, and 289 first emails went out
(51 bounced) the same morning. 425 POST/PUT/PATCH/DELETE routes carried no
login dependency at all, including sending mail from company mailboxes
(/gmail/emails/send, /gmail-ws/send, /api/v1/email-sync/send), changing app
settings and replacing the Google service account.

This middleware checks the admin session (session_state.verify_session) on
every POST/PUT/PATCH/DELETE except the public endpoints listed below:

  enforce  -- areas in ENFORCED_PREFIXES (the ones the scanner reached, plus
              mail sending and settings): refused with 401 without a login;
  report   -- everything else, until checked: allowed, and logged as
              "auth-guard: would block ..." so a legitimate caller without a
              login shows up before enforcement is widened.

Settings (backend/.env):
  AUTH_GUARD_MODE              "report" (default) or "enforce" for all routes
  AUTH_GUARD_ENFORCE_PREFIXES  comma list replacing ENFORCED_PREFIXES
  AUTH_GUARD_OFF               "true" disables the guard entirely (emergency)
"""
import logging
import os
import re
from typing import Iterable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("auth_guard")

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# Endpoints that must work without an admin login: respondents, panel members
# (their own auth), vendors/clients/platforms calling back, mail links,
# login itself. Matched against the path with and without a leading "/api".
PUBLIC = [re.compile(p) for p in (
    r"^/store/?$", r"^/routing/inapp-event$", r"^/prefetch-ip",
    r"^/adpixel/", r"^/panel(/|$)", r"^/panel-join", r"^/confirm",
    r"^/webhooks?/", r"^/panel-ses", r"^/sns", r"^/cint/webhook", r"^/cint-response", r"^/cpx-response",
    r"^/cpx-postback", r"^/vendor-response", r"^/response", r"^/survey-status",
    r"^/surveycomplete", r"^/surveyterminate", r"^/surveyquotafull", r"^/surveysecurity",
    r"^/login", r"^/logout", r"^/auth/", r"^/token", r"^/register",
    r"^/cold-outreach/unsubscribe/", r"^/unsubscribe", r"^/sales-outreach/event$",
    r"^/campaigns/automation/tracking/", r"^/track",
    r"^/gmail/oauth/callback", r"^/mystery-shopping/public/",
)]

ENFORCED_PREFIXES = (
    "/cold-outreach", "/sales-outreach", "/gmail", "/gmail-ws", "/v1/email-sync", "/email-sync",
    "/settings", "/performance", "/operations", "/campaigns", "/mail/", "/inbox", "/classified-gmail",
    "/users", "/roles",
)


def _forms(path: str) -> Iterable[str]:
    yield path
    if path.startswith("/api/"):
        yield path[4:]


def is_public(path: str) -> bool:
    return any(p.search(f) for f in _forms(path) for p in PUBLIC)


def enforced_prefixes():
    raw = os.getenv("AUTH_GUARD_ENFORCE_PREFIXES")
    if raw is None:
        return ENFORCED_PREFIXES
    return tuple(x.strip() for x in raw.split(",") if x.strip())


def is_enforced(path: str) -> bool:
    if os.getenv("AUTH_GUARD_MODE", "report").lower() == "enforce":
        return True
    prefixes = enforced_prefixes()
    return any(f == p or f.startswith(p.rstrip("/") + "/") or f.startswith(p)
               for f in _forms(path) for p in prefixes)


class AuthGuard(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if (request.method not in MUTATING or os.getenv("AUTH_GUARD_OFF", "").lower() == "true"
                or is_public(request.url.path)):
            return await call_next(request)
        from session_state import verify_session
        try:
            await verify_session(request)
            return await call_next(request)
        except HTTPException as e:
            ip = (request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0]
                  or (request.client.host if request.client else ""))
            ua = (request.headers.get("user-agent") or "")[:80]
            if is_enforced(request.url.path):
                logger.warning("auth-guard: refused %s %s ip=%s ua=%s (%s)", request.method,
                               request.url.path, ip, ua, e.detail)
                return JSONResponse(status_code=401, content={"detail": "Login required"})
            logger.warning("auth-guard: would block %s %s ip=%s ua=%s (%s)", request.method,
                           request.url.path, ip, ua, e.detail)
            return await call_next(request)
