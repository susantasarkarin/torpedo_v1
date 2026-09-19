"""
Local-Qwen call path for sales/mail_pool_ai.py.

Deliberately separate from both leads/bedrock_client.py's role-based
Bedrock/DO chain and leads/local_slm_client.py's classify() (hard-capped at
3 extra fields -- far too small for RFQ's schema). Reuses
local_slm_client.chat_json() as the transport primitive but does not share
its 12-second default timeout: docs/LOCAL_SLM_CHEAP_ROLE_AUDIT.md found
mail_pool_ai's prompt (full email body + a 15-field JSON schema) takes
21.5-40+ seconds against the local model in real testing, far past the
timeout tuned for bucket_classifier.py's short prompts. Changing that
shared default would risk regressing every other chat_json()/classify()
caller; this module gets its own env-driven timeout instead.

Mirrors bedrock_client.py's converse_json_meta()/converse_json_object()
call shape so sales/mail_pool_ai.py's call sites barely change -- only the
import and the exception type being caught differ.

Standing rule: never depend on or fall back to AWS Bedrock. This module has
no Bedrock fallback by design -- a failure here surfaces as
LocalMailAIError, which mail_pool_ai.py wraps into MailAIThrottled exactly
as a Bedrock outage would, so the existing "abort this batch, leave
unmarked, retry next beat" behavior is unchanged.
"""

import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

from leads import local_slm_client as _slm

logger = logging.getLogger(__name__)

MODEL_ID = _slm.DEFAULT_MODEL_NAME


def _timeout_seconds() -> float:
    # Read live, not at import time, so ops/tests can override per call.
    try:
        return float(os.getenv("MAIL_POOL_LOCAL_TIMEOUT_SECONDS", "60"))
    except (TypeError, ValueError):
        return 60.0


class LocalMailAIError(Exception):
    """The local model didn't answer, or never returned valid JSON even
    after one retry. Callers must treat this exactly like a Bedrock
    outage -- leave the item unmarked for the next run, never coerce a
    missing/malformed answer into a decision."""


def _reminder_user_prompt(user: str) -> str:
    return (user + "\n\nReturn ONLY valid JSON matching the shape above. "
            "No markdown fences, no commentary.")


def converse_json_meta(
    role: str, system: str, user: str,
    max_tokens: int = 1024, temperature: float = 0.0,
) -> Tuple[Any, Dict[str, Any]]:
    """
    Same call shape as bedrock_client.converse_json_meta -- `role` and
    `temperature` are accepted for interface compatibility but unused
    (there is exactly one local model, always called at temperature 0).

    One retry with a JSON-format reminder on a malformed response --
    chat_json() itself does not retry, and this model drifts from the
    requested shape more often than the models bedrock_client normally
    routes to.
    """
    timeout = _timeout_seconds()
    t0 = time.monotonic()
    try:
        parsed = _slm.chat_json(system=system, user=user, max_tokens=max_tokens,
                                timeout=timeout)
    except _slm.LocalSLMMalformedResponse:
        logger.warning("[mail-pool-local-ai] malformed JSON, retrying once with a reminder")
        try:
            parsed = _slm.chat_json(
                system=system, user=_reminder_user_prompt(user),
                max_tokens=max_tokens, timeout=timeout)
        except _slm.LocalSLMError as e:
            raise LocalMailAIError(f"malformed JSON persisted after retry: {e}") from e
    except _slm.LocalSLMUnavailable as e:
        raise LocalMailAIError(f"local model unavailable: {e}") from e
    latency = time.monotonic() - t0
    meta = {
        "model_id": MODEL_ID, "provider": "local", "role": role,
        "fallback_position": 0, "is_fallback": False,
        "input_tokens": None, "output_tokens": None, "total_tokens": None,
        "latency_s": latency,
    }
    return parsed, meta


def converse_json_object(role: str, system: str, user: str, **kw) -> Optional[Dict[str, Any]]:
    value, _meta = converse_json_meta(role, system, user, **kw)
    return value if isinstance(value, dict) else None
