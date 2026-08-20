"""Guards the lifetime ceiling on register-invites.

The min-gap setting spaces invites out but never stops them, so a lead who
never engages was mailed every few days indefinitely — 2.87M sends to 186K
people, with 108,148 receiving 14 invites each for a combined 3 clicks.
"""

import importlib
import os

import pytest


def _reload(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("PANEL_MAX_INVITES_PER_PANELIST", raising=False)
    else:
        monkeypatch.setenv("PANEL_MAX_INVITES_PER_PANELIST", value)
    import services.panel_email_service as svc
    return importlib.reload(svc)


@pytest.mark.parametrize("value,expected", [
    (None, 0),      # unset -> no cap, previous behaviour
    ("", 0),
    ("8", 8),
    ("3", 3),
    ("abc", 0),     # unparseable -> no cap, never an accidental stop
    ("-1", 0),
])
def test_cap_parsing(monkeypatch, value, expected):
    svc = _reload(monkeypatch, value)
    assert svc.PANEL_MAX_INVITES_PER_PANELIST == expected


def test_zero_does_not_silently_halt_the_programme(monkeypatch):
    """0 means "no lifetime cap" here, NOT the daily-batch kill-switch meaning.

    The daily batch treats cap=0 as a kill switch. Reusing that here would make
    an unset-looking value stop every invite in the system, which is the exact
    surprise that convention exists to prevent.
    """
    svc = _reload(monkeypatch, "0")
    assert svc.PANEL_MAX_INVITES_PER_PANELIST == 0


def test_cap_is_enforced_from_the_send_log_not_a_counter(monkeypatch):
    """Counting from the log keeps history for the 186K already mailed.

    A fresh per-panelist counter would start everyone at zero and hand the
    most over-mailed addresses a brand new allowance.
    """
    import inspect
    svc = _reload(monkeypatch, "8")
    src = inspect.getsource(svc.send_bulk_invitations)
    assert "invitation_log_collection.aggregate" in src
    assert "exhausted_set" in src
