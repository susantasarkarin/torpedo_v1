"""
AuthService unit tests — session lifecycle, revocation, expiry, and impersonation,
independent of FastAPI. `test_auth_dependencies.py` covers the same chain end-to-end
through actual HTTP requests; this file proves the service layer underneath it is
correct in isolation, so a dependency-wiring bug and a service-logic bug can't hide
behind each other.
"""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.auth.models import Credential, Session
from app.auth.service import AuthenticationFailed, AuthService, _hash_token
from app.models.base import CanonicalRepository

ORG = "org-A"


@pytest.fixture
def auth() -> AuthService:
    db = AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]
    return AuthService(
        credentials=CanonicalRepository(db["credentials"], Credential),
        sessions=CanonicalRepository(db["sessions"], Session),
        default_org_id=ORG,
    )


@pytest.mark.asyncio
async def test_authenticate_with_correct_password_succeeds(auth: AuthService):
    await auth.set_password("alice", "correct-horse-battery")

    session, raw_token = await auth.authenticate("alice", "correct-horse-battery")

    assert session.user_id == "alice"
    assert session.principal_type == "user"
    assert session.impersonated_by is None
    assert len(raw_token) > 20


@pytest.mark.asyncio
async def test_authenticate_with_wrong_password_fails(auth: AuthService):
    await auth.set_password("alice", "correct-horse-battery")

    with pytest.raises(AuthenticationFailed):
        await auth.authenticate("alice", "wrong-password")


@pytest.mark.asyncio
async def test_authenticate_unknown_user_fails_with_same_error_as_wrong_password(auth: AuthService):
    """No user-enumeration oracle: an attacker probing usernames must not be able to
    distinguish 'no such user' from 'wrong password' by error type or message."""
    await auth.set_password("alice", "correct-horse-battery")

    with pytest.raises(AuthenticationFailed) as unknown_user_exc:
        await auth.authenticate("nobody", "anything")
    with pytest.raises(AuthenticationFailed) as wrong_password_exc:
        await auth.authenticate("alice", "wrong-password")

    assert str(unknown_user_exc.value) == str(wrong_password_exc.value)


@pytest.mark.asyncio
async def test_raw_token_is_never_persisted(auth: AuthService):
    await auth.set_password("alice", "correct-horse-battery")
    session, raw_token = await auth.authenticate("alice", "correct-horse-battery")

    assert session.token_hash != raw_token
    assert session.token_hash == _hash_token(raw_token)


@pytest.mark.asyncio
async def test_verify_token_with_valid_token_returns_session(auth: AuthService):
    await auth.set_password("alice", "correct-horse-battery")
    _, raw_token = await auth.authenticate("alice", "correct-horse-battery")

    verified = await auth.verify_token(raw_token)

    assert verified.user_id == "alice"


@pytest.mark.asyncio
async def test_verify_token_with_garbage_token_fails(auth: AuthService):
    with pytest.raises(AuthenticationFailed):
        await auth.verify_token("this-was-never-issued")


@pytest.mark.asyncio
async def test_verify_token_with_expired_session_fails(auth: AuthService):
    await auth.set_password("alice", "correct-horse-battery")
    session, raw_token = await auth.authenticate("alice", "correct-horse-battery")
    # Force expiry directly at the repository level, bypassing the service's own
    # TTL logic, so this test proves verify_token's expiry check independent of
    # whatever the default TTL happens to be.
    await auth._sessions.update(
        session.id, session.version,
        {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
        updated_by="test",
    )

    with pytest.raises(AuthenticationFailed):
        await auth.verify_token(raw_token)


@pytest.mark.asyncio
async def test_revoked_session_fails_verification(auth: AuthService):
    await auth.set_password("alice", "correct-horse-battery")
    _, raw_token = await auth.authenticate("alice", "correct-horse-battery")

    await auth.revoke_session(raw_token)

    with pytest.raises(AuthenticationFailed):
        await auth.verify_token(raw_token)


@pytest.mark.asyncio
async def test_impersonation_session_carries_the_real_actor(auth: AuthService):
    await auth.set_password("admin-bob", "correct-horse-battery")
    admin_session, _ = await auth.authenticate("admin-bob", "correct-horse-battery")

    impersonation_session, impersonation_token = await auth.start_impersonation(
        admin_session, target_user_id="carol"
    )

    assert impersonation_session.user_id == "carol"
    assert impersonation_session.impersonated_by == "admin-bob"

    verified = await auth.verify_token(impersonation_token)
    assert verified.user_id == "carol"
    assert verified.impersonated_by == "admin-bob"


@pytest.mark.asyncio
async def test_cannot_impersonate_through_an_impersonation(auth: AuthService):
    await auth.set_password("admin-bob", "correct-horse-battery")
    admin_session, _ = await auth.authenticate("admin-bob", "correct-horse-battery")
    impersonation_session, _ = await auth.start_impersonation(admin_session, target_user_id="carol")

    with pytest.raises(AuthenticationFailed):
        await auth.start_impersonation(impersonation_session, target_user_id="dana")


def test_password_shorter_than_minimum_is_rejected():
    from app.auth.passwords import hash_password

    with pytest.raises(ValueError):
        hash_password("short")
