"""
ToolRegistry — named, controlled context-fetchers a caller assembles before asking
the Decision Engine to decide. Deliberately **not** live LLM-invoked function-calling
yet: master-prompt §28's "the AI must NOT have unrestricted database access" and §3's
"separate the AI decision layer from the deterministic execution/governance layer"
both argue for the caller (deterministic code) choosing which tools to run and
handing the results to the model as context, rather than the model autonomously
invoking arbitrary registered tools mid-conversation. Real agentic tool-calling needs
a running model to validate against (which model, whether it supports structured
tool-calls, how it fails) — none of which is verifiable without `RUNPOD_API_KEY`
configured. This registry is the mechanism; wiring it into live multi-turn tool-calling
is deferred, honestly, not silently skipped.

Every tool registered here is **read-only** — nothing in this module can write
business state. Actions (`create_lead`, `send_email`, ...) stay where they've always
been: real domain services, gated by real permission checks, called only by
deterministic code that decides to act on a `Decision` — never by this registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable


class ToolError(Exception):
    """Unknown tool name, or the underlying handler raised."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    handler: Callable[..., Awaitable[dict]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def describe_all(self) -> list[dict]:
        """What a prompt-builder would tell the model exists — name/description
        pairs only, never the handler itself."""
        return [{"name": t.name, "description": t.description} for t in self._tools.values()]

    async def call(self, name: str, **kwargs) -> dict:
        spec = self._tools.get(name)
        if spec is None:
            raise ToolError(f"unknown tool {name!r}")
        return await spec.handler(**kwargs)
