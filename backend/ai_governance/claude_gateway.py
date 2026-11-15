"""
CLAUDE GATEWAY - Governed generic LLM access (Anthropic API)
=============================================================
The Anthropic Messages API is the AI provider in this codebase. Models come
from the ladder config (platform_core.ladder.cfg()): `haiku` = fast/cheap,
`sonnet` = smart. Defaults claude-haiku-5-5 / claude-sonnet-5-5, overridable
with env LLM_MODEL_FAST / LLM_MODEL_SMART.

`ai_gateway.AIGateway` keeps the task-specific operations (classify /
summarize / extract / draft). This module adds:

- generate():      governed generic text/JSON generation for everything else
- web_search():    server-side web search (Anthropic web_search tool)
- chat_completion(), chat_completion_with_escalation(), ClaudeChatClient,
  AsyncClaudeChatClient: the .chat.completions.create(...) compat surface for
  the call sites migrated off the OpenAI SDK. Text calls go through the
  ladder's Anthropic transport (platform_core.ladder.anthropic_transport).
- ClaudeGenerativeModel: kept for routers/cold_outreach_router.py only.

Every call goes through the same governance checks (daily hard limit) and is
recorded in the `ai_governance_log` collection with caller + task_type.
"""

import os
import json
import logging
import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from .governance_checks import (
    check_ai_daily_limit,
    increment_ai_daily_usage,
    AIDailyLimitExceeded,
)

try:  # backend dir on sys.path (uvicorn main:app)
    from db import settings as _settings_db
except ImportError:  # imported as backend.* from the repo root
    from backend.db import settings as _settings_db  # type: ignore

logger = logging.getLogger(__name__)

_FAST_FALLBACK = "claude-haiku-5-5"
_SMART_FALLBACK = "claude-sonnet-5-5"


def _ladder():
    try:
        from platform_core import ladder
    except ImportError:  # pragma: no cover
        from backend.platform_core import ladder  # type: ignore
    return ladder


def model_for(tier: str = "fast") -> str:
    """Model id for 'fast'/'haiku' or 'smart'/'sonnet': env override, else ladder config."""
    key = "sonnet" if tier in ("smart", "sonnet", "premium") else "haiku"
    env = os.getenv("LLM_MODEL_SMART" if key == "sonnet" else "LLM_MODEL_FAST")
    if env:
        return env
    try:
        return _ladder().cfg()["models"][key]["model"]
    except Exception:
        return _SMART_FALLBACK if key == "sonnet" else _FAST_FALLBACK


# Names kept because other modules import them. Import-time values come from env
# or the built-in default only (no DB read at import); the call paths below use
# model_for(), which also honours the ladder config.
DEFAULT_MODEL = os.getenv("LLM_MODEL_FAST") or _FAST_FALLBACK
WEB_SEARCH_MODEL = os.getenv("LLM_MODEL_WEB_SEARCH") or DEFAULT_MODEL
PREMIUM_MODEL = os.getenv("LLM_MODEL_SMART") or _SMART_FALLBACK
CHEAP_MODEL = DEFAULT_MODEL
ANTHROPIC_DEFAULT_MODEL = CHEAP_MODEL   # name kept from the retired wrapper


def _strip_markdown_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _log_usage(task_type: str, model: str, usage: Any, caller: str = "") -> None:
    """Best-effort governance audit record. Never raises."""
    try:
        _settings_db()["ai_governance_log"].insert_one({
            "provider": "anthropic",
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


def _flatten(messages: List[Dict[str, Any]]) -> Tuple[str, str]:
    """OpenAI-style messages -> (system, single user string) for the ladder transport.
    A lone user turn is passed through verbatim; longer conversations are
    flattened with role labels."""
    system_parts, turns = [], []
    for m in messages:
        content = str(m.get("content") or "")
        if m.get("role") == "system":
            system_parts.append(content)
        else:
            turns.append((m.get("role") or "user", content))
    if len(turns) == 1:
        user = turns[0][1]
    else:
        user = "\n\n".join(f"{r.upper()}: {c}" for r, c in turns)
    return "\n\n".join(p for p in system_parts if p), user


def _text_call(system: str, user: str, *, model: str, max_tokens: int) -> Tuple[str, Any]:
    """One governed text call through the ladder's Anthropic transport. -> (text, usage)."""
    _governance_gate()
    text, tin, tout = _ladder().anthropic_transport(
        model=model, system=system or "", user=user, schema=None, max_tokens=max_tokens,
        thinking={"type": "disabled"})
    return (text or "").strip(), SimpleNamespace(input_tokens=tin, output_tokens=tout)


class ClaudeGateway:
    """Governed generic Anthropic access. Singleton via get_claude_gateway()."""

    def generate(self, prompt: str, system: Optional[str] = None,
                 model: Optional[str] = None, max_tokens: int = 16000,
                 json_only: bool = False, task_type: str = "generate",
                 caller: str = "", temperature: Optional[float] = None) -> str:
        """Governed single-turn generation. Returns the text response.
        `temperature` is accepted for compat; the transport leaves it at the default."""
        model = model or model_for("fast")
        if json_only:
            prompt = prompt + "\n\nReturn ONLY valid JSON. No preamble. No markdown."
        text, usage = _text_call(system or "", prompt, model=model, max_tokens=max_tokens)
        _log_usage(task_type, model, usage, caller)
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
        """Web search via the Anthropic server-side web_search tool."""
        _governance_gate()
        model = model or os.getenv("LLM_MODEL_WEB_SEARCH") or model_for("fast")
        response = _anthropic_client().messages.create(
            model=model,
            max_tokens=16000,
            tools=[{"type": "web_search_20260209", "name": "web_search",
                    "max_uses": max(1, min(num_results, 10))}],
            messages=[{"role": "user", "content": query}],
        )
        _log_usage("web_search", model, response.usage, caller)
        text = " ".join(b.text for b in response.content if b.type == "text").strip()
        # web_search_tool_result blocks carry the URL/title of each page the
        # tool looked at, so downstream code can cite a source for a claim.
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


def _anthropic_client():
    import anthropic
    from .ai_gateway import _get_anthropic_api_key
    return anthropic.Anthropic(api_key=_get_anthropic_api_key(), max_retries=2, timeout=120.0)


_gateway: Optional[ClaudeGateway] = None


def get_claude_gateway() -> ClaudeGateway:
    global _gateway
    if _gateway is None:
        _gateway = ClaudeGateway()
    return _gateway


# ======================================================================
# chat.completions drop-in compatibility (Anthropic via the ladder transport)
# ======================================================================
# Call sites pass placeholder gpt-*/gemini-* model strings, which are ignored.

def _to_openai_shape(text: str, model: str, tin: int, tout: int, finish: str = "stop") -> SimpleNamespace:
    usage = SimpleNamespace(prompt_tokens=tin, completion_tokens=tout, total_tokens=tin + tout)
    choice = SimpleNamespace(index=0, message=SimpleNamespace(role="assistant", content=text),
                             finish_reason=finish)
    return SimpleNamespace(id="", model=model, choices=[choice], usage=usage)


def _chat_create(kwargs: Dict[str, Any]) -> SimpleNamespace:
    system, user = _flatten(list(kwargs.get("messages") or []))
    model = model_for("fast")
    max_tokens = int(kwargs.get("max_tokens") or kwargs.get("max_completion_tokens") or 1024)
    text, usage = _text_call(system, user, model=model, max_tokens=max_tokens)
    _log_usage("chat_compat", model, usage)
    return _to_openai_shape(text, model, usage.input_tokens, usage.output_tokens)


class _Completions:
    def create(self, **kwargs) -> Any:
        return _chat_create(kwargs)


class _AsyncCompletions:
    async def create(self, **kwargs) -> Any:
        import asyncio
        return await asyncio.to_thread(_chat_create, kwargs)


class _WebSearchCompletions:
    def create(self, **kwargs) -> Any:
        _governance_gate()
        system, turns = _split_messages(kwargs.get("messages") or [])
        ck: Dict[str, Any] = dict(
            model=os.getenv("LLM_MODEL_WEB_SEARCH") or model_for("fast"),
            max_tokens=kwargs.get("max_tokens") or kwargs.get("max_completion_tokens") or 16000,
            messages=turns,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}],
        )
        if system:
            ck["system"] = system
        response = _anthropic_client().messages.create(**ck)
        _log_usage("web_search_chat", ck["model"], response.usage)
        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        return _to_openai_shape(
            text, response.model, response.usage.input_tokens, response.usage.output_tokens,
            "stop" if response.stop_reason == "end_turn" else response.stop_reason)


def _split_messages(messages: List[Dict[str, Any]]):
    """Extract system text; pass through user/assistant turns (web-search shim only)."""
    system_parts, turns = [], []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(m.get("content") or "")
        else:
            turns.append({"role": m["role"], "content": m.get("content") or ""})
    if not turns:
        turns = [{"role": "user", "content": system_parts.pop() if system_parts else ""}]
    return ("\n\n".join(p for p in system_parts if p) or None), turns


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
# Retired leads.openai_wrapper replacements
# ======================================================================

def chat_completion(messages: List[Dict[str, Any]], model: Optional[str] = None,
                    max_output_tokens: int = 1024,
                    response_format: Optional[Dict[str, Any]] = None,
                    source: str = "", endpoint: str = "",
                    **_ignored) -> Dict[str, Any]:
    """
    Replacement for the retired leads.openai_wrapper.chat_completion.
    Returns {"success", "content", "model", "provider", "escalated", "error"}.
    """
    try:
        turns = list(messages)
        if response_format and response_format.get("type") in ("json_object", "json_schema") and turns:
            last = dict(turns[-1])
            last["content"] = str(last["content"]) + \
                "\n\nReturn ONLY valid JSON. No preamble. No markdown."
            turns[-1] = last
        use_model = model or model_for("fast")
        system, user = _flatten(turns)
        text, usage = _text_call(system, user, model=use_model, max_tokens=max_output_tokens)
        _log_usage(endpoint or "chat_completion", use_model, usage, caller=source)
        return {"success": True, "content": _strip_markdown_json(text),
                "model": use_model, "provider": "anthropic",
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
    Two-tier classification: fast model first, escalate to the smart model when
    the parsed confidence is below threshold. Replaces the retired
    leads.openai_wrapper.chat_completion_with_escalation.
    """
    result = chat_completion(messages, model=model_for("fast"), **kw)
    if not result["success"]:
        return result
    try:
        confidence = float(json.loads(result["content"]).get(confidence_key, 1.0))
    except Exception:
        confidence = 0.0
    if confidence < confidence_threshold:
        escalated = chat_completion(messages, model=model_for("smart"), **kw)
        if escalated["success"]:
            escalated["escalated"] = True
            return escalated
    return result


# ======================================================================
# google.generativeai shim: only routers/cold_outreach_router.py still uses it
# ======================================================================

class _GenerateContentResponse(SimpleNamespace):
    pass


class ClaudeGenerativeModel:
    """Drop-in for google.generativeai.GenerativeModel: .generate_content(prompt).text"""

    def __init__(self, model_name: str = "", *args, **kwargs):
        self._model = model_for("fast")  # the passed model string is ignored

    def generate_content(self, prompt, *args, **kwargs) -> _GenerateContentResponse:
        if isinstance(prompt, (list, tuple)):
            prompt = "\n".join(str(p) for p in prompt)
        text = get_claude_gateway().generate(
            str(prompt), model=self._model, task_type="gemini_compat")
        return _GenerateContentResponse(text=text)
