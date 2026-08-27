"""
Qwen-only LLM client for lead_gen_mcp.

lead_gen_mcp runs under its own venv (lead_gen_venv), separate from the main
backend/venv, and does not have the `openai` package installed — only
`anthropic` and `httpx`. Rather than add a new dependency or call Anthropic's
real API directly (both bounce_handler.py and query_agent.py previously did
the latter, hardcoding a Claude model), this makes a raw HTTP call to the
same AWS Bedrock Mantle OpenAI-compatible endpoint the rest of the codebase
uses (see backend/ai_governance/ai_gateway.py, backend/leads/bedrock_client.py)
so every LLM call in this codebase — this module included — resolves to Qwen.

Auth: AWS_BEARER_TOKEN_BEDROCK, loaded via the shared backend/.env
(EnvironmentFile= in torpedo-lead-gen-mcp.service).
"""

from __future__ import annotations

import json
import os
from typing import Optional

import httpx

BEDROCK_BASE_URL = os.getenv(
    "BEDROCK_MANTLE_BASE_URL", "https://bedrock-mantle.us-east-1.api.aws/v1")
QWEN_MODEL = os.getenv("BEDROCK_MODEL_CHEAP", "qwen.qwen3-32b-v1:0")


def _api_key() -> str:
    key = os.getenv("AWS_BEARER_TOKEN_BEDROCK", "") or os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError(
            "No Bedrock API key configured — set AWS_BEARER_TOKEN_BEDROCK")
    return key


def call_qwen(system: str, user: str, max_tokens: int = 1024,
              temperature: float = 0.3, timeout: float = 60.0) -> str:
    """One Qwen call via Bedrock Mantle's OpenAI-compatible chat/completions
    endpoint. Returns the assistant's text. Raises on transport/API failure —
    callers already wrap this in their own try/except with a fallback."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    response = httpx.post(
        f"{BEDROCK_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
        content=json.dumps({
            "model": QWEN_MODEL,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }),
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return (data["choices"][0]["message"]["content"] or "").strip()
