"""Skrapp replaces Hunter in the lead-gen MCP server (2026-10-15). No network."""
import asyncio
from unittest.mock import MagicMock

from backend.lead_gen_mcp import enricher, skrapp


class _Client:
    def __init__(self, code, body):
        self.code, self.body, self.calls = code, body, []

    async def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        r = MagicMock(status_code=self.code)
        r.json.return_value = self.body
        return r


VALID = {"email": "Priya.Sharma@nielsen.com", "pattern": "{first}.{last}", "quality": {"status": "valid"},
         "companyData": {"name": "Nielsen", "country": "India"}}


def test_request_shape(monkeypatch):
    monkeypatch.setenv("SKRAPP_API_KEY_1", "k1")
    c = _Client(200, VALID)
    out = asyncio.run(skrapp.find(c, "Priya", "Sharma", company="Nielsen", company_data=True))
    url, params, headers = c.calls[0]
    assert url == "https://api.skrapp.io/api/v2/find"
    assert params == {"firstName": "Priya", "lastName": "Sharma", "company": "Nielsen", "includeCompanyData": "true"}
    assert headers == {"X-Access-Key": "k1"}
    assert out["email"] == "priya.sharma@nielsen.com" and out["quality"] == "valid"


def test_enricher_takes_only_valid_addresses(monkeypatch):
    monkeypatch.setenv("SKRAPP_API_KEY_1", "k1")
    saved = {}
    monkeypatch.setattr(enricher.st, "save_domain_pattern", lambda d, p, m: saved.update(domain=d, pattern=p))
    row = asyncio.run(enricher._skrapp_lookup(_Client(200, VALID), "Priya", "Sharma", "Nielsen"))
    assert row["domain"] == "nielsen.com" and row["email"] == "priya.sharma@nielsen.com"
    assert saved == {"domain": "nielsen.com", "pattern": "{first}.{last}"}
    catch_all = {"email": "x@y.com", "quality": {"status": "catch-all"}}
    assert asyncio.run(enricher._skrapp_lookup(_Client(200, catch_all), "A", "B", "Y")) is None


def test_not_found_and_no_key(monkeypatch):
    monkeypatch.setenv("SKRAPP_API_KEY_1", "k1")
    assert asyncio.run(skrapp.find(_Client(404, {}), "A", "B", domain="y.com")) is None
    for k in ("SKRAPP_API_KEY", "SKRAPP_API_KEY_1", "SKRAPP_API_KEY_2", "SKRAPP_API_KEY_3"):
        monkeypatch.delenv(k, raising=False)
    c = _Client(200, VALID)
    assert asyncio.run(skrapp.find(c, "A", "B", domain="y.com")) is None and not c.calls
