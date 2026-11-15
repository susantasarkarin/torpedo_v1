"""
Mail-pool LLM shim: the bedrock_client-shaped call interface
(converse_json_meta / converse_json_object) that sales/mail_pool_ai.py was
written against, backed by platform_core.ladder (Haiku, then Sonnet; schema
validated, budget and usage logged by the ladder).

History: this shape first wrapped Bedrock Converse, then (2026-09) a local
Qwen llama-server, which was retired on 2026-11-15. `role` and `temperature`
are accepted for interface compatibility only.
"""
import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

MODEL_ID = "ladder"


class MailAIError(Exception):
    """No tier produced valid JSON. Callers treat this like a provider
    outage: leave the item unmarked for the next run, never coerce a
    missing/malformed answer into a decision."""


LocalMailAIError = MailAIError  # old name, kept for callers


def _check(data: Any):
    return [] if isinstance(data, (dict, list)) else ["response was not a JSON object"]


def converse_json_meta(
    role: str, system: str, user: str,
    max_tokens: int = 1024, temperature: float = 0.0,
) -> Tuple[Any, Dict[str, Any]]:
    from platform_core.ladder import escalate_json
    t0 = time.monotonic()
    data, tier, attempts = escalate_json(
        task="mail_pool", system=system, user=user, schema=None,
        check=_check, max_tokens=max_tokens,
    )
    if data is None:
        problems = [p for a in attempts for p in (a.get("problems") or [])][:3]
        raise MailAIError("no valid AI answer: " + "; ".join(str(p) for p in problems))
    meta = {
        "model_id": tier or MODEL_ID, "provider": "anthropic", "role": role,
        "fallback_position": max(len(attempts) - 1, 0), "is_fallback": len(attempts) > 1,
        "input_tokens": None, "output_tokens": None, "total_tokens": None,
        "latency_s": time.monotonic() - t0,
    }
    return data, meta


def converse_json_object(role: str, system: str, user: str, **kw) -> Optional[Dict[str, Any]]:
    value, _meta = converse_json_meta(role, system, user, **kw)
    return value if isinstance(value, dict) else None
