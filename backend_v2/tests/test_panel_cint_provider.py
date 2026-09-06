"""
`CintSurveyProvider` — built against v1's actual, verified entry-link integration.
Everything faked; nothing here may reach a real Cint endpoint.
"""

from datetime import timezone

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

from app.models.base import CanonicalRepository
from app.models.money import Money
from app.panel.cint_provider import CintSurveyProvider
from app.panel.models import Survey
from app.panel.providers import SurveyProviderUnavailable

CURRENCY = "INR"


@pytest.fixture(autouse=True)
def _cint_credentials(monkeypatch):
    monkeypatch.setenv("CINT_API_KEY", "fake-key-for-tests")
    monkeypatch.setenv("CINT_SUPPLIER_CODE", "fake-supplier-code")


def _survey() -> Survey:
    return Survey(org_id="org-A", created_by="a", updated_by="a", provider="cint", external_id="ext-1", quota_remaining=10, cpi=Money(amount_minor=500, currency=CURRENCY), conversion_rate=0.3)


@pytest.mark.asyncio
async def test_missing_credentials_raises_before_any_request(monkeypatch):
    monkeypatch.delenv("CINT_API_KEY", raising=False)
    provider = CintSurveyProvider()
    with pytest.raises(SurveyProviderUnavailable):
        await provider.build_redirect_url(survey=_survey(), respondent_ref="r1")


@pytest.mark.asyncio
async def test_build_redirect_url_returns_the_live_link():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "SupplierLinks/Create/ext-1/fake-supplier-code" in str(request.url)
        assert request.headers["Authorization"] == "fake-key-for-tests"
        return httpx.Response(200, json={"SupplierLink": {"LiveLink": "https://sandbox.example/enter/abc"}})

    provider = CintSurveyProvider(transport=httpx.MockTransport(handler))
    url = await provider.build_redirect_url(survey=_survey(), respondent_ref="r1")
    assert url == "https://sandbox.example/enter/abc"


@pytest.mark.asyncio
async def test_build_redirect_url_raises_when_response_has_no_live_link():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"SupplierLink": {}})

    provider = CintSurveyProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(SurveyProviderUnavailable):
        await provider.build_redirect_url(survey=_survey(), respondent_ref="r1")


@pytest.mark.asyncio
async def test_build_redirect_url_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    provider = CintSurveyProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(SurveyProviderUnavailable):
        await provider.build_redirect_url(survey=_survey(), respondent_ref="r1")


@pytest.mark.asyncio
async def test_refresh_is_an_honest_unimplemented_boundary_not_a_guess():
    """No fabricated success — refresh() names exactly what's missing rather than
    parsing an unverified endpoint's response shape."""
    provider = CintSurveyProvider()
    with pytest.raises(SurveyProviderUnavailable):
        await provider.refresh(survey=_survey())
