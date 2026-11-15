"""
Thin Anthropic Haiku client for lead_gen_mcp.

lead_gen_mcp runs as its own systemd service (torpedo-lead-gen-mcp) under its
own venv and imports nothing from the rest of backend, so it cannot use
platform_core.ladder. This is the same provider (Anthropic Messages API), one
call, no SDK dependency beyond httpx (already used by this package).

Env:
  ANTHROPIC_API_KEY   required (loaded via EnvironmentFile= from backend/.env)
  LLM_MODEL_FAST      model id, default claude-haiku-5-5
"""

from __future__ import annotations

import os

import httpx

DEFAULT_MODEL = "claude-haiku-5-5"
_URL = "https://api.anthropic.com/v1/messages"


def call_llm(system: str, user: str, max_tokens: int = 1024,
             temperature: float = 0.3) -> str:
    """One Haiku call. Returns the assistant's text. Raises on transport/API
    failure; callers already wrap this in their own try/except with a fallback."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    body = {
        "model": os.getenv("LLM_MODEL_FAST", DEFAULT_MODEL),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        body["system"] = system
    resp = httpx.post(
        _URL, json=body, timeout=60.0,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    resp.raise_for_status()
    blocks = resp.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
