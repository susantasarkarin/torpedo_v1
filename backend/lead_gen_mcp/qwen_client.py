"""
Qwen-only LLM client for lead_gen_mcp.

lead_gen_mcp runs under its own venv (lead_gen_venv), separate from the main
backend/venv. bounce_handler.py and query_agent.py previously called the real
Anthropic API directly with their own anthropic.Anthropic client, hardcoding
a Claude model — a straight bypass of this codebase's Qwen-only policy.

This calls AWS Bedrock's `bedrock-runtime.converse` API directly via boto3 —
the SAME mechanism backend/leads/bedrock_client.py uses for the rest of the
codebase's Qwen calls (mail_pool_ai.py, bucket_classifier.py), authenticating
with plain AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY (already in backend/.env,
loaded via EnvironmentFile= in torpedo-lead-gen-mcp.service) via boto3's
standard credential chain.

Deliberately NOT using the "Bedrock Mantle" OpenAI-compatible endpoint that
ai_gateway.py/claude_gateway.py use — verified 2026-08-27 that Mantle's key
is invalid/unconfigured in this environment (401 invalid_api_key), while the
boto3 Converse path used here is proven working in production. Importing
backend.leads.bedrock_client directly was tried and rejected: backend/leads/
__init__.py eagerly imports the whole leads package (pulls in requests,
creates Mongo indexes as a side effect) just to reach one function — too much
surface area for this isolated venv, hence this self-contained duplicate of
just the Converse call.
"""

from __future__ import annotations

import os

import boto3

QWEN_MODEL = os.getenv("BEDROCK_MODEL_CHEAP", "qwen.qwen3-32b-v1:0")

_runtime_client = None


def _client():
    global _runtime_client
    if _runtime_client is None:
        _runtime_client = boto3.client(
            "bedrock-runtime", region_name=os.getenv("AWS_REGION", "ap-south-1"))
    return _runtime_client


def call_qwen(system: str, user: str, max_tokens: int = 1024,
              temperature: float = 0.3) -> str:
    """One Qwen call via AWS Bedrock's Converse API. Returns the assistant's
    text. Raises on transport/API failure — callers already wrap this in
    their own try/except with a fallback."""
    kwargs = {
        "modelId": QWEN_MODEL,
        "messages": [{"role": "user", "content": [{"text": user}]}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
    }
    if system:
        kwargs["system"] = [{"text": system}]

    response = _client().converse(**kwargs)
    content = response.get("output", {}).get("message", {}).get("content", [])
    return "".join(block.get("text", "") for block in content).strip()
