"""
DigitalOcean serverless inference (GradientAI) — dumb HTTP transport.

This is the FALLBACK provider behind AWS Bedrock. It exists because every
Bedrock model shares one credential, so model-level failover gave no
protection at all: when the Bedrock API key expired on 2026-08-09 the whole
qwen -> deepseek -> haiku chain died together and lead classification stopped
silently for a day. A fallback is only worth having if it fails independently
of the thing it is backing up, which means a different provider, not a
different model on the same account.

Scope is deliberately narrow. This module knows how to make one chat call and
report what happened; it does NOT own retries, chains, or the cheap/smart role
mapping — bedrock_client owns all of that, and remains the only module that
names model IDs.

The API is OpenAI-compatible (POST /chat/completions), so this is plain
`requests` rather than another SDK dependency.

Config:
    DO_INFERENCE_API_KEY    model access key from the DO GenAI console (required)
    DO_INFERENCE_BASE_URL   default https://inference.do-ai.run/v1
    DO_INFERENCE_TIMEOUT    per-request seconds, default 60
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("do_inference_client")

DEFAULT_BASE_URL = "https://inference.do-ai.run/v1"


class DOInferenceError(RuntimeError):
    """DigitalOcean inference call failed."""


class DOAuthError(DOInferenceError):
    """Key missing, invalid or lacking access to the model."""


class DOThrottled(DOInferenceError):
    """Rate limited or temporarily unavailable — worth retrying."""


class DOModelNotFound(DOInferenceError):
    """The requested model slug does not exist on this account."""


def api_key() -> str:
    return (
        os.getenv("DO_INFERENCE_API_KEY")
        or os.getenv("DIGITALOCEAN_INFERENCE_KEY")
        or ""
    ).strip()


def base_url() -> str:
    return (os.getenv("DO_INFERENCE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def timeout_seconds() -> int:
    try:
        return max(5, int(os.getenv("DO_INFERENCE_TIMEOUT", "") or 60))
    except (TypeError, ValueError):
        return 60


def is_configured() -> bool:
    """True when a key is present. Checked before the fallback is attempted so
    an unconfigured fallback is reported as such instead of as an auth error."""
    return bool(api_key())


def _headers() -> Dict[str, str]:
    key = api_key()
    if not key:
        raise DOAuthError(
            "DO_INFERENCE_API_KEY is not set — the DigitalOcean fallback is "
            "unconfigured. Create a model access key in the DO GenAI console."
        )
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _raise_for_status(response: requests.Response, model: str) -> None:
    """Map an HTTP status onto an exception the caller's chain understands."""
    if response.status_code < 400:
        return

    body = response.text[:300]
    if response.status_code in (401, 403):
        raise DOAuthError(f"DigitalOcean rejected the API key ({response.status_code}): {body}")
    if response.status_code == 404:
        raise DOModelNotFound(f"model {model!r} not found on this DO account: {body}")
    if response.status_code == 429 or response.status_code >= 500:
        raise DOThrottled(f"DigitalOcean unavailable ({response.status_code}): {body}")
    raise DOInferenceError(f"DigitalOcean inference failed ({response.status_code}): {body}")


def chat(model: str, system: str, user: str,
         max_tokens: int = 1024, temperature: float = 0.0
         ) -> Tuple[str, Dict[str, int], float]:
    """One chat completion. Returns (text, usage, latency_seconds).

    `usage` is normalised to Bedrock's key names (inputTokens/outputTokens/
    totalTokens) so the cost-audit log line and meta dict in bedrock_client
    read identically whichever provider answered.
    """
    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    started = time.monotonic()
    try:
        response = requests.post(
            f"{base_url()}/chat/completions",
            headers=_headers(),
            json=payload,
            timeout=timeout_seconds(),
        )
    except requests.Timeout as e:
        raise DOThrottled(f"DigitalOcean inference timed out after {timeout_seconds()}s") from e
    except requests.RequestException as e:
        raise DOInferenceError(f"DigitalOcean inference transport error: {e}") from e

    latency = time.monotonic() - started
    _raise_for_status(response, model)

    try:
        data = response.json()
    except ValueError as e:
        raise DOInferenceError(f"DigitalOcean returned non-JSON: {response.text[:200]}") from e

    choices = data.get("choices") or []
    if not choices:
        raise DOInferenceError(f"DigitalOcean returned no choices: {str(data)[:200]}")

    text = ((choices[0].get("message") or {}).get("content") or "").strip()

    raw_usage = data.get("usage") or {}
    usage = {
        "inputTokens": raw_usage.get("prompt_tokens"),
        "outputTokens": raw_usage.get("completion_tokens"),
        "totalTokens": raw_usage.get("total_tokens"),
    }
    return text, usage, latency


def list_models() -> List[str]:
    """Model slugs available to this account.

    Exists because DO's catalogue slugs are account- and time-dependent, so the
    defaults in bedrock_client are a starting point to be confirmed against a
    real key rather than something to trust blindly. Used by the health check.
    """
    try:
        response = requests.get(
            f"{base_url()}/models", headers=_headers(), timeout=timeout_seconds())
    except requests.RequestException as e:
        raise DOInferenceError(f"could not list DigitalOcean models: {e}") from e

    _raise_for_status(response, "<list>")
    data = response.json()
    return sorted(
        m.get("id") for m in (data.get("data") or []) if m.get("id")
    )


def health() -> Dict[str, Any]:
    """Cheap diagnostic for the fallback path: configured? reachable? models?"""
    if not is_configured():
        return {"configured": False, "reachable": False,
                "error": "DO_INFERENCE_API_KEY not set"}
    try:
        models = list_models()
        return {"configured": True, "reachable": True,
                "model_count": len(models), "models": models[:25]}
    except Exception as e:
        return {"configured": True, "reachable": False, "error": str(e)}
