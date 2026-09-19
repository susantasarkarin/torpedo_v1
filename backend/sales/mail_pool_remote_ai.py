"""
AI call path for sales/mail_pool_ai.py.

History (2026-09-19, same day, two revisions):
1. Bedrock (this pipeline's original provider) was confirmed unavailable in
   production (payment issue) with its DigitalOcean fallback unconfigured
   (DOFallbackNotConfigured in live logs) -- so this pipeline was silently
   doing nothing every beat tick. First fix: route to the local Qwen model
   (torpedo-v2-llm.service) instead.
2. Real production calls against local Qwen measured 138-193+ seconds per
   call and repeatedly hit even a 180s timeout. The root cause, read
   straight from llama-server's own timing log during a live failed call:
   generation speed of ~1.1 tokens/second -- severe CPU starvation from
   sharing this VM with mongod/the API/celery workers, not a prompt-size
   problem (confirmed: trimming the prompt made no measurable difference).
   No timeout is large enough to make 1.1 tok/s viable for a real-time-ish
   pipeline. Second fix, this revision: route to the DigitalOcean-hosted
   fallback instead -- the exact model (alibaba-qwen3-32b) this pipeline's
   own Bedrock fallback chain already pointed at
   (BEDROCK_FALLBACKS_CHEAP=do:alibaba-qwen3-32b in celery_app.py), just
   reached directly rather than through bedrock_client's Bedrock-first
   chain. Hosted off this VM, so it isn't competing for the same starved
   CPU, and it's the same model class (32B) this pipeline was originally
   built and proven against via Bedrock.

Deliberately separate from leads/bedrock_client.py's role-based Bedrock/DO
chain (this never attempts Bedrock first, per standing rule) and from
leads/local_slm_client.py (that module is for the local self-hosted model
specifically, with its own concurrency gate that doesn't apply to a remote
host). Reuses leads/do_inference_client.py as the transport primitive --
the same OpenAI-compatible client bedrock_client's `do:` chain entries use.

Mirrors bedrock_client.py's converse_json_meta()/converse_json_object()
call shape so sales/mail_pool_ai.py's call sites barely change.

Standing rule: never depend on or fall back to AWS Bedrock. This module
never attempts Bedrock at any point.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

from leads import do_inference_client as _transport

logger = logging.getLogger(__name__)

# The same DO model slug this pipeline's own (now-bypassed) Bedrock
# fallback chain already pointed at -- see this module's docstring.
MODEL_ID = os.getenv("MAIL_POOL_REMOTE_MODEL", "alibaba-qwen3-32b")


def _timeout_seconds() -> float:
    # DO_INFERENCE_TIMEOUT (default 60s in do_inference_client) is sized
    # for a real hosted provider, not a starved local box -- no
    # module-specific override needed here, but read live in case ops sets
    # MAIL_POOL_REMOTE_TIMEOUT_SECONDS to something larger for this
    # module's particularly large prompt.
    try:
        override = os.getenv("MAIL_POOL_REMOTE_TIMEOUT_SECONDS")
        return float(override) if override else _transport.timeout_seconds()
    except (TypeError, ValueError):
        return float(_transport.timeout_seconds())


class RemoteMailAIError(Exception):
    """The DO-hosted model didn't answer, or never returned valid JSON even
    after one retry. Callers must treat this exactly like a Bedrock outage
    -- leave the item unmarked for the next run, never coerce a
    missing/malformed answer into a decision."""


def _strip_markdown_fences(text: str) -> str:
    clean = text.strip()
    if clean.startswith("```"):
        parts = clean.split("```")
        clean = parts[1] if len(parts) > 1 else parts[0]
        if clean.lower().startswith("json"):
            clean = clean[4:]
        clean = clean.strip()
    return clean


def _reminder_user_prompt(user: str) -> str:
    return (user + "\n\nReturn ONLY valid JSON matching the shape above. "
            "No markdown fences, no commentary.")


def _call_and_parse(system: str, user: str, max_tokens: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if not _transport.is_configured():
        raise RemoteMailAIError(
            "DO_INFERENCE_API_KEY is not set -- the DigitalOcean fallback "
            "this pipeline now depends on is unconfigured. Create a model "
            "access key in the DO GenAI console.")
    try:
        text, usage, latency = _transport.chat(
            MODEL_ID, system, user, max_tokens=max_tokens, temperature=0.0,
            timeout=_timeout_seconds())
    except _transport.DOInferenceError as e:
        raise RemoteMailAIError(f"DigitalOcean call failed: {e}") from e
    clean = _strip_markdown_fences(text)
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, dict):
        return None, {"usage": usage, "latency": latency}
    return parsed, {"usage": usage, "latency": latency}


def converse_json_meta(
    role: str, system: str, user: str,
    max_tokens: int = 1024, temperature: float = 0.0,
) -> Tuple[Any, Dict[str, Any]]:
    """
    Same call shape as bedrock_client.converse_json_meta -- `role` and
    `temperature` are accepted for interface compatibility but unused
    (temperature is always 0 for this pipeline's extraction calls).

    One retry with a JSON-format reminder on a malformed response.
    """
    parsed, info = _call_and_parse(system, user, max_tokens)
    if parsed is None:
        logger.warning("[mail-pool-remote-ai] malformed JSON, retrying once with a reminder")
        parsed, info = _call_and_parse(system, _reminder_user_prompt(user), max_tokens)
        if parsed is None:
            raise RemoteMailAIError("malformed JSON persisted after retry")
    usage = info["usage"]
    meta = {
        "model_id": MODEL_ID, "provider": "digitalocean", "role": role,
        "fallback_position": 0, "is_fallback": False,
        "input_tokens": usage.get("inputTokens"),
        "output_tokens": usage.get("outputTokens"),
        "total_tokens": usage.get("totalTokens"),
        "latency_s": info["latency"],
    }
    return parsed, meta


def converse_json_object(role: str, system: str, user: str, **kw) -> Optional[Dict[str, Any]]:
    value, _meta = converse_json_meta(role, system, user, **kw)
    return value if isinstance(value, dict) else None
