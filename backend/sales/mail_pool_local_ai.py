"""
Local-Qwen call path for sales/mail_pool_ai.py.

History (2026-09-19, one day, three revisions):
1. Bedrock (this pipeline's original provider) was confirmed unavailable in
   production (payment issue) with its DigitalOcean fallback unconfigured
   -- so this pipeline was silently doing nothing every beat tick. First
   fix: route to the local Qwen2.5-0.5B model (torpedo-v2-llm.service).
2. Real production calls against local Qwen2.5-0.5B measured 138-193+
   seconds per call and got real extraction errors (wrong incidence rate,
   dropped fields). Root cause, read from llama-server's own timing log
   during a live call: ~1.1 tokens/second -- but a same-VM, same-moment
   comparison against a 1.5B model showed 3x FASTER generation and 100%
   correct output, ruling out "model too big" and pointing instead at (a)
   0.5B being too weak a model for 12-field structured extraction
   regardless of speed, and (b) CPU/memory contention on this shared VM.
   Second fix: routed to the DigitalOcean-hosted fallback instead, on the
   (at-the-time reasonable) assumption that this VM simply couldn't run
   local inference for this task.
3. Re-litigated per explicit standing instruction: the SLM must stay LOCAL
   on this same VM; DO_INFERENCE_API_KEY was never meant to be "the
   solution", just evidence the architecture had drifted. Investigated
   further and found llama-server's systemd unit
   (/etc/systemd/system/torpedo-v2-llm.service) had a 768M memory cap sized
   for the 0.5B model with swap disabled -- likely why earlier local calls
   were so unreliable, independent of raw model capability. Raised the cap
   (768M -> 1.6G, documented in the unit's own comment, backup at
   torpedo-v2-llm.service.bak.20260919-114522) and swapped in the 1.5B
   model. A real production test afterward: 15.1 seconds, 7.96 tokens/sec,
   100% correct 12-field extraction, memory flat around 1.26GB throughout.
   Third fix, this revision: local Qwen2.5-1.5B is the pipeline's provider
   again -- this time on infrastructure actually sized for it.

Deliberately separate from both leads/bedrock_client.py's role-based
Bedrock/DO chain and leads/local_slm_client.py's classify() (hard-capped at
3 extra fields -- far too small for RFQ's schema). Reuses
local_slm_client.chat_json() as the transport primitive but does not share
its 12-second default timeout, which is tuned for bucket_classifier.py's
much shorter prompts.

Mirrors bedrock_client.py's converse_json_meta()/converse_json_object()
call shape so sales/mail_pool_ai.py's call sites barely change.

Standing rule: never depend on or fall back to AWS Bedrock, and never
depend on an external inference API (DigitalOcean/OpenAI/Anthropic/etc.)
as the primary path. This module has no such fallback by design -- a
failure here surfaces as LocalMailAIError, which mail_pool_ai.py wraps
into MailAIThrottled exactly as a Bedrock outage would, so the existing
"abort this batch, leave unmarked, retry next beat" behavior is unchanged.
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
    # Default of 90s carries ~6x headroom above the 15.1s real call
    # measured against the properly-provisioned 1.5B service -- see this
    # module's docstring for the memory-cap fix that made that possible.
    try:
        return float(os.getenv("MAIL_POOL_LOCAL_TIMEOUT_SECONDS", "90"))
    except (TypeError, ValueError):
        return 90.0


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
