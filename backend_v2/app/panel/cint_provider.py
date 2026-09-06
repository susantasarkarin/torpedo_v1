"""
CintSurveyProvider — the real `SurveyProvider` implementation, built against v1's
actual, actively-used Cint integration (`backend/app/services/cint_service.py`) as
the verified reference, not a guess: same base URLs, same auth header shape, same
entry-link endpoint v1's production code calls today.

**`build_redirect_url()` is real and verified.** `POST {base}Supply/v1/SupplierLinks/
Create/{survey_id}/{supplier_code}` with `Authorization: <api_key>` (the raw key,
not a Bearer token — confirmed from v1's `_get_headers()`) returns
`{"SupplierLink": {"LiveLink": "...", ...}}`; `LiveLink` is the respondent redirect
URL. This is the same call v1's production entry-link creation path makes.

**`refresh()` is honestly NOT implemented against a real endpoint, and says so.**
Auditing v1 found that Cint's opportunities API (the survey-availability/quota side)
is a **push subscription** — Cint calls a callback URL you register, the same
push-only shape already documented for outcomes (`app.panel.service.CallbackService`'s
docstring: "Cint's outcomes subscription is push-only, no history endpoint"). There
is no verified pull-per-survey quota endpoint: v1 defined
`LEGACY_SURVEY_DETAIL_ENDPOINT` but never actually called it anywhere in the
codebase, so its response shape is unconfirmed. Rather than fabricate a parser for
an endpoint this session cannot verify, `refresh()` raises
`SurveyProviderUnavailable` naming exactly what's missing: a real implementation
needs either Cint's actual per-survey detail response schema (needs live API
access to confirm) or an inbound opportunities-webhook receiver symmetric to
`CallbackService` (a real, buildable architecture change, just not this one).
Guessing here would be exactly "never return fake successful Cint data."

**Fails loud on a missing credential**, same discipline as
`app.ai.gpu_lease.api_key()`: `CINT_API_KEY`/`CINT_SUPPLIER_CODE` unset raises
immediately, never silently no-ops.
"""

from __future__ import annotations

import os

import httpx

from app.panel.models import Survey
from app.panel.providers import SurveyProjection, SurveyProviderUnavailable

SANDBOX_BASE_URL = "https://sandbox.techops.engineering/"
PRODUCTION_BASE_URL = "https://api.samplicio.us/"
ENTRY_LINKS_ENDPOINT = "Supply/v1/SupplierLinks"


def _credentials() -> tuple[str, str]:
    api_key = (os.getenv("CINT_API_KEY") or "").strip()
    supplier_code = (os.getenv("CINT_SUPPLIER_CODE") or "").strip()
    if not api_key or not supplier_code:
        raise SurveyProviderUnavailable(
            "CINT_API_KEY/CINT_SUPPLIER_CODE not set — refusing to call Cint. "
            "Set them in the environment of whatever runs backend_v2, not in the repo."
        )
    return api_key, supplier_code


def _base_url() -> str:
    environment = (os.getenv("CINT_ENVIRONMENT") or "sandbox").strip().lower()
    return PRODUCTION_BASE_URL if environment == "production" else SANDBOX_BASE_URL


class CintSurveyProvider:
    def __init__(self, *, timeout: float = 30.0, transport: httpx.BaseTransport | None = None):
        self._timeout = timeout
        self._transport = transport  # test-only injection point, see app.ai.gpu_lease.RunPodDriver

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": api_key, "Content-Type": "application/json"}

    async def build_redirect_url(self, *, survey: Survey, respondent_ref: str) -> str:
        api_key, supplier_code = _credentials()
        url = f"{_base_url()}{ENTRY_LINKS_ENDPOINT}/Create/{survey.external_id}/{supplier_code}"
        payload = {"SupplierRid": respondent_ref}

        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(url, json=payload, headers=self._headers(api_key))
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise SurveyProviderUnavailable(f"Cint entry-link request failed: {exc}") from exc

        link = data.get("SupplierLink") or {}
        live_link = link.get("LiveLink")
        if not live_link:
            raise SurveyProviderUnavailable(f"Cint entry-link response did not include a LiveLink: {str(data)[:300]}")
        return live_link

    async def refresh(self, *, survey: Survey) -> SurveyProjection:
        raise SurveyProviderUnavailable(
            "Cint has no verified pull-per-survey quota/CPI endpoint — its opportunities API is "
            "push/webhook-based (same shape as its outcomes subscription). Implementing this needs "
            "either Cint's real per-survey detail response schema (unconfirmed without live API "
            "access) or an inbound opportunities-webhook receiver. Not guessed at here."
        )
