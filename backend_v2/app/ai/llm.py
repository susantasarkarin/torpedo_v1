"""
LLMProvider — the fifth instance of this codebase's external-boundary `Protocol`
pattern (`app.leadgen.ai.AIClassifier`, `app.outreach.providers.SendProvider`,
`app.outreach.drafting.MessageDrafter`, `app.panel.providers.SurveyProvider`, now
this). Tested against fakes throughout; `GpuBrokerLLMProvider` is the real
implementation, calling the shared node's OpenAI-compatible endpoint through
`GpuBroker.acquire()`.

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

        return LLMResponse(content=content, model=endpoint.model)
