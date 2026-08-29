"""
BEDROCK GATEWAY - Governed generic LLM access (AWS Bedrock Mantle)
====================================================================
AWS Bedrock Mantle (OpenAI-compatible, serverless, per-token billed) is the
AI provider in this codebase. Billed through the same AWS account as SES.

`ai_gateway.AIGateway` keeps the task-specific operations (classify /
summarize / extract / draft). This module adds:

- generate():      governed generic text/JSON generation for everything else
- web_search():    server-side web search via a Claude model also hosted on
                   Bedrock Mantle (open-weight models don't support this tool)
- claude_chat_client() / async_claude_chat_client():
                   drop-in replacements for openai.OpenAI / AsyncOpenAI
                   exposing .chat.completions.create(...) — now a thin
                   pass-through since Bedrock Mantle speaks that shape natively
- ClaudeGenerativeModel: drop-in replacement for
                   google.generativeai.GenerativeModel(...).generate_content()

Every call goes through the same governance checks (daily hard limit) and is
recorded in the `ai_governance_log` collection with caller + task_type, so
usage is auditable in one place.

Names kept as "Claude*"/"claude_*" throughout for compat with existing callers.
"""

import os
import json
import logging
import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import anthropic
import openai

from .governance_checks import (
    check_ai_daily_limit,
    increment_ai_daily_usage,
    AIDailyLimitExceeded,
)
from .ai_gateway import _get_anthropic_api_key, _get_mongo_client, BEDROCK_BASE_URL

logger = logging.getLogger(__name__)

# Anthropic-route base_url for the same Bedrock Mantle deployment — only used
# by web_search(). DELIBERATE, DOCUMENTED EXCEPTION to the Qwen-only policy:
# server-side web search is Anthropic-specific and Qwen (or any open-weight
# model) does not support it on Bedrock. Every other call in this codebase
# must resolve to Qwen; do not extend this exception to any other task.
BEDROCK_ANTHROPIC_BASE_URL = os.getenv(
    "BEDROCK_MANTLE_ANTHROPIC_BASE_URL", "https://bedrock-mantle.us-east-1.api.aws/anthropic")
WEB_SEARCH_MODEL = os.getenv("BEDROCK_MODEL_WEB_SEARCH", "anthropic.claude-haiku-4-5")

# Default for generic generation. Qwen-only policy: same model as
# ai_gateway's cheap tier and bedrock_client's "smart" role — override per-call
# or via env, but never default to a different provider here.
DEFAULT_MODEL = os.getenv("BEDROCK_MODEL_PREMIUM", "qwen.qwen3-32b-v1:0")


def _strip_markdown_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _log_usage(task_type: str, model: str, usage: Any, caller: str = "") -> None:
    """Best-effort governance audit record. Never raises."""
    try:
        db = _get_mongo_client()["torpedo_settings"]
        db["ai_governance_log"].insert_one({
            "provider": "bedrock",
            "model": model,
            "task_type": task_type,
            "caller": caller,
            "input_tokens": getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", None),
            "at": datetime.utcnow(),
        })
    except Exception as e:  # pragma: no cover - logging must never break callers
        logger.debug(f"ai_governance_log write failed: {e}")


def _governance_gate() -> None:
    if not check_ai_daily_limit():
        raise AIDailyLimitExceeded("AI daily limit reached. No more calls allowed today.")
    increment_ai_daily_usage()


def _bedrock_client() -> openai.OpenAI:
    return openai.OpenAI(api_key=_get_anthropic_api_key(), base_url=BEDROCK_BASE_URL)


class ClaudeGateway:
    """Governed generic Bedrock access. Singleton via get_claude_gateway()."""

    def __init__(self):
        self._client: Optional[openai.OpenAI] = None

    def _client_or_create(self) -> openai.OpenAI:
        if self._client is None:
            self._client = _bedrock_client()
        return self._client

    def generate(self, prompt: str, system: Optional[str] = None,
                 model: Optional[str] = None, max_tokens: int = 16000,
                 json_only: bool = False, task_type: str = "generate",
                 caller: str = "", temperature: Optional[float] = None) -> str:
        """Governed single-turn generation. Returns the text response."""
        _governance_gate()
        model = model or DEFAULT_MODEL
        if json_only:
            suffix = "\n\nReturn ONLY valid JSON. No preamble. No markdown."
            prompt = prompt + suffix
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        kwargs: Dict[str, Any] = dict(
            model=model, max_tokens=max_tokens, messages=messages)
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = self._client_or_create().chat.completions.create(**kwargs)
        _log_usage(task_type, model, response.usage, caller)
        text = (response.choices[0].message.content or "").strip()
        return _strip_markdown_json(text) if json_only else text

    def generate_json(self, prompt: str, **kw) -> Optional[Dict[str, Any]]:
        """generate() + json.loads, returning None on parse failure."""
        try:
            return json.loads(self.generate(prompt, json_only=True, **kw))
        except (json.JSONDecodeError, AIDailyLimitExceeded):
            raise
        except Exception as e:
            logger.error(f"generate_json failed: {e}")
            return None

    def web_search(self, query: str, num_results: int = 10,
                   model: Optional[str] = None, caller: str = "") -> Dict[str, Any]:
        """
        Web search via a Claude model's server-side web_search tool, hosted on
        the same Bedrock Mantle deployment (Anthropic Messages route).
        """
        _governance_gate()
        model = model or WEB_SEARCH_MODEL
        client = anthropic.Anthropic(auth_token=_get_anthropic_api_key(), base_url=BEDROCK_ANTHROPIC_BASE_URL)
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            tools=[{"type": "web_search_20260209", "name": "web_search",
                    "max_uses": max(1, min(num_results, 10))}],
            messages=[{"role": "user", "content": query}],
        )
        _log_usage("web_search", model, response.usage, caller)
        text = " ".join(b.text for b in response.content if b.type == "text").strip()
        # Preserve what the server-side web_search tool actually retrieved —
        # previously discarded entirely, which is why nothing downstream
        # could ever cite a source for a claim. web_search_tool_result
        # blocks carry the URL/title of each page the tool looked at;
        # citation annotations on text blocks (when present) tie a
        # specific sentence back to one of those URLs.
        sources = []
        for block in response.content:
            if getattr(block, "type", None) == "web_search_tool_result":
                content = getattr(block, "content", None) or []
                for item in content:
                    url = getattr(item, "url", None)
                    if url:
                        sources.append({
                            "url": url,
                            "title": getattr(item, "title", None),
                        })
        return {"query": query, "answer": text, "sources": sources, "success": True,
                "searched_at": datetime.utcnow().isoformat()}


_gateway: Optional[ClaudeGateway] = None


def get_claude_gateway() -> ClaudeGateway:
    global _gateway
    if _gateway is None:
        _gateway = ClaudeGateway()
    return _gateway


# ======================================================================
# OpenAI chat.completions drop-in compatibility (Bedrock-backed)
# ======================================================================
# Bedrock Mantle speaks the OpenAI Chat Completions shape natively, so these
# are now thin pass-throughs — only the model name is overridden (call sites
# pass placeholder gpt-*/gemini-* strings that get ignored).

class _Completions:
    def create(self, **kwargs) -> Any:
        _governance_gate()
        client = _bedrock_client()
        kwargs = dict(kwargs)
        kwargs["model"] = DEFAULT_MODEL
        kwargs.pop("response_format", None)  # not guaranteed supported across models
        response = client.chat.completions.create(**kwargs)
        _log_usage("chat_compat", kwargs["model"], response.usage)
        return response


class _AsyncCompletions:
    async def create(self, **kwargs) -> Any:
        _governance_gate()
        client = openai.AsyncOpenAI(api_key=_get_anthropic_api_key(), base_url=BEDROCK_BASE_URL)
        kwargs = dict(kwargs)
        kwargs["model"] = DEFAULT_MODEL
        kwargs.pop("response_format", None)
        response = await client.chat.completions.create(**kwargs)
        _log_usage("chat_compat", kwargs["model"], response.usage)
        return response


class _WebSearchCompletions:
    def create(self, **kwargs) -> Any:
        _governance_gate()
        client = anthropic.Anthropic(auth_token=_get_anthropic_api_key(), base_url=BEDROCK_ANTHROPIC_BASE_URL)
        system, turns = _split_messages(kwargs.get("messages") or [])
        ck: Dict[str, Any] = dict(
            model=WEB_SEARCH_MODEL,
            max_tokens=kwargs.get("max_tokens") or kwargs.get("max_completion_tokens") or 16000,
            messages=turns,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}],
        )
        if system:
            ck["system"] = system
        response = client.messages.create(**ck)
        _log_usage("web_search_chat", ck["model"], response.usage)
        return _to_openai_shape(response)


def _split_messages(messages: List[Dict[str, Any]]):
    """Extract system text; pass through user/assistant turns. Only used by
    the Anthropic-route web-search shim above."""
    system_parts, turns = [], []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(m.get("content") or "")
        else:
            turns.append({"role": m["role"], "content": m.get("content") or ""})
    if not turns:
        turns = [{"role": "user", "content": system_parts.pop() if system_parts else ""}]
    return ("\n\n".join(p for p in system_parts if p) or None), turns


def _to_openai_shape(response) -> SimpleNamespace:
    text = "\n".join(b.text for b in response.content if b.type == "text").strip()
    usage = SimpleNamespace(
        prompt_tokens=response.usage.input_tokens,
        completion_tokens=response.usage.output_tokens,
        total_tokens=response.usage.input_tokens + response.usage.output_tokens,
    )
    message = SimpleNamespace(role="assistant", content=text)
    choice = SimpleNamespace(index=0, message=message,
                             finish_reason="stop" if response.stop_reason == "end_turn"
                             else response.stop_reason)
    return SimpleNamespace(id=response.id, model=response.model,
                           choices=[choice], usage=usage)


class ClaudeChatClient:
    """Drop-in for openai.OpenAI(): exposes .chat.completions.create(...)."""

    def __init__(self, *args, **kwargs):  # accepts and ignores api_key etc.
        self.chat = SimpleNamespace(completions=_Completions())


class ClaudeWebSearchChatClient:
    """Same interface, but backed by Claude's server-side web_search tool —
    for call sites whose prompts say "search the web for ..."."""

    def __init__(self, *args, **kwargs):
        self.chat = SimpleNamespace(completions=_WebSearchCompletions())


class AsyncClaudeChatClient:
    """Drop-in for openai.AsyncOpenAI(): exposes await .chat.completions.create(...)."""

    def __init__(self, *args, **kwargs):
        self.chat = SimpleNamespace(completions=_AsyncCompletions())


def claude_chat_client(*args, **kwargs) -> ClaudeChatClient:
    return ClaudeChatClient()


def async_claude_chat_client(*args, **kwargs) -> AsyncClaudeChatClient:
    return AsyncClaudeChatClient()


# ======================================================================
# Retired leads.openai_wrapper replacements (Bedrock-backed)
# ======================================================================

# Qwen-only policy: both tiers resolve to the same model as ai_gateway.py and
# bedrock_client.py. PREMIUM_MODEL/CHEAP_MODEL are kept as two names (used by
# chat_completion_with_escalation's cheap-then-premium retry) but must never
# default to a different provider.
PREMIUM_MODEL = os.getenv("BEDROCK_MODEL_PREMIUM", "qwen.qwen3-32b-v1:0")
CHEAP_MODEL = os.getenv("BEDROCK_MODEL_CHEAP", "qwen.qwen3-32b-v1:0")
# High-volume email classification default (name kept from the retired wrapper)
ANTHROPIC_DEFAULT_MODEL = CHEAP_MODEL


def chat_completion(messages: List[Dict[str, Any]], model: Optional[str] = None,
                    max_output_tokens: int = 1024,
                    response_format: Optional[Dict[str, Any]] = None,
                    source: str = "", endpoint: str = "",
                    **_ignored) -> Dict[str, Any]:
    """
    Bedrock-backed replacement for the retired leads.openai_wrapper.chat_completion.
    Returns {"success", "content", "model", "provider", "escalated", "error"}.
    """
    try:
        _governance_gate()
        client = _bedrock_client()
        turns = list(messages)
        if response_format and response_format.get("type") in ("json_object", "json_schema") and turns:
            last = dict(turns[-1])
            last["content"] = str(last["content"]) + \
                "\n\nReturn ONLY valid JSON. No preamble. No markdown."
            turns[-1] = last
        use_model = model or CHEAP_MODEL
        response = client.chat.completions.create(
            model=use_model, max_tokens=max_output_tokens, messages=turns)
        _log_usage(endpoint or "chat_completion", use_model, response.usage, caller=source)
        text = (response.choices[0].message.content or "").strip()
        return {"success": True, "content": _strip_markdown_json(text),
                "model": use_model, "provider": "bedrock",
                "escalated": False, "error": None}
    except Exception as e:
        logger.error(f"chat_completion failed: {e}")
        return {"success": False, "content": None, "model": None,
                "provider": "bedrock", "escalated": False, "error": str(e)}


def chat_completion_with_escalation(messages: List[Dict[str, Any]],
                                    confidence_key: str = "confidence",
                                    confidence_threshold: float = 0.7,
                                    **kw) -> Dict[str, Any]:
    """
    Two-tier classification: cheap model first, escalate to premium when
    the parsed confidence is below threshold. Replaces the retired
    leads.openai_wrapper.chat_completion_with_escalation.
    """
    result = chat_completion(messages, model=CHEAP_MODEL, **kw)
    if not result["success"]:
        return result
    try:
        confidence = float(json.loads(result["content"]).get(confidence_key, 1.0))
    except Exception:
        confidence = 0.0
    if confidence < confidence_threshold:
        escalated = chat_completion(messages, model=PREMIUM_MODEL, **kw)
        if escalated["success"]:
            escalated["escalated"] = True
            return escalated
    return result


# ======================================================================
# google.generativeai drop-in compatibility (Bedrock-backed)
# ======================================================================

class _GenerateContentResponse(SimpleNamespace):
    pass


class ClaudeGenerativeModel:
    """Drop-in for google.generativeai.GenerativeModel: .generate_content(prompt).text"""

    def __init__(self, model_name: str = "", *args, **kwargs):
        self._model = DEFAULT_MODEL  # gemini-* model strings are ignored

    def generate_content(self, prompt, *args, **kwargs) -> _GenerateContentResponse:
        if isinstance(prompt, (list, tuple)):
            prompt = "\n".join(str(p) for p in prompt)
        text = get_claude_gateway().generate(
            str(prompt), model=self._model, task_type="gemini_compat")
        return _GenerateContentResponse(text=text)
