"""
AuthService — session issuance, verification, revocation, and impersonation.

Session tokens are opaque, high-entropy random strings (`secrets.token_urlsafe`), not
JWTs or any other self-describing/claims-bearing format. This is a deliberate
architectural choice, not an omission: a claims-bearing token invites embedding
roles/org/permissions directly in it, which is exactly the failure mode being avoided
— "authorization state becoming detached from the canonical server-side records."
An opaque token can carry no claims because it carries no structure at all; it is only
ever a lookup key. Every request re-resolves permissions from `RBACService` fresh, so
a permission change takes effect on a caller's very next request, not on their next
login.

Only a SHA-256 hash of the token is ever stored — a stolen database dump yields no
usable session tokens. (Note: SHA-256, not Argon2, for the *token* — a session token
is already 256 bits of random entropy, so a fast hash for O(1) lookup is correct here;
Argon2's deliberate slowness is for *passwords*, which are low-entropy and guessable,
via `app/auth/passwords.py`.)
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from app.auth.models import Credential, Session
from app.auth.passwords import hash_password, verify_password
from app.models.base import CanonicalRepository

DEFAULT_SESSION_TTL = timedelta(hours=12)

# Brute-force lockout — see Credential.failed_attempts/locked_until's own
# comment for why this is per-account, not per-IP. Both an operational-cadence
# choice, not a locked business rule, same discipline as this codebase's other
# threshold constants (HIGH_DROPOUT_THRESHOLD, PROVIDER_FAILURE_THRESHOLD).
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


class AuthenticationFailed(Exception):
    """Bad credentials, or a token that fails verification (missing, malformed,
    unknown, expired, or revoked) — the caller turns this into a 401, never a 403.
    Authentication failures and authorization failures are different facts and must
    render differently; conflating them is exactly the kind of ambiguity that makes a
    security boundary unauditable."""


class AuthService:
    def __init__(
        self,
        credentials: CanonicalRepository[Credential],
        sessions: CanonicalRepository[Session],
        *,
        default_org_id: str,
    ):
        self._credentials = credentials
        self._sessions = sessions
        self._default_org_id = default_org_id

    async def set_password(self, user_id: str, plaintext: str, *, actor: str = "system") -> Credential:
        existing = await self._credentials.find_one({"user_id": user_id})
        password_hash = hash_password(plaintext)
        if existing:
            return await self._credentials.update(
                existing.id, existing.version, {"password_hash": password_hash}, updated_by=actor
            )
        cred = Credential(
            org_id=self._default_org_id, created_by=actor, updated_by=actor,
            user_id=user_id, password_hash=password_hash,
        )
        return await self._credentials.insert(cred)

    async def authenticate(
        self, user_id: str, plaintext: str, *, principal_type: str = "user"
    ) -> tuple[Session, str]:
        """Returns (session_record, raw_token). The raw token exists only here, once
        — it is never retrievable again after this call, by design (only its hash is
        persisted).

        Locked-out state raises the exact same `AuthenticationFailed("invalid
        credentials")` as a wrong password or a missing user, deliberately — a
        distinguishable "account locked" response would itself be a new oracle
        (it would confirm the account exists AND that 5 failed attempts have
        accumulated), which is exactly the class of leak the "same error for
        every failure mode" rule already exists to prevent."""
        cred = await self._credentials.find_one({"user_id": user_id})
        if cred is None:
            raise AuthenticationFailed("invalid credentials")

        now = datetime.now(timezone.utc)
        if cred.locked_until is not None and cred.locked_until > now:
            raise AuthenticationFailed("invalid credentials")

        if not verify_password(plaintext, cred.password_hash):
            new_failed = cred.failed_attempts + 1
            changes: dict = {"failed_attempts": new_failed}
            if new_failed >= MAX_FAILED_ATTEMPTS:
                changes["locked_until"] = now + LOCKOUT_DURATION
                changes["failed_attempts"] = 0  # a fresh window starts once the lockout itself expires
            await self._credentials.update(cred.id, cred.version, changes, updated_by=user_id)
            raise AuthenticationFailed("invalid credentials")

        if cred.failed_attempts > 0 or cred.locked_until is not None:
            await self._credentials.update(cred.id, cred.version, {"failed_attempts": 0, "locked_until": None}, updated_by=user_id)

        return await self._issue_session(user_id, principal_type=principal_type, impersonated_by=None)

    async def start_impersonation(self, actor_session: Session, target_user_id: str) -> tuple[Session, str]:
        """The actor must already hold a valid, non-impersonating session — you can't
        impersonate through an impersonation. Permission to call this at all
        (`rbac.permissions.IMPERSONATE`) is enforced by the caller (the FastAPI
        dependency layer), not here — this method's job is only the session
        bookkeeping, per the single-responsibility split this module keeps
        throughout (RBACService owns *may this happen*, AuthService owns *the session
        record of it having happened*)."""
        if actor_session.impersonated_by is not None:
            raise AuthenticationFailed("cannot start impersonation from an impersonated session")
        return await self._issue_session(
            target_user_id, principal_type="user", impersonated_by=actor_session.user_id
        )

    async def _issue_session(
        self, user_id: str, *, principal_type: str, impersonated_by: str | None
    ) -> tuple[Session, str]:
        raw_token = secrets.token_urlsafe(32)
        session = Session(
            org_id=self._default_org_id, created_by=user_id, updated_by=user_id,
            user_id=user_id, principal_type=principal_type,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) + DEFAULT_SESSION_TTL,
            impersonated_by=impersonated_by,
        )
        saved = await self._sessions.insert(session)
        return saved, raw_token

    async def verify_token(self, raw_token: str) -> Session:
        """Raises AuthenticationFailed rather than returning None — see the class
        docstring on why a missing/invalid/expired/revoked token is one failure class
        (401), never silently treated as "no session" and left to the caller to
        remember to check."""
        session = await self._sessions.find_one({"token_hash": _hash_token(raw_token)})
        if session is None:
            raise AuthenticationFailed("no such session")
        if session.revoked_at is not None:
            raise AuthenticationFailed("session revoked")
        if session.expires_at <= datetime.now(timezone.utc):
            raise AuthenticationFailed("session expired")
        return session

    async def revoke_session(self, raw_token: str) -> None:
        session = await self._sessions.find_one({"token_hash": _hash_token(raw_token)})
        if session is None:
            return  # revoking a token that doesn't exist is a no-op, not an error
        await self._sessions.update(
            session.id, session.version, {"revoked_at": datetime.now(timezone.utc)}, updated_by=session.user_id
        )
