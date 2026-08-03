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
    role="smart"  -> BEDROCK_MODEL_SMART   (default deepseek.v3-v1:0)
                     email writing, second-opinion classification

Swapping either model to e.g. Nova Lite or Claude Haiku requires changing only
the environment variable.

Configuration (env only — no credentials in code, standard chain applies):
    BEDROCK_MODEL_CHEAP   default qwen.qwen3-32b-v1:0
    BEDROCK_MODEL_SMART   default deepseek.v3-v1:0
    AWS_REGION            default ap-south-1  (Mumbai)
    BEDROCK_MAX_RETRIES   default 3

DeepSeek note: we deliberately do NOT enable reasoning/thinking. Reasoning
tokens bill as output tokens and are wasted on short classification and email
tasks, so no `additionalModelRequestFields` reasoning config is sent.
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
DEFAULT_MODEL_SMART = "deepseek.v3-v1:0"
DEFAULT_REGION = "ap-south-1"

VALID_ROLES = ("cheap", "smart")

# Throttling / transient error codes worth retrying.
_RETRYABLE_CODES = {
    "ThrottlingException", "TooManyRequestsException",
    "ServiceQuotaExceededException", "ModelTimeoutException",
    "InternalServerException", "ServiceUnavailableException",
}


def get_region() -> str:
    return os.getenv("AWS_REGION") or DEFAULT_REGION


def model_for_role(role: str) -> str:
    """Resolve a role to a concrete model ID. The only place IDs are read."""
    if role == "cheap":
        return os.getenv("BEDROCK_MODEL_CHEAP") or DEFAULT_MODEL_CHEAP
    if role == "smart":
        return os.getenv("BEDROCK_MODEL_SMART") or DEFAULT_MODEL_SMART
    raise ValueError(f"unknown role {role!r}; expected one of {VALID_ROLES}")


def max_retries() -> int:
    try:
        return max(1, int(os.getenv("BEDROCK_MAX_RETRIES", "") or 3))
    except (TypeError, ValueError):
        return 3


def config_summary() -> Dict[str, Any]:
    return {
        "region": get_region(),
        "model_cheap": model_for_role("cheap"),
        "model_smart": model_for_role("smart"),
        "max_retries": max_retries(),
    }


# ============================================================
# ERRORS
# ============================================================

class BedrockError(RuntimeError):
    """Bedrock call failed (transport, auth, throttling exhausted)."""


class ModelAccessError(BedrockError):
    """A configured model is not accessible in the configured region."""


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

    try:
        response = _get_control_client().list_foundation_models()
    except Exception as e:
        raise ModelAccessError(
            f"Could not list Bedrock foundation models in {region}: {e}. "
            f"Check AWS credentials and that Bedrock is available in this region."
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

def _call_converse(model_id: str, system: str, user: str,
                   max_tokens: int, temperature: float) -> Tuple[str, Dict[str, int], float]:
    """One raw Converse call. Returns (text, usage, latency_seconds)."""
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
    model_id = model_for_role(role)
    attempts = max_retries()
    last_error: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        try:
            text, usage, latency = _call_converse(
                model_id, system, user, max_tokens, temperature)

            # Cost audit trail — every call, at INFO.
            logger.info(
                "bedrock call role=%s model=%s latency=%.2fs "
                "input_tokens=%s output_tokens=%s total_tokens=%s attempt=%d",
                role, model_id, latency,
                usage.get("inputTokens"), usage.get("outputTokens"),
                usage.get("totalTokens"), attempt,
            )

            if not text:
                raise BedrockError(f"empty response from {model_id}")

            meta = {
                "model_id": model_id,
                "role": role,
                "input_tokens": usage.get("inputTokens"),
                "output_tokens": usage.get("outputTokens"),
                "total_tokens": usage.get("totalTokens"),
                "latency_s": round(latency, 3),
            }
            return text, meta

        except Exception as e:
            code = _error_code(e)
            if code in _RETRYABLE_CODES and attempt < attempts:
                backoff = 2 ** (attempt - 1)
                logger.warning(
                    "bedrock %s on %s (attempt %d/%d), retrying in %ds",
                    code, model_id, attempt, attempts, backoff)
                time.sleep(backoff)
                last_error = e
                continue
            if isinstance(e, BedrockError):
                raise
            raise BedrockError(
                f"bedrock converse failed (role={role}, model={model_id}): {e}") from e

    raise BedrockError(
        f"bedrock throttled after {attempts} attempts "
        f"(role={role}, model={model_id}): {last_error}")


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
    Native request body for a batch record. Qwen and DeepSeek on Bedrock both
    take an OpenAI-chat-style schema. UNVERIFIED against the live service —
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
