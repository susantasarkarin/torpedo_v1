"""Zoho Books client (India DC): token refresh, paging, org id, write gate."""
import pytest

from integrations import zoho_books as zb


class _Resp:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data
        self.content = b"x"

    def json(self):
        return self._data


@pytest.fixture
def env(monkeypatch):
    for k, v in {"ZOHO_CLIENT_ID": "cid", "ZOHO_CLIENT_SECRET": "sec", "ZOHO_REFRESH_TOKEN": "rt",
                 "ZOHO_ORG_ID": "60015654919"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("ZOHO_WRITE_ENABLED", raising=False)
    zb._Token.value = None
    zb._Token.expires_at = 0


def test_not_configured_names_what_is_missing(monkeypatch):
    for k in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_ORG_ID"):
        monkeypatch.delenv(k, raising=False)
    zb._Token.value = None
    with pytest.raises(zb.ZohoNotConfigured) as e:
        zb.access_token()
    assert "ZOHO_REFRESH_TOKEN" in str(e.value)


def test_india_endpoints_org_id_and_paging(env, monkeypatch):
    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append(("POST", url))
        return _Resp(200, {"access_token": "at", "expires_in": 3600})

    pages = {1: {"code": 0, "invoices": [{"invoice_id": "1"}], "page_context": {"has_more_page": True}},
             2: {"code": 0, "invoices": [{"invoice_id": "2"}], "page_context": {"has_more_page": False}}}

    def fake_request(method, url, params=None, json=None, timeout=None, headers=None):
        calls.append((method, url, params["organization_id"], headers["Authorization"]))
        return _Resp(200, pages[params["page"]])

    monkeypatch.setattr(zb.requests, "post", fake_post)
    monkeypatch.setattr(zb.requests, "request", fake_request)
    assert [i["invoice_id"] for i in zb.invoices()] == ["1", "2"]
    assert calls[0] == ("POST", "https://accounts.zoho.in/oauth/v2/token")
    assert calls[1][1] == "https://www.zohoapis.in/books/v3/invoices"
    assert calls[1][2] == "60015654919" and calls[1][3] == "Zoho-oauthtoken at"
    assert sum(1 for c in calls if c[0] == "POST") == 1  # token reused across pages


def test_writing_is_off_by_default(env):
    with pytest.raises(zb.ZohoWriteDisabled):
        zb.create_draft_invoice({"customer_id": "1"})


def test_api_error_is_raised_with_zohos_message(env, monkeypatch):
    monkeypatch.setattr(zb.requests, "post", lambda *a, **k: _Resp(200, {"access_token": "at"}))
    monkeypatch.setattr(zb.requests, "request",
                        lambda *a, **k: _Resp(400, {"code": 2, "message": "Invalid value passed for organization_id"}))
    with pytest.raises(zb.ZohoError) as e:
        zb.get("/invoices")
    assert "organization_id" in str(e.value)
