"""
LLMProvider — the fifth instance of this codebase's external-boundary `Protocol`
pattern (`app.leadgen.ai.AIClassifier`, `app.outreach.providers.SendProvider`,
`app.outreach.drafting.MessageDrafter`, `app.panel.providers.SurveyProvider`, now
this). Tested against fakes throughout. Two real implementations exist:
`GpuBrokerLLMProvider` (a rented, on-demand RunPod pod, acquired/leased through
`GpuBroker`) and `LocalLlamaCppProvider` (an always-on llama.cpp process this
deployment's own VM runs and owns outright — no lease, no idle-sweep, no external
account). `get_llm_provider()` prefers the local provider when configured, same
"prefer the real thing that's actually configured" discipline as
`app.outreach.routers.get_send_provider()` preferring SES over SMTP.

`LLMUnavailable` mirrors `AIUnavailable` exactly: raised, never returned as an empty
response — the same I-4 shape ("AI failure is never a business verdict") applied to
the model boundary itself, not just to what the model is asked to decide.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from app.ai.gpu_broker import GpuBroker
from app.ai.gpu_lease import GpuLeaseError


class LLMUnavailable(Exception):
    """Raised, never returned as an empty/fabricated response. A caller cannot
    mistake a cold-starting or unreachable model for "the model answered nothing"
    — those are different failures with different correct responses."""


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    # Real token usage, parsed from the OpenAI-compatible endpoint's own
    # `usage` object when the real server includes one — never fabricated.
    # `None` (not 0) when the server doesn't report it, so a caller can tell
    # "not measured" apart from "measured as zero."
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class LLMProvider(Protocol):
    async def chat(self, *, messages: list[dict], response_format: dict | None = None) -> LLMResponse:
        """May raise LLMUnavailable."""
        ...


class GpuBrokerLLMProvider:
    """The real provider. `wait=False` (the default) is the request-handler-safe
    form: a cold start raises `LLMUnavailable` immediately rather than blocking on
    a multi-minute wait — callers on a request path should catch this and queue
    the work, not hold a connection open (same rule `GpuBroker.acquire()` itself
    documents for `wait=False`)."""

    def __init__(self, broker: GpuBroker, *, wait: bool = False, transport: httpx.BaseTransport | None = None):
        self._broker = broker
        self._wait = wait
        self._transport = transport  # test-only injection point, see gpu_lease.RunPodDriver

    async def chat(self, *, messages: list[dict], response_format: dict | None = None) -> LLMResponse:
        try:
            endpoint = await self._broker.acquire(wait=self._wait)
        except GpuLeaseError as exc:
            raise LLMUnavailable(str(exc)) from exc

        payload: dict = {"model": endpoint.model, "messages": messages}
        if response_format:
            payload["response_format"] = response_format

        try:
            async with httpx.AsyncClient(timeout=120.0, transport=self._transport) as client:
                response = await client.post(
                    f"{endpoint.base_url}/chat/completions", json=payload,
                    headers={"Authorization": f"Bearer {endpoint.api_key}"},
                )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"model call failed: {exc}") from exc

        await self._broker.touch(endpoint.pod_id)

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"model response did not match the expected shape: {exc}") from exc

        usage = data.get("usage") or {}
        return LLMResponse(
            content=content, model=endpoint.model,
            prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"), total_tokens=usage.get("total_tokens"),
        )


class LocalLlamaCppProvider:
    """The real local-inference provider: calls an always-on llama.cpp
    `llama-server` process (OpenAI-compatible `/chat/completions`) that this
    deployment starts, owns, and restarts itself via systemd — see
    docs/LOCAL_LLM_RUNBOOK.md for exactly which model, how it's started, and
    how the endpoint/API key are configured. Deliberately does not go through
    `GpuBroker`: there is no lease to acquire and no idle timer to touch —
    the process is either up (this call succeeds or the server itself
    returns an error) or down (this call raises `LLMUnavailable`), the same
    two-state shape `verify_token()` uses for a session rather than
    inventing a third "maybe" state."""

    def __init__(self, *, base_url: str, model: str, api_key: str | None = None, transport: httpx.BaseTransport | None = None):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._transport = transport  # test-only injection point, same as GpuBrokerLLMProvider

    async def chat(self, *, messages: list[dict], response_format: dict | None = None) -> LLMResponse:
        payload: dict = {"model": self._model, "messages": messages}
        if response_format:
            payload["response_format"] = response_format
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        try:
            async with httpx.AsyncClient(timeout=120.0, transport=self._transport) as client:
                response = await client.post(f"{self._base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"local model call failed: {exc}") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"local model response did not match the expected shape: {exc}") from exc

        usage = data.get("usage") or {}
        return LLMResponse(
            content=content, model=data.get("model") or self._model,
            prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"), total_tokens=usage.get("total_tokens"),
        )


def get_llm_provider(db) -> LLMProvider:
    """The one place every router constructs its LLMProvider — was 7 separate
    `GpuBrokerLLMProvider(GpuBroker(db["ai_gpu_leases"]))` call sites across
    4 files before this, each of which would have needed editing (and could
    have been missed) to pick up the local provider. Prefers
    `LocalLlamaCppProvider` when `local_llm_base_url` is configured; falls
    back to the unchanged RunPod broker path otherwise — this never deletes
    or replaces that path, only takes priority over it."""
    from app.config import get_settings

    settings = get_settings()
    if settings.local_llm_base_url:
        return LocalLlamaCppProvider(
            base_url=settings.local_llm_base_url, model=settings.local_llm_model_name, api_key=settings.local_llm_api_key,
        )
    return GpuBrokerLLMProvider(GpuBroker(db["ai_gpu_leases"]))
