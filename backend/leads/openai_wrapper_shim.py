"""
AI GOVERNANCE SHIM LAYER
========================
This module provides backwards compatibility for code that imports from openai_wrapper.

IMPORTANT: This is a TRANSITIONAL module. All new code should use:
- backend.ai_governance.gemini_gateway for email operations
- backend.ai_governance.openai_gateway for web search

DeepSeek has been COMPLETELY REMOVED. Any DeepSeek calls will fail.
"""

import logging
from typing import Optional, Dict, Any, List, Literal

logger = logging.getLogger(__name__)


# ============== DEPRECATION WARNINGS ==============

_deprecation_logged = set()

def _log_deprecation(func_name: str):
    """Log deprecation warning once per function"""
    if func_name not in _deprecation_logged:
        logger.warning(
            f"DEPRECATED: {func_name} is deprecated. "
            "Migrate to backend.ai_governance module."
        )
        _deprecation_logged.add(func_name)


# ============== REMOVED: DEEPSEEK ==============

class DeepSeekRemoved(Exception):
    """Raised when any DeepSeek functionality is accessed"""
    def __init__(self, message=None):
        super().__init__(
            message or "DeepSeek has been COMPLETELY REMOVED from this codebase. "
            "Use backend.ai_governance.gemini_gateway for email operations."
        )


def get_deepseek_api_key():
    """REMOVED: DeepSeek is no longer supported"""
    raise DeepSeekRemoved()


def get_deepseek_client():
    """REMOVED: DeepSeek is no longer supported"""
    raise DeepSeekRemoved()


# ============== CONSTANTS ==============

# Only OpenAI is allowed (for web search only)
AIProvider = Literal["openai"]

OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
OPENAI_PREMIUM_MODEL = "gpt-4o"

# Default is now OpenAI (only for web search)
DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = OPENAI_DEFAULT_MODEL

# No retries per governance spec
MAX_RETRIES = 0
INITIAL_RETRY_DELAY = 0
MAX_RETRY_DELAY = 0

# Token limits
DEFAULT_MAX_OUTPUT_TOKENS = 300
BACKGROUND_MAX_OUTPUT_TOKENS = 150
INTERNAL_MAX_OUTPUT_TOKENS = 200
ESCALATED_MAX_OUTPUT_TOKENS = 500

ESCALATION_CONFIDENCE_THRESHOLD = 0.7

RequestSource = Literal["api", "user", "internal"]

# Model costs (reference only)
MODEL_COSTS = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gemini-2.0-flash": {"input": 0.0, "output": 0.0},
}

# Allowed tasks (only web search for OpenAI)
OPENAI_REQUIRED_TASKS = frozenset({
    "web_search",
    "company_discovery",
    "web_enrichment",
})


# ============== REDIRECTED FUNCTIONS ==============

def get_model_for_task(task_type: str = "default") -> tuple:
    """
    DEPRECATED: Use ai_governance module directly.
    
    Email tasks now use Gemini (via ai_governance.gemini_gateway)
    Web search uses OpenAI (via ai_governance.openai_gateway)
    """
    _log_deprecation("get_model_for_task")
    
    if task_type in OPENAI_REQUIRED_TASKS:
        return ("openai", OPENAI_DEFAULT_MODEL)
    else:
        # Email tasks should use Gemini now
        raise ValueError(
            f"Task '{task_type}' should use Gemini via ai_governance.gemini_gateway. "
            "This function only supports web search tasks now."
        )


def is_ai_disabled() -> bool:
    """Check if AI is disabled"""
    import os
    return os.getenv("DISABLE_AI_CALLS", "").lower() in ("true", "1", "yes")


def get_openai_api_key() -> Optional[str]:
    """Get OpenAI API key (for web search only)"""
    try:
        from backend.ai_governance.openai_gateway import _get_openai_api_key
        return _get_openai_api_key()
    except Exception:
        import os
        return os.getenv("OPENAI_API_KEY")


def chat_completion(
    messages: List[Dict[str, str]],
    source: RequestSource = "api",
    endpoint: str = "",
    model: str = None,
    max_output_tokens: Optional[int] = None,
    temperature: float = 0.1,
    response_format: Optional[Dict] = None,
    allow_premium_model: bool = False,
    provider: Optional[str] = None
) -> Dict[str, Any]:
    """
    DEPRECATED: Use ai_governance module directly.
    
    - For email classification/summarization: use ai_governance.gemini_gateway
    - For web search: use ai_governance.openai_gateway
    """
    _log_deprecation("chat_completion")
    
    # Detect operation type from messages
    prompt_text = " ".join([m.get("content", "") for m in messages]).lower()
    
    # Block email operations through this function
    email_keywords = ["classify", "classification", "categorize", "email", "summarize"]
    if any(kw in prompt_text for kw in email_keywords):
        raise ValueError(
            "Email operations are no longer supported through chat_completion. "
            "Use backend.ai_governance.gemini_gateway.classify_email() instead."
        )
    
    # For web search, redirect to OpenAI gateway
    from backend.ai_governance.openai_gateway import web_search
    
    user_message = next((m for m in messages if m.get("role") == "user"), {})
    query = user_message.get("content", "")
    
    result = web_search(query)
    
    return {
        "content": str(result.get("results", [])),
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "model": OPENAI_DEFAULT_MODEL,
        "provider": "openai",
        "success": result.get("success", False),
        "error": result.get("error")
    }


def reset_clients():
    """DEPRECATED: No-op for backwards compatibility"""
    _log_deprecation("reset_clients")
    pass


# ============== REMOVED DEEPSEEK ITEMS ==============
# These are kept as explicit errors to catch any remaining usage

DEEPSEEK_DEFAULT_MODEL = property(lambda self: (_ for _ in ()).throw(DeepSeekRemoved()))
DEEPSEEK_API_BASE = property(lambda self: (_ for _ in ()).throw(DeepSeekRemoved()))
DEEPSEEK_TASKS = frozenset()  # Empty - all tasks removed


def is_deepseek_model(model: str) -> bool:
    """REMOVED: DeepSeek is no longer supported"""
    raise DeepSeekRemoved()


# ============== LOGGER STUB ==============

class TokenUsageLogger:
    """Stub logger for backwards compatibility"""
    
    def __init__(self):
        pass
    
    def log_usage(self, **kwargs):
        _log_deprecation("TokenUsageLogger.log_usage")
        pass
    
    def get_usage_summary(self, hours: int = 24):
        _log_deprecation("TokenUsageLogger.get_usage_summary")
        return {}


token_logger = TokenUsageLogger()


class RateLimiter:
    """Stub rate limiter for backwards compatibility"""
    
    def is_allowed(self, source: str) -> bool:
        return True


rate_limiter = RateLimiter()


# ============== MIGRATION NOTICE ==============

def __getattr__(name):
    """Catch any remaining DeepSeek references"""
    if 'deepseek' in name.lower():
        raise DeepSeekRemoved(
            f"'{name}' is no longer available. DeepSeek has been removed."
        )
    raise AttributeError(f"module has no attribute '{name}'")
