"""
CLAUDE GATEWAY - Governed generic LLM access (Anthropic Claude ONLY)
====================================================================
Claude is the ONLY AI provider in this codebase.

`ai_gateway.AIGateway` keeps the task-specific operations (classify /
summarize / extract / draft). This module adds:

- generate():      governed generic text/JSON generation for everything else
- web_search():    Claude server-side web search (replaces the old OpenAI
                   web-search gateway)
- claude_chat_client() / async_claude_chat_client():
                   drop-in replacements for openai.OpenAI / AsyncOpenAI
                   exposing .chat.completions.create(...)
- ClaudeGenerativeModel: drop-in replacement for
                   google.generativeai.GenerativeModel(...).generate_content()

Every call goes through the same governance checks (daily hard limit) and is
recorded in the `ai_governance_log` collection with caller + task_type, so
usage is auditable in one place.
"""

import os
import json
import logging
import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import anthropic

from .governance_checks import (
    check_ai_daily_limit,
    increment_ai_daily_usage,
    AIDailyLimitExceeded,
)
from .ai_gateway import _get_anthropic_api_key, _get_mongo_client, KIMI_BASE_URL

logger = logging.getLogger(__name__)

# Default for generic generation. High-volume cheap tasks (classification)
# keep using ai_gateway's cheap tier; override per-call or via env.
DEFAULT_MODEL = os.getenv("KIMI_MODEL_PREMIUM", "kimi-k3")
# Claude-specific sampling restriction — Kimi accepts temperature/top_p normally,
# so this stays empty unless a future Kimi tier needs the same workaround.
_NO_SAMPLING_PREFIXES = ()


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
            "provider": "anthropic",
            "model": model,
            "task_type": task_type,
            "caller": caller,
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "at": datetime.utcnow(),
        })
    except Exception as e:  # pragma: no cover - logging must never break callers
        logger.debug(f"ai_governance_log write failed: {e}")


def _governance_gate() -> None:
    if not check_ai_daily_limit():
        raise AIDailyLimitExceeded("AI daily limit reached. No more calls allowed today.")
    increment_ai_daily_usage()


class ClaudeGateway:
    """Governed generic Claude access. Singleton via get_claude_gateway()."""

    def __init__(self):
        self._client: Optional[anthropic.Anthropic] = None

    def _client_or_create(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(auth_token=_get_anthropic_api_key(), base_url=KIMI_BASE_URL)
        return self._client

    def generate(self, prompt: str, system: Optional[str] = None,
                 model: Optional[str] = None, max_tokens: int = 16000,
                 json_only: bool = False, task_type: str = "generate",
                 caller: str = "") -> str:
        """Governed single-turn generation. Returns the text response."""
        _governance_gate()
        model = model or DEFAULT_MODEL
        if json_only:
            suffix = "\n\nReturn ONLY valid JSON. No preamble. No markdown."
            prompt = prompt + suffix
        kwargs: Dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system
        response = self._client_or_create().messages.create(**kwargs)
        _log_usage(task_type, model, response.usage, caller)
        text = next((b.text for b in response.content if b.type == "text"), "")
        return _strip_markdown_json(text) if json_only else text.strip()

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
        Web search via Claude's server-side web_search tool.
        Replaces the old OpenAI web-search gateway.
        """
        _governance_gate()
        model = model or DEFAULT_MODEL
        response = self._client_or_create().messages.create(
            model=model,
            max_tokens=16000,
            tools=[{"type": "web_search_20260209", "name": "web_search",
                    "max_uses": max(1, min(num_results, 10))}],
            messages=[{"role": "user", "content": query}],
        )
        _log_usage("web_search", model, response.usage, caller)
        text = " ".join(b.text for b in response.content if b.type == "text").strip()
        return {"query": query, "answer": text, "success": True,
                "searched_at": datetime.utcnow().isoformat()}


_gateway: Optional[ClaudeGateway] = None


def get_claude_gateway() -> ClaudeGateway:
    global _gateway
    if _gateway is None:
        _gateway = ClaudeGateway()
    return _gateway


# ======================================================================
# OpenAI chat.completions drop-in compatibility (Claude-backed)
# ======================================================================

def _split_messages(messages: List[Dict[str, Any]]):
    """Extract system text; pass through user/assistant turns."""
    system_parts, turns = [], []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(m.get("content") or "")
        else:
            turns.append({"role": m["role"], "content": m.get("content") or ""})
    if not turns:
        turns = [{"role": "user", "content": system_parts.pop() if system_parts else ""}]
    return ("\n\n".join(p for p in system_parts if p) or None), turns


def _wants_json(kwargs: Dict[str, Any]) -> bool:
    rf = kwargs.get("response_format")
    return bool(rf) and (rf.get("type") in ("json_object", "json_schema"))


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


def _build_claude_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    model = DEFAULT_MODEL  # requested gpt-*/gemini-* model strings are ignored
    system, turns = _split_messages(kwargs.get("messages") or [])
    if _wants_json(kwargs) and turns:
        last = dict(turns[-1])
        last["content"] = str(last["content"]) + \
            "\n\nReturn ONLY valid JSON. No preamble. No markdown."
        turns[-1] = last
    out: Dict[str, Any] = dict(
        model=model,
        max_tokens=kwargs.get("max_tokens") or kwargs.get("max_completion_tokens") or 16000,
        messages=turns,
    )
    if system:
        out["system"] = system
    # temperature/top_p are rejected by current Opus models — only forward
    # temperature to models that still accept it.
    if not model.startswith(_NO_SAMPLING_PREFIXES) and kwargs.get("temperature") is not None:
        out["temperature"] = kwargs["temperature"]
    return out


class _Completions:
    def create(self, **kwargs) -> SimpleNamespace:
        _governance_gate()
        client = anthropic.Anthropic(auth_token=_get_anthropic_api_key(), base_url=KIMI_BASE_URL)
        ck = _build_claude_kwargs(kwargs)
        response = client.messages.create(**ck)
        _log_usage("chat_compat", ck["model"], response.usage)
        return _to_openai_shape(response)


class _AsyncCompletions:
    async def create(self, **kwargs) -> SimpleNamespace:
        _governance_gate()
        client = anthropic.AsyncAnthropic(auth_token=_get_anthropic_api_key(), base_url=KIMI_BASE_URL)
        ck = _build_claude_kwargs(kwargs)
        response = await client.messages.create(**ck)
        _log_usage("chat_compat", ck["model"], response.usage)
        return _to_openai_shape(response)


class _WebSearchCompletions:
    def create(self, **kwargs) -> SimpleNamespace:
        _governance_gate()
        client = anthropic.Anthropic(auth_token=_get_anthropic_api_key(), base_url=KIMI_BASE_URL)
        ck = _build_claude_kwargs(kwargs)
        ck["tools"] = [{"type": "web_search_20260209", "name": "web_search",
                        "max_uses": 8}]
        response = client.messages.create(**ck)
        _log_usage("web_search_chat", ck["model"], response.usage)
        return _to_openai_shape(response)


class ClaudeChatClient:
    """Drop-in for openai.OpenAI(): exposes .chat.completions.create(...)."""

    def __init__(self, *args, **kwargs):  # accepts and ignores api_key etc.
        self.chat = SimpleNamespace(completions=_Completions())


class ClaudeWebSearchChatClient:
    """Same interface, but Claude can use its server-side web_search tool —
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
# Retired leads.openai_wrapper replacements (Claude-backed)
# ======================================================================

PREMIUM_MODEL = os.getenv("KIMI_MODEL_PREMIUM", "kimi-k3")
CHEAP_MODEL = os.getenv("KIMI_MODEL_CHEAP", "kimi-k2.6")
# High-volume email classification default (name kept from the retired wrapper)
ANTHROPIC_DEFAULT_MODEL = CHEAP_MODEL


def chat_completion(messages: List[Dict[str, Any]], model: Optional[str] = None,
                    max_output_tokens: int = 1024,
                    response_format: Optional[Dict[str, Any]] = None,
                    source: str = "", endpoint: str = "",
                    **_ignored) -> Dict[str, Any]:
    """
    Claude-backed replacement for the retired leads.openai_wrapper.chat_completion.
    Returns {"success", "content", "model", "provider", "escalated", "error"}.
    """
    try:
        _governance_gate()
        client = anthropic.Anthropic(auth_token=_get_anthropic_api_key(), base_url=KIMI_BASE_URL)
        system, turns = _split_messages(messages)
        if response_format and response_format.get("type") in ("json_object", "json_schema") and turns:
            last = dict(turns[-1])
            last["content"] = str(last["content"]) + \
                "\n\nReturn ONLY valid JSON. No preamble. No markdown."
            turns[-1] = last
        kwargs: Dict[str, Any] = dict(model=model or CHEAP_MODEL,
                                      max_tokens=max_output_tokens, messages=turns)
        if system:
            kwargs["system"] = system
        response = client.messages.create(**kwargs)
        _log_usage(endpoint or "chat_completion", kwargs["model"], response.usage, caller=source)
        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        return {"success": True, "content": _strip_markdown_json(text),
                "model": kwargs["model"], "provider": "anthropic",
                "escalated": False, "error": None}
    except Exception as e:
        logger.error(f"chat_completion failed: {e}")
        return {"success": False, "content": None, "model": None,
                "provider": "anthropic", "escalated": False, "error": str(e)}


def chat_completion_with_escalation(messages: List[Dict[str, Any]],
                                    confidence_key: str = "confidence",
                                    confidence_threshold: float = 0.7,
                                    **kw) -> Dict[str, Any]:
    """
    Two-tier classification: claude-haiku first, escalate to claude-opus when
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
# google.generativeai drop-in compatibility (Claude-backed)
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
