"""
Unit tests for the route authorization decision (app/security.is_allowed).

Pure logic — no DB or HTTP. Verifies the safe-by-default behaviour (disabled =>
allow) and the coarse capability enforcement when enabled.
"""

import pytest

pytestmark = pytest.mark.smoke

security = None
_import_error = None
try:
    from backend.app import security as _sec
    security = _sec
except Exception as e:  # pragma: no cover
    _import_error = e

ADMIN = {"username": "a", "roles": ["admin"]}
MANAGER = {"username": "m", "roles": ["manager"]}
USER = {"username": "u", "roles": ["user"]}
VIEWER = {"username": "v", "roles": ["viewer"]}


@pytest.fixture(autouse=True)
def _guard():
    if security is None:
        pytest.skip(f"security module unavailable: {_import_error}")


def test_disabled_allows_everything():
    # Safe-by-default: with enforcement off, even a viewer may approve.
    assert security.is_allowed(VIEWER, "approve", enabled=False) is True
    assert security.is_allowed({}, "write", enabled=False) is True


def test_no_capability_required_allows():
    assert security.is_allowed(VIEWER, None, enabled=True) is True


def test_enabled_enforces_read_write_approve():
    assert security.is_allowed(VIEWER, "read", enabled=True) is True
    assert security.is_allowed(VIEWER, "write", enabled=True) is False
    assert security.is_allowed(USER, "write", enabled=True) is True
    assert security.is_allowed(USER, "approve", enabled=True) is False
    assert security.is_allowed(MANAGER, "approve", enabled=True) is True


def test_admin_wildcard_allows_all():
    assert security.is_allowed(ADMIN, "write", enabled=True) is True
    assert security.is_allowed(ADMIN, "approve", enabled=True) is True


def test_unknown_role_denied_when_enabled():
    weird = {"username": "x", "roles": ["contractor"]}
    assert security.is_allowed(weird, "read", enabled=True) is False
    # ...but never blocked while enforcement is disabled (no lockout risk).
    assert security.is_allowed(weird, "read", enabled=False) is True
