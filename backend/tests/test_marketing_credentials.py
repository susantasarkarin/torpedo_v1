"""Integration credentials: encrypted at rest, never returned (MARKETING_PLAN "Secrets")."""
import json

import pytest
from cryptography.fernet import Fernet

from marketing import credentials as C
from tests._fakemongo import FakeDB

TOKEN = "EAAB-super-secret-token-123"


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv(C.KEY_ENV, Fernet.generate_key().decode())
    monkeypatch.setattr(C, "_audit", lambda *a, **k: None)
    d = {"email_automation": FakeDB()}
    return d, (lambda n: d[n])


def test_secret_is_encrypted_at_rest_and_never_in_status(db):
    d, gd = db
    C.save("meta", secrets={"system_user_token": TOKEN}, settings={"page_ids": {"SFW": "111"}}, actor="owner", gd=gd)
    raw = json.dumps(d["email_automation"][C.COLLECTION].docs, default=str)
    assert TOKEN not in raw
    st = C.status(gd)
    assert TOKEN not in json.dumps(st, default=str)
    assert st["meta"]["secrets"] == {"system_user_token": True, "app_secret": False, "webhook_verify_token": False} and st["meta"]["connected"]
    assert st["meta"]["settings"]["page_ids"] == {"SFW": "111"} and st["_key_configured"]
    assert C.secrets("meta", gd)["system_user_token"] == TOKEN


def test_blank_secret_keeps_stored_value_and_clear_removes_it(db):
    d, gd = db
    C.save("pagespeed", secrets={"api_key": "k1"}, actor="o", gd=gd)
    C.save("pagespeed", secrets={"api_key": "  "}, settings={"urls": ["https://bimwavesolutions.com/"]}, actor="o", gd=gd)
    assert C.secrets("pagespeed", gd)["api_key"] == "k1"
    C.clear("pagespeed", "api_key", actor="o", gd=gd)
    assert not C.status(gd)["pagespeed"]["connected"]
    C.clear("pagespeed", None, actor="o", gd=gd)
    assert d["email_automation"][C.COLLECTION].count_documents({}) == 0


def test_unknown_platform_or_field_rejected(db):
    _, gd = db
    with pytest.raises(KeyError):
        C.save("tiktok", secrets={"x": "y"}, actor="o", gd=gd)
    with pytest.raises(ValueError):
        C.save("meta", secrets={"password": "y"}, actor="o", gd=gd)
    with pytest.raises(ValueError):
        C.save("meta", settings={"random": 1}, actor="o", gd=gd)


def test_no_key_refuses_to_store(monkeypatch):
    monkeypatch.delenv(C.KEY_ENV, raising=False)
    monkeypatch.setattr(C, "_audit", lambda *a, **k: None)
    d = {"email_automation": FakeDB()}
    with pytest.raises(C.CredentialsUnavailable):
        C.save("meta", secrets={"system_user_token": TOKEN}, actor="o", gd=lambda n: d[n])
    assert d["email_automation"][C.COLLECTION].count_documents({}) == 0
    assert C.status(lambda n: d[n])["_key_configured"] is False


def test_settings_only_platform_counts_as_connected(db):
    _, gd = db
    C.save("quora", settings={"pixel_ids": {"SFW": "abc"}}, actor="o", gd=gd)
    assert C.status(gd)["quora"]["connected"]


def test_mark_error_text_is_stored_truncated(db):
    _, gd = db
    C.save("linkedin", secrets={"client_secret": "s"}, actor="o", gd=gd)
    C.mark("linkedin", ok=False, error="x" * 500, gd=gd)
    assert len(C.status(gd)["linkedin"]["last_error"]) == 300
    C.mark("linkedin", ok=True, gd=gd)
    assert C.status(gd)["linkedin"]["last_error"] is None and C.status(gd)["linkedin"]["last_ok_at"]
