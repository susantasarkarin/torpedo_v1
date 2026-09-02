"""
BEDROCK CLIENT — the ONLY module permitted to import boto3 for Bedrock or to
reference a model ID.
=============================================================================

All AI access goes through the Converse API (`bedrock-runtime.converse`), which
normalizes request/response shape across providers. `invoke_model` is never
used, and no provider SDK (Anthropic, OpenAI) is called directly.

Roles, not model names, are what callers choose:

    role="cheap"  -> BEDROCK_MODEL_CHEAP   (default qwen.qwen3-32b-v1:0)
                     query generation, search-result extraction, enrichment,
                     first-pass bucket classification
    role="smart"  -> BEDROCK_MODEL_SMART   (default qwen.qwen3-32b-v1:0)
                     email writing, second-opinion classification

Swapping either model to e.g. Nova Lite or Claude Haiku requires changing only
the environment variable.

Each role fails over ACROSS PROVIDERS: AWS Bedrock primary, DigitalOcean
serverless inference (GradientAI) as the fallback. A model returning a "not
usable" error (validation, access denied, not found, bad key) is skipped and
the next entry answers. Throttles still retry on the same model first.

    cheap:  bedrock qwen3-32b  ->  do:alibaba-qwen3-32b
    smart:  bedrock qwen3-32b  ->  do:alibaba-qwen3-32b

Chain entries prefixed `do:` are routed to do_inference_client; everything else
goes to Bedrock. This module still owns every model ID either way.

This replaced a three-deep Bedrock-only chain (qwen -> deepseek -> haiku), which
protected nothing: all Bedrock models share one account credential, so when the
Bedrock API key expired on 2026-08-09 the entire chain failed with the same
error in under a second and lead classification stopped silently for a day.
Failover only buys anything across a failure boundary — hence a second provider
rather than a third model.

Configuration (env only — no credentials in code, standard chain applies):
    BEDROCK_MODEL_CHEAP       default qwen.qwen3-32b-v1:0
    BEDROCK_MODEL_SMART       default qwen.qwen3-32b-v1:0
    BEDROCK_FALLBACKS_CHEAP   comma-separated; default do:alibaba-qwen3-32b
    BEDROCK_FALLBACKS_SMART   comma-separated; default do:alibaba-qwen3-32b
    AWS_REGION                default ap-south-1  (Mumbai)
    BEDROCK_MAX_RETRIES       default 3
    BEDROCK_FAILOVER_MEMORY_SECONDS  default 300
    DO_INFERENCE_API_KEY      DigitalOcean model access key (fallback; required
                              for the fallback to be usable at all)
    DO_INFERENCE_BASE_URL     default https://inference.do-ai.run/v1

Bedrock auth note: Bedrock here authenticates via AWS_BEARER_TOKEN_BEDROCK (a
Bedrock API key) when present, falling back to the standard SigV4 credential
chain. Bedrock API keys EXPIRE; the IAM user currently in AWS_ACCESS_KEY_ID
(ses-api-mailer) has no Bedrock permissions, so when the key lapses there is no
SigV4 path behind it. That is exactly the failure the DigitalOcean fallback now
covers.

Single-model policy: Qwen serves BOTH roles on BOTH providers. The cheap/smart
split is kept as an interface so callers never name a model and the two can be
pointed at different models later via env, but today they resolve to the same
one. Note this weakens the confidence-based escalation in bucket_classifier —
escalating "cheap" to "smart" now re-asks the same model rather than a stronger
one (see that module's note).

Thinking mode is deliberately NOT enabled. Qwen3 supports a reasoning mode whose
tokens bill as output and are wasted on short classification and email tasks, so
no `additionalModelRequestFields` reasoning config is ever sent.
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bedrock_client")

# ============================================================
# CONFIG
# ============================================================

DEFAULT_MODEL_CHEAP = "qwen.qwen3-32b-v1:0"
DEFAULT_MODEL_SMART = "qwen.qwen3-32b-v1:0"
DEFAULT_REGION = "ap-south-1"

# Fallback chain: AWS Bedrock primary, DigitalOcean serverless inference as the
# fallback. Entries prefixed `do:` are routed to do_inference_client instead of
# Bedrock (see _call_converse).
#
# This used to be three Bedrock models deep (qwen -> deepseek -> haiku) and that
# protected nothing. Every Bedrock model authenticates with the same account
# credential, so when the Bedrock API key expired on 2026-08-09 all three failed
# with the identical error inside 0.6s and lead classification stopped dead for a
# day. Failover is only meaningful across a failure boundary; one model per
# provider, two providers, is strictly stronger than three models on one account.
#
# Qwen only, by policy — both roles, both providers. The DO slug below is the
# closest Qwen match to the Bedrock primary. DO's catalogue is account-specific,
# so confirm it against a real key with `do_inference_client.list_models()` (see
# health()) and override via BEDROCK_FALLBACKS_CHEAP / BEDROCK_FALLBACKS_SMART
# if the slug differs.
DO_MODEL_CHEAP = "do:alibaba-qwen3-32b"
DO_MODEL_SMART = "do:alibaba-qwen3-32b"

DEFAULT_FALLBACKS_CHEAP = (DO_MODEL_CHEAP,)
DEFAULT_FALLBACKS_SMART = (DO_MODEL_SMART,)

# Marks a chain entry as belonging to the DigitalOcean provider.
DO_PREFIX = "do:"

# Self-hosted / any OpenAI-compatible endpoint. Same transport as `do:`, but
# reads its own base URL and key, so a local Qwen and the DigitalOcean
# fallback can be configured independently and used in the same chain:
#
#     BEDROCK_MODEL_CHEAP=local:qwen3-32b
#     BEDROCK_FALLBACKS_CHEAP=qwen.qwen3-32b-v1:0,do:alibaba-qwen3-32b
#
# i.e. try your own box first, fall back to Bedrock, then to DigitalOcean.
LOCAL_PREFIX = "local:"

VALID_ROLES = ("cheap", "smart")

# Throttling / transient error codes worth retrying on the SAME model.
_RETRYABLE_CODES = {
    "ThrottlingException", "TooManyRequestsException",
    "ServiceQuotaExceededException", "ModelTimeoutException",
    "InternalServerException", "ServiceUnavailableException",
    # DigitalOcean equivalents (429 / 5xx / timeout) — same treatment.
    "DOThrottled",
}

# Errors meaning "this model is not usable" — fail over to the next model
# immediately rather than burning the retry budget on a model that will keep
# rejecting us. ValidationException covers both "model needs an inference
# profile" and the account-level "Operation not allowed".
_FAILOVER_CODES = {
    "ValidationException", "AccessDeniedException",
    "ResourceNotFoundException", "ModelNotReadyException",
    # DigitalOcean: bad key, wrong model slug, or an unclassified failure.
    # Nothing to gain from retrying any of these on the same model.
    "DOAuthError", "DOModelNotFound", "DOInferenceError",
    "DOFallbackNotConfigured",
}

# How long to keep using a fallback after the primary fails, before probing the
# primary again. Without this, every single call re-tries a dead primary first
# and pays its latency — meaningful when draining thousands of senders.
FAILOVER_MEMORY_SECONDS = int(os.getenv("BEDROCK_FAILOVER_MEMORY_SECONDS", "300"))

# role -> (model_id, monotonic_deadline). Set when a model fails over.
_demoted: Dict[str, float] = {}


def get_region() -> str:
    return os.getenv("AWS_REGION") or DEFAULT_REGION


def _env_chain(var: str, default: Tuple[str, ...]) -> List[str]:
    """
    Read a comma-separated model list from the environment.

    Unset falls back to the built-in default; explicitly set-but-empty means
    "no fallbacks" and must be honoured. Testing truthiness would conflate the
    two and silently re-enable the defaults for an operator who deliberately
    turned fallbacks off.
    """
    raw = os.getenv(var)
    if raw is None:
        return list(default)
    return [m.strip() for m in raw.split(",") if m.strip()]


def model_for_role(role: str) -> str:
    """
    Resolve a role to its primary model ID.

    Kept for callers and tests that want the configured primary. The runtime
    path uses models_for_role(), which returns the whole fallback chain.
    """
    if role == "cheap":
        return os.getenv("BEDROCK_MODEL_CHEAP") or DEFAULT_MODEL_CHEAP
    if role == "smart":
        return os.getenv("BEDROCK_MODEL_SMART") or DEFAULT_MODEL_SMART
    raise ValueError(f"unknown role {role!r}; expected one of {VALID_ROLES}")


def models_for_role(role: str) -> List[str]:
    """
    Ordered model chain for a role: primary first, then fallbacks.

    Configure with BEDROCK_MODEL_CHEAP / BEDROCK_MODEL_SMART for the primary
    and BEDROCK_FALLBACKS_CHEAP / BEDROCK_FALLBACKS_SMART (comma-separated) for
    the rest. Duplicates are dropped so a fallback that equals the primary
    doesn't get tried twice.
    """
    primary = model_for_role(role)
    if role == "cheap":
        fallbacks = _env_chain("BEDROCK_FALLBACKS_CHEAP", DEFAULT_FALLBACKS_CHEAP)
    else:
        fallbacks = _env_chain("BEDROCK_FALLBACKS_SMART", DEFAULT_FALLBACKS_SMART)

    chain: List[str] = []
    for model_id in [primary, *fallbacks]:
        if model_id and model_id not in chain:
            chain.append(model_id)

    # A model that recently failed over goes to the back of the chain until its
    # cooldown expires — we still keep it as a candidate rather than dropping
    # it, so a fully-broken chain degrades to "try everything" not "try nothing".
    now = time.monotonic()
    healthy = [m for m in chain if _demoted.get(m, 0.0) <= now]
    demoted = [m for m in chain if _demoted.get(m, 0.0) > now]
    return healthy + demoted


def _demote(model_id: str) -> None:
    _demoted[model_id] = time.monotonic() + FAILOVER_MEMORY_SECONDS


def max_retries() -> int:
    try:
        return max(1, int(os.getenv("BEDROCK_MAX_RETRIES", "") or 3))
    except (TypeError, ValueError):
        return 3


def config_summary() -> Dict[str, Any]:
    """Effective routing config. Includes whether the DigitalOcean fallback is
    actually usable — a chain that lists a fallback with no key configured is
    the same as having no fallback, and that should be visible here rather than
    discovered when the primary fails."""
    try:
        from leads.do_inference_client import is_configured as _do_configured
    except ImportError:  # pragma: no cover - DO client not present
        _do_configured = lambda: False  # noqa: E731

    return {
        "primary_provider": "bedrock",
        "fallback_provider": "digitalocean",
        "region": get_region(),
        "model_cheap": model_for_role("cheap"),
        "model_smart": model_for_role("smart"),
        "chain_cheap": models_for_role("cheap"),
        "chain_smart": models_for_role("smart"),
        "do_fallback_configured": bool(_do_configured()),
        "max_retries": max_retries(),
        "failover_memory_seconds": FAILOVER_MEMORY_SECONDS,
    }


# ============================================================
# ERRORS
# ============================================================

class BedrockError(RuntimeError):
    """Bedrock call failed (transport, auth, throttling exhausted)."""


class ModelAccessError(BedrockError):
    """A configured model is not accessible in the configured region."""


class DOFallbackNotConfigured(BedrockError):
    """The DigitalOcean fallback was reached but has no API key set."""


class JSONParseError(ValueError):
    """Model output was not valid JSON."""


# ============================================================
# CLIENTS (lazy — never built at import time)
# ============================================================

_runtime_client = None
_control_client = None


def _get_runtime_client():
    global _runtime_client
    if _runtime_client is None:
        import boto3
        _runtime_client = boto3.client("bedrock-runtime", region_name=get_region())
    return _runtime_client


def _get_control_client():
    global _control_client
    if _control_client is None:
        import boto3
        _control_client = boto3.client("bedrock", region_name=get_region())
    return _control_client


def reset_clients() -> None:
    """Drop cached clients (used after region/config changes, and by tests)."""
    global _runtime_client, _control_client
    _runtime_client = None
    _control_client = None


# ============================================================
# STARTUP VALIDATION
# ============================================================

def validate_model_access(roles: Tuple[str, ...] = VALID_ROLES) -> Dict[str, str]:
    """
    Verify every configured model is actually available in this region.
    Call once at process startup. Fails fast and loudly — a missing model
    should stop the run, not surface as a wall of per-lead errors.

    Returns {role: model_id} on success.
    """
    region = get_region()
    wanted = {role: model_for_role(role) for role in roles}

    def _fallback_can_serve() -> bool:
        from leads.do_inference_client import is_configured
        return is_configured()

    try:
        response = _get_control_client().list_foundation_models()
    except Exception as e:
        # Bedrock being unreachable is no longer fatal IF DigitalOcean can take
        # the traffic — that is the entire point of a cross-provider fallback.
        # Warn loudly (running entirely on the fallback is a degraded state
        # someone needs to fix) but let the run proceed.
        if _fallback_can_serve():
            logger.warning(
                "Bedrock unavailable in %s (%s) — continuing on the DigitalOcean "
                "fallback. Primary is DEGRADED; fix Bedrock access.", region, e)
            return wanted
        raise ModelAccessError(
            f"Could not list Bedrock foundation models in {region}: {e}. "
            f"Check AWS credentials and that Bedrock is available in this region. "
            f"The DigitalOcean fallback is also unconfigured (set DO_INFERENCE_API_KEY), "
            f"so there is no path to a model at all."
        ) from e

    available = set()
    for summary in response.get("modelSummaries", []):
        model_id = summary.get("modelId")
        if model_id:
            available.add(model_id)
            # Bedrock lists some models without the version suffix.
            available.add(model_id.split(":")[0])

    missing = {
        role: model for role, model in wanted.items()
        if model not in available and model.split(":")[0] not in available
    }
    if missing and _fallback_can_serve():
        logger.warning(
            "Bedrock model(s) not accessible in %s: %s — continuing on the "
            "DigitalOcean fallback. Primary is DEGRADED.", region, missing)
        return wanted
    if missing:
        raise ModelAccessError(
            "Model(s) not accessible in region "
            f"{region}: {missing}. Enable model access in the Bedrock console "
            "(Model access -> Manage model access), or correct "
            "BEDROCK_MODEL_CHEAP / BEDROCK_MODEL_SMART. "
            f"Models visible in {region}: {sorted(available)[:15]}..."
        )

    logger.info("Bedrock model access verified in %s: %s", region, wanted)
    return wanted


# ============================================================
# STRICT JSON
# ============================================================

_FENCE_OPEN = re.compile(r"^\s*```(?:json|JSON)?\s*", re.MULTILINE)
_FENCE_CLOSE = re.compile(r"\s*```\s*$", re.MULTILINE)


def parse_json_strict(text: str) -> Any:
    """
    Parse model output as JSON. Strips accidental markdown fences and any
    prose wrapped around a single JSON value. Raises JSONParseError on
    anything it cannot parse — callers retry once with a reminder rather than
    silently accepting garbage.
    """
    if text is None or not str(text).strip():
        raise JSONParseError("empty model response")

    cleaned = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", str(text))).strip()

    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        pass

    # Trailing commentary after a valid value is common; try the first
    # balanced object or array span.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except (json.JSONDecodeError, TypeError):
                continue

    raise JSONParseError(
        f"model returned invalid JSON ({len(cleaned)} chars): {cleaned[:200]!r}")


JSON_REMINDER = (
    "\n\nYour previous response was not valid JSON. "
    "Return ONLY valid JSON. No markdown fences. No preamble. No commentary."
)


# ============================================================
# CONVERSE
# ============================================================

def is_do_model(model_id: str) -> bool:
    return str(model_id or "").startswith(DO_PREFIX)


def is_local_model(model_id: str) -> bool:
    """True for a `local:`-prefixed entry — any OpenAI-compatible endpoint."""
    return str(model_id or "").startswith(LOCAL_PREFIX)


def provider_of(model_id: str) -> str:
    if is_local_model(model_id):
        return "self_hosted"
    return "digitalocean" if is_do_model(model_id) else "bedrock"


def _call_do(model_id: str, system: str, user: str,
             max_tokens: int, temperature: float) -> Tuple[str, Dict[str, int], float]:
    """Route a `do:`-prefixed chain entry to DigitalOcean."""
    from leads.do_inference_client import chat, is_configured

    if not is_configured():
        # Distinct from an auth failure: nothing is misconfigured upstream,
        # the fallback simply has no key yet. Its own type so the code shows up
        # verbatim in the "all N models failed" summary.
        raise DOFallbackNotConfigured(
            "DO_INFERENCE_API_KEY not set — DigitalOcean fallback unavailable")

    return chat(model_id[len(DO_PREFIX):], system, user, max_tokens, temperature)


def _call_self_hosted(model_id: str, system: str, user: str,
                      max_tokens: int, temperature: float
                      ) -> Tuple[str, Dict[str, int], float]:
    """
    Route a `local:`-prefixed entry to a self-hosted OpenAI-compatible server.

    Reuses do_inference_client's transport — it is a plain POST to
    /chat/completions, which is what vLLM, Ollama, llama.cpp and LM Studio all
    speak — but with its own base URL and key so the two providers stay
    independently configurable.
    """
    from leads import do_inference_client as _oai

    base = os.getenv(_oai.SELF_HOSTED_BASE_URL_ENV, "").strip()
    if not base:
        raise DOFallbackNotConfigured(
            f"{_oai.SELF_HOSTED_BASE_URL_ENV} not set — self-hosted model "
            f"{model_id!r} is in the chain but has nowhere to call")

    return _oai.chat(
        model_id[len(LOCAL_PREFIX):], system, user, max_tokens, temperature,
        base_url=base,
        api_key=os.getenv(_oai.SELF_HOSTED_KEY_ENV, "") or "not-required",
    )


def _call_converse(model_id: str, system: str, user: str,
                   max_tokens: int, temperature: float) -> Tuple[str, Dict[str, int], float]:
    """One raw model call, routed to whichever provider owns `model_id`.

    Returns (text, usage, latency_seconds) in Bedrock's shape regardless of
    provider, so the retry loop and cost-audit logging above stay
    provider-agnostic.
    """
    if is_local_model(model_id):
        return _call_self_hosted(model_id, system, user, max_tokens, temperature)
    if is_do_model(model_id):
        return _call_do(model_id, system, user, max_tokens, temperature)

    client = _get_runtime_client()

    kwargs: Dict[str, Any] = {
        "modelId": model_id,
        "messages": [{"role": "user", "content": [{"text": user}]}],
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": temperature,
        },
    }
    if system:
        kwargs["system"] = [{"text": system}]

    started = time.monotonic()
    response = client.converse(**kwargs)
    latency = time.monotonic() - started

    content = response.get("output", {}).get("message", {}).get("content", [])
    text = "".join(block.get("text", "") for block in content).strip()
    usage = response.get("usage", {}) or {}
    return text, usage, latency


def converse_meta(role: str, system: str, user: str,
                  max_tokens: int = 1024, temperature: float = 0.0
                  ) -> Tuple[str, Dict[str, Any]]:
    """
    Governed Bedrock Converse call that ALSO returns a cost-audit meta dict.

    Returns (text, meta) where meta is:
        {model_id, role, input_tokens, output_tokens, total_tokens, latency_s}

    This is the single implementation of the retry loop; converse() wraps it
    and drops the meta so existing callers are unchanged.
    Raises BedrockError when all retries are exhausted.
    """
    chain = models_for_role(role)
    attempts = max_retries()
    failures: List[str] = []

    for position, model_id in enumerate(chain):
        last_error: Optional[Exception] = None

        for attempt in range(1, attempts + 1):
            try:
                text, usage, latency = _call_converse(
                    model_id, system, user, max_tokens, temperature)

                if not text:
                    raise BedrockError(f"empty response from {model_id}")

                # Cost audit trail — every call, at INFO. `position` makes a
                # silent quality downgrade visible in the logs: anything above 0
                # means the primary was unavailable and a fallback answered.
                logger.info(
                    "llm call provider=%s role=%s model=%s position=%d latency=%.2fs "
                    "input_tokens=%s output_tokens=%s total_tokens=%s attempt=%d",
                    provider_of(model_id), role, model_id, position, latency,
                    usage.get("inputTokens"), usage.get("outputTokens"),
                    usage.get("totalTokens"), attempt,
                )

                meta = {
                    "model_id": model_id,
                    "provider": provider_of(model_id),
                    "role": role,
                    "fallback_position": position,
                    "is_fallback": position > 0,
                    "input_tokens": usage.get("inputTokens"),
                    "output_tokens": usage.get("outputTokens"),
                    "total_tokens": usage.get("totalTokens"),
                    "latency_s": round(latency, 3),
                }
                return text, meta

            except Exception as e:
                code = _error_code(e)

                # Transient — same model, backoff, try again.
                if code in _RETRYABLE_CODES and attempt < attempts:
                    backoff = 2 ** (attempt - 1)
                    logger.warning(
                        "bedrock %s on %s (attempt %d/%d), retrying in %ds",
                        code, model_id, attempt, attempts, backoff)
                    time.sleep(backoff)
                    last_error = e
                    continue

                # Model unusable — stop retrying it and move down the chain.
                last_error = e
                break

        _demote(model_id)
        failures.append(f"{model_id}: {_error_code(last_error)}")
        remaining = len(chain) - position - 1
        if remaining:
            logger.warning(
                "bedrock model %s unavailable (%s) — falling back to %s",
                model_id, _error_code(last_error), chain[position + 1])

    # Every model in the chain failed. When they all fail the same way this is
    # almost always credentials or account-level access, not the models — the
    # joined error list makes that pattern obvious at a glance.
    raise BedrockError(
        f"all {len(chain)} models failed for role={role} — [{'; '.join(failures)}]"
    )


def converse(role: str, system: str, user: str,
             max_tokens: int = 1024, temperature: float = 0.0) -> str:
    """
    Governed Bedrock Converse call.

    Args:
        role: "cheap" or "smart" — never a model ID
        system: system instruction (may be empty)
        user: the user turn
        max_tokens: response cap
        temperature: sampling temperature

    Returns the model's text response.
    Raises BedrockError when all retries are exhausted.
    """
    text, _meta = converse_meta(role, system, user, max_tokens, temperature)
    return text


def _error_code(exc: Exception) -> str:
    """Extract a botocore error code, tolerating non-botocore exceptions."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return str(response.get("Error", {}).get("Code", "")) or type(exc).__name__
    return type(exc).__name__


def converse_json(role: str, system: str, user: str,
                  max_tokens: int = 1024, temperature: float = 0.0) -> Any:
    """
    converse() + parse_json_strict(), with exactly one retry that appends a
    "return only valid JSON" reminder. Raises JSONParseError if the retry also
    fails, so callers can fall back deliberately.
    """
    text = converse(role, system, user, max_tokens, temperature)
    try:
        return parse_json_strict(text)
    except JSONParseError as first_error:
        logger.warning("role=%s returned unparseable JSON, retrying once: %s",
                       role, first_error)
        retry_text = converse(role, system, user + JSON_REMINDER,
                              max_tokens, temperature)
        return parse_json_strict(retry_text)


def converse_json_object(role: str, system: str, user: str, **kw) -> Optional[Dict[str, Any]]:
    """converse_json constrained to an object. Returns None if not an object."""
    value = converse_json(role, system, user, **kw)
    return value if isinstance(value, dict) else None


def converse_json_meta(role: str, system: str, user: str,
                       max_tokens: int = 1024, temperature: float = 0.0
                       ) -> Tuple[Any, Dict[str, Any]]:
    """
    Like converse_json() but also returns the cost-audit meta from
    converse_meta(). One JSON-reminder retry, same as converse_json.
    Returns (parsed_json, meta). Raises JSONParseError if both attempts fail.
    """
    text, meta = converse_meta(role, system, user, max_tokens, temperature)
    try:
        return parse_json_strict(text), meta
    except JSONParseError as first_error:
        logger.warning("role=%s returned unparseable JSON, retrying once: %s",
                       role, first_error)
        retry_text, meta = converse_meta(role, system, user + JSON_REMINDER,
                                         max_tokens, temperature)
        return parse_json_strict(retry_text), meta


# ============================================================
# BATCH INFERENCE (50% cheaper than on-demand; not time-sensitive work)
# ============================================================
# Batch jobs write JSONL to S3, run as a `bedrock` model-invocation job, and
# land results back in S3. This is the one place where Bedrock requires the
# model's NATIVE request schema (batch does not go through Converse), so the
# translation is kept here — callers still never see a model ID or a native
# body.
#
# Config (env):
#   BEDROCK_BATCH_S3_BUCKET   s3 bucket for job input/output   (required)
#   BEDROCK_BATCH_ROLE_ARN    IAM role Bedrock assumes         (required)
#   BEDROCK_BATCH_S3_PREFIX   key prefix                        (default batch-inference)

_s3_client = None
_BATCH_TERMINAL = {"Completed", "Failed", "Stopped", "Expired"}


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client("s3", region_name=get_region())
    return _s3_client


def batch_config() -> Dict[str, str]:
    bucket = os.getenv("BEDROCK_BATCH_S3_BUCKET", "")
    role_arn = os.getenv("BEDROCK_BATCH_ROLE_ARN", "")
    if not bucket or not role_arn:
        raise BedrockError(
            "Batch mode needs BEDROCK_BATCH_S3_BUCKET and BEDROCK_BATCH_ROLE_ARN. "
            "Use on-demand mode (the default) if batch is not set up.")
    return {"bucket": bucket, "role_arn": role_arn,
            "prefix": os.getenv("BEDROCK_BATCH_S3_PREFIX", "batch-inference")}


def _native_body(role: str, system: str, user: str,
                 max_tokens: int, temperature: float) -> Dict[str, Any]:
    """
    Native request body for a batch record. Qwen on Bedrock takes an
    OpenAI-chat-style schema. UNVERIFIED against the live service —
    submit a 2-record job first (see RUNBOOK) before trusting a big run.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    return {"messages": messages, "max_tokens": max_tokens,
            "temperature": temperature}


def build_batch_records(items: List[Tuple[str, str, str]], role: str,
                        max_tokens: int = 2048,
                        temperature: float = 0.0) -> List[str]:
    """
    items: [(record_id, system, user), ...] -> JSONL lines for a batch job.
    record_id round-trips through the job so results can be matched to leads.
    """
    lines = []
    for record_id, system, user in items:
        lines.append(json.dumps({
            "recordId": str(record_id)[:64],
            "modelInput": _native_body(role, system, user, max_tokens, temperature),
        }, ensure_ascii=False))
    return lines


def submit_batch_job(jsonl_lines: List[str], role: str,
                     job_name: Optional[str] = None) -> Dict[str, str]:
    """
    Upload JSONL to S3 and start a Bedrock model-invocation (batch) job.
    Returns {"job_arn", "input_key", "output_prefix"}.
    """
    cfg = batch_config()
    model_id = model_for_role(role)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    job_name = job_name or f"lead-pipeline-{stamp}"
    input_key = f"{cfg['prefix']}/input/{job_name}.jsonl"
    output_prefix = f"{cfg['prefix']}/output/{job_name}/"

    _get_s3_client().put_object(
        Bucket=cfg["bucket"], Key=input_key,
        Body=("\n".join(jsonl_lines) + "\n").encode("utf-8"))

    response = _get_control_client().create_model_invocation_job(
        jobName=job_name,
        modelId=model_id,
        roleArn=cfg["role_arn"],
        inputDataConfig={"s3InputDataConfig": {
            "s3Uri": f"s3://{cfg['bucket']}/{input_key}"}},
        outputDataConfig={"s3OutputDataConfig": {
            "s3Uri": f"s3://{cfg['bucket']}/{output_prefix}"}},
    )
    job_arn = response["jobArn"]
    logger.info("batch job submitted job=%s model=%s records=%d arn=%s",
                job_name, model_id, len(jsonl_lines), job_arn)
    return {"job_arn": job_arn, "input_key": input_key,
            "output_prefix": output_prefix}


def poll_batch_job(job_arn: str, interval_seconds: int = 300,
                   timeout_seconds: int = 24 * 3600) -> str:
    """Block until the job reaches a terminal state. Returns the final status."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        status = _get_control_client().get_model_invocation_job(
            jobIdentifier=job_arn).get("status", "")
        logger.info("batch job %s status=%s", job_arn, status)
        if status in _BATCH_TERMINAL:
            return status
        if time.monotonic() > deadline:
            raise BedrockError(f"batch job {job_arn} timed out (last={status})")
        time.sleep(interval_seconds)


def fetch_batch_results(output_prefix: str) -> Dict[str, Any]:
    """
    Download job output and return {record_id: parsed_json_or_None}.
    Output records carry modelOutput in the model's native response schema;
    the assistant text is extracted here and run through parse_json_strict.
    """
    cfg = batch_config()
    s3 = _get_s3_client()
    results: Dict[str, Any] = {}

    listing = s3.list_objects_v2(Bucket=cfg["bucket"], Prefix=output_prefix)
    for obj in listing.get("Contents", []):
        key = obj["Key"]
        if not key.endswith(".jsonl.out") and not key.endswith(".jsonl"):
            continue
        body = s3.get_object(Bucket=cfg["bucket"], Key=key)["Body"].read()
        for line in body.decode("utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                record_id = record.get("recordId", "")
                text = _extract_native_text(record.get("modelOutput") or {})
                try:
                    results[record_id] = parse_json_strict(text)
                except JSONParseError:
                    results[record_id] = None
            except Exception as e:
                logger.warning("unparseable batch output line in %s: %s", key, e)
    logger.info("batch results fetched: %d records from %s",
                len(results), output_prefix)
    return results


def _extract_native_text(model_output: Dict[str, Any]) -> str:
    """Assistant text from an OpenAI-chat-style native response."""
    choices = model_output.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        return str(message.get("content") or "")
    # Some providers return {"output": {"message": {...}}} even in batch.
    content = (model_output.get("output", {}).get("message", {})
               .get("content") or [])
    if isinstance(content, list) and content:
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(model_output.get("generation") or "")


def converse_string_list(role: str, system: str, user: str,
                         key: Optional[str] = None, **kw) -> Optional[List[str]]:
    """
    converse_json constrained to a list of strings, accepting either a bare
    array or an object wrapping one (optionally under `key`). Blank and
    non-string entries are dropped. Returns None if nothing usable.
    """
    value = converse_json(role, system, user, **kw)

    if isinstance(value, dict):
        if key and isinstance(value.get(key), list):
            value = value[key]
        else:
            for candidate in value.values():
                if isinstance(candidate, list):
                    value = candidate
                    break
            else:
                return None

    if not isinstance(value, list):
        return None

    items = [s.strip() for s in value if isinstance(s, str) and s.strip()]
    return items or None
