"""
LEGACY WRAPPER SHIM — Claude-backed (Anthropic is the ONLY AI provider)
=======================================================================
The original openai_wrapper was retired with a bare `raise RuntimeError`,
which silently broke every module that lazily imported it (scheduler
batches, query generator, settings/classification usage endpoints,
email_sync router, automation engines).

This module restores the legacy API, routed through the governed
ai_governance.claude_gateway. New code should import from ai_governance
directly; this file exists so the existing call sites work again.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

try:
    from ai_governance.claude_gateway import (  # re-exported for legacy importers
        chat_completion,
        chat_completion_with_escalation,
        ClaudeChatClient,
        PREMIUM_MODEL,
        CHEAP_MODEL,
        ANTHROPIC_DEFAULT_MODEL,
    )
    from ai_governance.ai_gateway import _get_anthropic_api_key, _get_mongo_client
    from ai_governance.governance_checks import check_ai_daily_limit
except ImportError:  # package context (tests import as backend.*)
    from backend.ai_governance.claude_gateway import (
        chat_completion,
        chat_completion_with_escalation,
        ClaudeChatClient,
        PREMIUM_MODEL,
        CHEAP_MODEL,
        ANTHROPIC_DEFAULT_MODEL,
    )
    from backend.ai_governance.ai_gateway import _get_anthropic_api_key, _get_mongo_client
    from backend.ai_governance.governance_checks import check_ai_daily_limit

logger = logging.getLogger(__name__)

__all__ = [
    "chat_completion", "chat_completion_with_escalation", "batch_chat_completion",
    "get_openai_client", "get_openai_api_key", "is_ai_disabled", "token_logger",
    "PREMIUM_MODEL", "CHEAP_MODEL", "ANTHROPIC_DEFAULT_MODEL",
]

# USD per 1K tokens (for the usage summary endpoints)
_COSTS = {
    "claude-opus-4-8": {"input": 0.005, "output": 0.025},
    "claude-haiku-4-5": {"input": 0.001, "output": 0.005},
}


def get_openai_client() -> ClaudeChatClient:
    """Legacy name — returns the governed Claude chat client."""
    return ClaudeChatClient()


def get_openai_api_key() -> str:
    """Legacy name — returns the Anthropic API key (Claude-only codebase)."""
    try:
        return _get_anthropic_api_key()
    except Exception:
        return ""


def is_ai_disabled() -> bool:
    """AI kill switch: env flags (legacy name honoured) or daily limit reached."""
    if os.getenv("DISABLE_AI_CALLS", "false").lower() == "true":
        return True
    if os.getenv("DISABLE_OPENAI_CALLS", "false").lower() == "true":  # legacy flag
        return True
    try:
        return not check_ai_daily_limit()
    except Exception:
        return False


def batch_chat_completion(items: List[Any],
                          prompt_generator: Callable[[List[Any]], str],
                          source: str = "",
                          batch_size: int = 10,
                          max_output_tokens: int = 800,
                          system_prompt: Optional[str] = None,
                          model: Optional[str] = None,
                          **_ignored) -> List[Dict[str, Any]]:
    """
    Process items in batches through one Claude call per batch.
    The prompt must ask for JSON of shape {"results": [...]} with one entry
    per item; returns a flat list aligned with `items` (error dicts on failure).
    """
    out: List[Dict[str, Any]] = []
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt_generator(batch)})
        result = chat_completion(
            messages,
            model=model or ANTHROPIC_DEFAULT_MODEL,
            max_output_tokens=max_output_tokens,
            response_format={"type": "json_object"},
            source=source,
            endpoint="batch_chat_completion",
        )
        if not result["success"]:
            out.extend({"error": result.get("error", "ai_call_failed")} for _ in batch)
            continue
        try:
            parsed = json.loads(result["content"])
            results = parsed.get("results", parsed if isinstance(parsed, list) else [])
        except Exception as e:
            out.extend({"error": f"parse_error: {e}"} for _ in batch)
            continue
        for i in range(len(batch)):
            out.append(results[i] if i < len(results) and isinstance(results[i], dict)
                       else {"error": "missing_result"})
    return out


class _TokenLogger:
    """Usage summary over the ai_governance_log collection (Claude usage)."""

    def get_usage_summary(self, hours: int = 24) -> Dict[str, Any]:
        try:
            db = _get_mongo_client()["torpedo_settings"]
            since = datetime.utcnow() - timedelta(hours=hours)
            pipeline = [
                {"$match": {"at": {"$gte": since}}},
                {"$group": {
                    "_id": {"model": "$model", "source": "$task_type"},
                    "total_input_tokens": {"$sum": {"$ifNull": ["$input_tokens", 0]}},
                    "total_output_tokens": {"$sum": {"$ifNull": ["$output_tokens", 0]}},
                    "total_requests": {"$sum": 1},
                }},
            ]
            breakdown = []
            for row in db["ai_governance_log"].aggregate(pipeline):
                model = row["_id"].get("model") or "claude-opus-4-8"
                costs = _COSTS.get(model, _COSTS["claude-opus-4-8"])
                cost = (row["total_input_tokens"] / 1000 * costs["input"] +
                        row["total_output_tokens"] / 1000 * costs["output"])
                breakdown.append({
                    "model": model,
                    "source": row["_id"].get("source") or "unknown",
                    "total_input_tokens": row["total_input_tokens"],
                    "total_output_tokens": row["total_output_tokens"],
                    "total_requests": row["total_requests"],
                    "total_cost": round(cost, 6),
                })
            return {"breakdown": breakdown, "period_hours": hours,
                    "provider": "anthropic"}
        except Exception as e:
            logger.warning(f"token usage summary failed: {e}")
            return {"breakdown": [], "error": str(e)}


token_logger = _TokenLogger()
