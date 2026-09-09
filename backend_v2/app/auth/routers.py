"""
HTTP surface for authentication — the piece that was missing entirely.

`AuthService.authenticate()`/`revoke_session()` were real, tested service methods
with no HTTP endpoint exposing either — nothing in `app.main` mounted a login route,
meaning no external caller could ever obtain a session token through this API at
all. This closes that gap with exactly two routes: login and logout.

**Deliberately no self-service registration/signup endpoint.** This is a
single-tenant, internally-provisioned B2B system — every existing user in this
codebase is created via `AuthService.set_password()` called by an operator/seed
script, never by a public "create my own account" flow. Adding one would be a real
product decision (open registration risk, email verification, invite flows) this
router does not make unilaterally.

**Uniform 401 on every failure mode**, mirroring `AuthenticationFailed`'s own
docstring: wrong password, unknown user, and a locked-out account all return the
identical `{"detail": "invalid credentials"}` body — a distinguishable response for
any one of these would be a user-enumeration or lockout-state oracle.

**Brute-force protection is real but scoped**: `AuthService.authenticate()` now
locks an account for `LOCKOUT_DURATION` after `MAX_FAILED_ATTEMPTS` consecutive
failures (`app.auth.service`). This is per-account, not per-IP — there is no
distributed rate-limiting infrastructure in this codebase (no Redis, no shared
in-memory limiter across worker processes), and building one is a materially
larger undertaking than this endpoint. Real protection against credential-stuffing
on a known account; honestly not IP-based throttling.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import get_auth_service
from app.auth.service import AuthenticationFailed, AuthService

router = APIRouter()


class LoginRequest(BaseModel):
    user_id: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime
    user_id: str


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest, svc: AuthService = Depends(get_auth_service)) -> LoginResponse:
    # Never logged, never echoed back beyond this one response, never included
    # in any error detail — the raw token exists in exactly one place after
    # this call: the caller's own response body (see AuthService.authenticate()'s
    # own docstring: "the raw token exists only here, once").
    try:
        session, token = await svc.authenticate(body.user_id, body.password)
    except AuthenticationFailed as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials") from exc
    return LoginResponse(token=token, expires_at=session.expires_at, user_id=session.user_id)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(authorization: str | None = Header(default=None), svc: AuthService = Depends(get_auth_service)) -> None:
    """Idempotent by design, same as `AuthService.revoke_session()` itself:
    logging out with no token, a malformed header, or an already-revoked
    token is a no-op, never an error — there is nothing a caller needs to
    retry or handle."""
    if not authorization or not authorization.startswith("Bearer "):
        return
    raw_token = authorization.removeprefix("Bearer ").strip()
    await svc.revoke_session(raw_token)
