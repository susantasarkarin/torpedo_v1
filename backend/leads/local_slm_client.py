"""
LOCAL SLM CLIENT -- Torpedo v1 Local Intelligence Layer, Phase 1
==================================================================

A standalone client for the local Qwen2.5-0.5B server (llama-server,
127.0.0.1:8003, --parallel 1) meant for callers OUTSIDE the Bedrock
cheap/smart role chain -- historical_classifier.py, reply_sentiment.py,
reply_intent.py, gemini_enrichment.py, lead_gen_mcp, email_crm_pipeline, and
any new SLM-opportunity work -- none of which touch bedrock_client.py's role
system today.

Deliberately separate from bedrock_client.py: that module owns the cheap/
smart role chain, Bedrock failover semantics and cost-audit logging for the
EXISTING Bedrock-routed callers, and none of that changes here (Bedrock and
the smart role remain untouched, per standing instruction). This client is
unconditionally local -- it has no role chain and no Bedrock fallback,
because Phase 2's migration targets are callers that have never gone through
bedrock_client.py at all.

Reuses, rather than reimplements:
  - do_inference_client.chat() for the actual HTTP transport (the same
    OpenAI-compatible POST /chat/completions bedrock_client._call_self_hosted()
    uses for the "cheap" role's local: entries).
  - local_llm_gate.acquire_local_llm_slot() for cross-process admission
    control -- MANDATORY on every call this module makes. There is exactly
    one inference slot on this server; every caller from every module must
    queue for it the same way, or the 2026-09-16 incident (VM load ~107)
    repeats itself at a larger scale as more callers are migrated in.

Evidence this module's design responds to (2026-09-17 testing session):
  - bucket_classifier.py's shape (short prompt, small fixed-vocabulary
    output) is the only workload proven reliable on this model/hardware.
  - Every wider/richer shape tested (mail_pool_ai.py, AIClassificationService,
    icp_query_ai.py, ingestion.py) timed out or failed outright.
  - A minimal 2-field binary-classification prompt returned syntactically
    valid JSON but the WRONG answer on real semantic content -- proving a
    narrow schema fixes format compliance, not accuracy. classify()'s output
    is a proposal for the caller's existing deterministic logic to validate,
    never a business verdict on its own.

classify() enforces the proven-safe shape structurally -- a short prompt, a
closed category enum, a confidence float, and at most a couple of extra small
fields -- raising before ever calling the model on a request shaped like the
operations already proven to fail, rather than quietly sending it anyway.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple

from leads import do_inference_client as _transport
from leads.local_llm_gate import LocalLLMQueueTimeout, acquire_local_llm_slot

logger = logging.getLogger("local_slm_client")

# 2026-09-19: the shared local model (torpedo-v2-llm.service, port 8003)
# was swapped from Qwen2.5-0.5B to Qwen2.5-1.5B after real testing showed
# the 0.5B model too weak for reliable structured extraction (see
# sales/mail_pool_local_ai.py's docstring). llama-server ignores the
# "model" field on a single-model server, so this is a label/log-accuracy
# fix, not a behavior change for existing callers.
DEFAULT_MODEL_NAME = "qwen2.5-1.5b-instruct"

# classify()'s structural guardrail: the proven-safe shape is a handful of
# fields, not the 15-field nested JSON that failed in mail_pool_ai.py. This is
# a hard cap, not a suggestion -- a task needing more fields should be split
# into multiple classify() calls (each validated independently) rather than
# grow one call past what's evidence-backed.
MAX_EXTRA_FIELDS = 3


class LocalSLMError(Exception):
    """Base class for every failure this module raises."""


class LocalSLMUnavailable(LocalSLMError):
    """Queue timeout, transport error, or HTTP failure -- the server didn't
    answer. Distinct from a malformed answer (LocalSLMMalformedResponse)."""


class LocalSLMMalformedResponse(LocalSLMError):
    """The server answered, but the content wasn't valid JSON or didn't match
    the requested shape. Callers must treat this the same as "no AI
    proposal" -- never coerce a partial/invalid answer into a business
    decision."""


@dataclass
class ClassificationResult:
    category: str
    confidence: float
    extra_fields: Dict[str, Any] = field(default_factory=dict)
    latency_seconds: float = 0.0
    raw_response: str = ""


def _inference_timeout_seconds() -> float:
    # Read live (not at import time) so tests and ops can override per call
    # without reloading the module.
    try:
        return float(os.getenv("LOCAL_LLM_INFERENCE_TIMEOUT_SECONDS", "12"))
    except (TypeError, ValueError):
        return 12.0


def _base_url() -> str:
    base = os.getenv(_transport.SELF_HOSTED_BASE_URL_ENV, "").strip()
    if not base:
        raise LocalSLMUnavailable(
            f"{_transport.SELF_HOSTED_BASE_URL_ENV} not set -- the local SLM "
            f"server has nowhere to call")
    return base


def _api_key() -> str:
    return os.getenv(_transport.SELF_HOSTED_KEY_ENV, "") or "not-required"


def _call(system: str, user: str, max_tokens: int,
          timeout: Optional[float]) -> Tuple[str, Dict[str, int], float]:
    """One gated call to the local server. Returns (text, usage, latency)."""
    effective_timeout = timeout if timeout is not None else _inference_timeout_seconds()
    base_url = _base_url()  # raises before touching the gate if unconfigured
    try:
        with acquire_local_llm_slot():
            return _transport.chat(
                DEFAULT_MODEL_NAME, system, user,
                max_tokens=max_tokens, temperature=0.0,
                base_url=base_url, api_key=_api_key(),
                timeout=effective_timeout,
            )
    except LocalLLMQueueTimeout as e:
        raise LocalSLMUnavailable(
            f"queue timeout waiting for a local inference slot: {e}") from e
    except _transport.DOInferenceError as e:
        # do_inference_client.py is a shared OpenAI-compatible transport
        # reused for both the real DigitalOcean endpoint AND this local
        # server (see its own module docstring) -- its exception messages
        # say "DigitalOcean" unconditionally, which is flatly wrong when
        # raised from here and actively misleading to debug (confirmed
        # live, 2026-09-19: local-path timeouts logged as "DigitalOcean
        # inference timed out" while nothing ever left this VM). Keep the
        # real detail (timeout duration, status code, etc.) but relabel
        # the provider name rather than silently relaying the wrong one.
        corrected = str(e).replace("DigitalOcean", "local model")
        raise LocalSLMUnavailable(
            f"local inference call to {base_url} failed "
            f"({type(e).__name__}): {corrected}") from e


def _strip_markdown_fences(text: str) -> str:
    clean = text.strip()
    if clean.startswith("```"):
        parts = clean.split("```")
        clean = parts[1] if len(parts) > 1 else parts[0]
        if clean.lower().startswith("json"):
            clean = clean[4:]
        clean = clean.strip()
    return clean


def chat_json(
    *,
    system: str,
    user: str,
    max_tokens: int = 512,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Lower-level primitive: one gated call to the local server, parsed as JSON
    with NO schema reshaping -- for a caller that already has its own proven
    prompt and its own response-validation logic (e.g. bucket_classifier.py,
    the one workload this session's testing validated as reliable on this
    model -- see docs/AI_VALIDATION_RESULTS.md) and just needs the admission-
    gated transport under it, not classify()'s guardrails built for a prompt
    written from scratch.

    Raises LocalSLMUnavailable / LocalSLMMalformedResponse exactly like
    classify() -- callers must treat both as "no AI proposal", same as any
    other call through this module.
    """
    text, _usage, _latency = _call(system, user, max_tokens, timeout)
    clean = _strip_markdown_fences(text)
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError as e:
        raise LocalSLMMalformedResponse(f"model did not return valid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise LocalSLMMalformedResponse(f"model returned non-object JSON: {parsed!r}")
    return parsed


def classify(
    *,
    task_description: str,
    categories: Sequence[str],
    content: str,
    extra_fields: Optional[Dict[str, str]] = None,
    max_tokens: int = 200,
    timeout: Optional[float] = None,
) -> ClassificationResult:
    """
    The one proven-safe shape: classify `content` into exactly one of
    `categories`, plus a confidence float, plus at most MAX_EXTRA_FIELDS small
    named fields (e.g. {"urgency": "high|medium|low"}).

    Raises ValueError before ever calling the model if the request doesn't fit
    this shape -- deliberate friction. A task needing more than this needs its
    own validation pass first (see
    docs/AI_WORKLOAD_SLM_SUITABILITY_MATRIX.md), not a bigger call through
    this function.

    Raises LocalSLMUnavailable (server didn't answer) or
    LocalSLMMalformedResponse (answered, but content/category/confidence
    didn't validate). Callers must treat both as "no AI proposal" -- fall back
    to the existing deterministic path, never retry-forever and never fall
    through to a business decision on an exception.
    """
    if not categories:
        raise ValueError("classify() requires a non-empty category list")
    extra_fields = extra_fields or {}
    if len(extra_fields) > MAX_EXTRA_FIELDS:
        raise ValueError(
            f"classify() caps extra fields at {MAX_EXTRA_FIELDS} (got "
            f"{len(extra_fields)}) -- this shape is unproven on the local "
            f"model; split into multiple classify() calls instead of growing "
            f"one call past what's been validated")

    schema_lines = [
        '  "category": one of ' + json.dumps(list(categories)),
        '  "confidence": 0.0-1.0',
    ]
    for name, description in extra_fields.items():
        schema_lines.append(f'  "{name}": {description}')
    schema = "{\n" + ",\n".join(schema_lines) + "\n}"

    user_prompt = (
        f"{task_description}\n\n"
        f"Content:\n{content}\n\n"
        f"Return JSON only, no explanation:\n{schema}"
    )
    system_prompt = "You are a precise classifier. Follow the schema exactly."

    text, usage, latency = _call(system_prompt, user_prompt, max_tokens, timeout)

    clean = _strip_markdown_fences(text)
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError as e:
        raise LocalSLMMalformedResponse(f"model did not return valid JSON: {e}") from e

    if not isinstance(parsed, dict):
        raise LocalSLMMalformedResponse(f"model returned non-object JSON: {parsed!r}")

    category = parsed.get("category")
    if category not in categories:
        raise LocalSLMMalformedResponse(
            f"model returned category {category!r}, not one of {list(categories)}")

    confidence = parsed.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) \
            or not (0.0 <= confidence <= 1.0):
        raise LocalSLMMalformedResponse(f"model returned invalid confidence: {confidence!r}")

    extra = {k: parsed[k] for k in extra_fields if k in parsed}

    return ClassificationResult(
        category=category, confidence=float(confidence), extra_fields=extra,
        latency_seconds=latency, raw_response=text,
    )
