"""
LEGACY OPENAI WRAPPER - DEPRECATED
==================================
This file is maintained for backwards compatibility only.
All new code should use the ai_governance module directly.

IMPORTANT: DeepSeek has been COMPLETELY REMOVED.
This wrapper now routes to the appropriate governance gateway.
"""

import os
import logging
from typing import Optional, Dict, Any, List, Literal

logger = logging.getLogger(__name__)

# ============== DEPRECATION WARNING ==============

def _deprecation_warning(func_name: str):
    """Log deprecation warning"""
    logger.warning(
        f"DEPRECATED: {func_name} from openai_wrapper.py is deprecated. "
        "Use backend.ai_governance module instead."
    )


# ============== REMOVED DEEPSEEK REFERENCES ==============
# The following have been REMOVED and will raise errors if accessed:
# - AIProvider (no longer includes "deepseek")
# - DEFAULT_PROVIDER (removed - use ai_governance)
# - DEEPSEEK_DEFAULT_MODEL (REMOVED)
# - DEEPSEEK_API_BASE (REMOVED)
# - DEEPSEEK_TASKS (REMOVED)
# - get_deepseek_api_key (REMOVED)
# - get_deepseek_client (REMOVED)
# - _deepseek_chat_completion (REMOVED)

# If any code imports these, it will fail - THIS IS INTENTIONAL
# as per governance spec: "Any DeepSeek reference = build failure"


# ============== ALLOWED CONFIGURATION ==============

# Only OpenAI is allowed for web search
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"

# Request source types (simplified)
RequestSource = Literal["api", "user", "internal"]


# ============== STUB FUNCTIONS ==============
# These maintain API compatibility but route to governance framework

def is_ai_disabled() -> bool:
    """Check if AI calls are disabled"""
    return os.getenv("DISABLE_AI_CALLS", "").lower() in ("true", "1", "yes")


def get_openai_api_key() -> Optional[str]:
    """Get OpenAI API key - for web search only"""
    from backend.ai_governance.openai_gateway import _get_openai_api_key
    try:
        return _get_openai_api_key()
    except ValueError:
        return None


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
    DEPRECATED: Use ai_governance.gemini_gateway for email operations
    or ai_governance.openai_gateway for web search.
    
    This function now only supports web search operations.
    All email-related operations will raise an error.
    """
    _deprecation_warning("chat_completion")
    
    # Detect if this is an email operation (forbidden for OpenAI)
    email_keywords = ["classify", "email", "summarize", "extraction"]
    prompt_text = " ".join([m.get("content", "") for m in messages]).lower()
    
    if any(kw in prompt_text for kw in email_keywords):
        raise ValueError(
            "Email operations are forbidden for OpenAI. "
            "Use backend.ai_governance.gemini_gateway for email classification/summarization."
        )
    
    # Route to OpenAI gateway for web search
    from backend.ai_governance.openai_gateway import get_openai_gateway
    
    gateway = get_openai_gateway()
    
    # Extract query from messages
    user_message = next((m for m in messages if m.get("role") == "user"), {})
    query = user_message.get("content", "")
    
    result = gateway.web_search(query)
    
    return {
        "content": str(result.get("results", [])),
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "model": OPENAI_DEFAULT_MODEL,
        "provider": "openai",
        "success": result.get("success", False),
        "error": result.get("error")
    }


def get_model_for_task(task_type: str = "default") -> tuple:
    """
    DEPRECATED: Task routing is now handled by ai_governance module.
    
    Returns:
        Always returns OpenAI for web search, raises for other tasks.
    """
    _deprecation_warning("get_model_for_task")
    
    web_tasks = {"web_search", "company_discovery", "web_enrichment"}
    
    if task_type in web_tasks:
        return ("openai", OPENAI_DEFAULT_MODEL)
    else:
        raise ValueError(
            f"Task '{task_type}' is not allowed through this wrapper. "
            "Use backend.ai_governance.gemini_gateway for email tasks."
        )


# ============== REMOVED FUNCTIONS ==============
# These functions have been removed and will raise errors

def get_deepseek_api_key():
    """REMOVED: DeepSeek is completely removed from this codebase."""
    raise RuntimeError(
        "DeepSeek has been REMOVED from this codebase. "
        "This function no longer exists. "
        "Use backend.ai_governance.gemini_gateway for email operations."
    )


def get_deepseek_client():
    """REMOVED: DeepSeek is completely removed from this codebase."""
    raise RuntimeError(
        "DeepSeek has been REMOVED from this codebase. "
        "This function no longer exists."
    )


def reset_clients():
    """REMOVED: Client singletons are now managed by ai_governance module."""
    _deprecation_warning("reset_clients")
    pass  # No-op for backwards compatibility


# ============== CONSTANTS FOR BACKWARDS COMPATIBILITY ==============

# These are kept to prevent import errors but should not be used
DEFAULT_MAX_OUTPUT_TOKENS = 300
BACKGROUND_MAX_OUTPUT_TOKENS = 150
INTERNAL_MAX_OUTPUT_TOKENS = 200
ESCALATED_MAX_OUTPUT_TOKENS = 500
MAX_RETRIES = 0  # NO RETRIES as per governance spec
ESCALATION_CONFIDENCE_THRESHOLD = 0.7

# Model costs (for reference only - actual billing handled by providers)
MODEL_COSTS = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gemini-2.0-flash": {"input": 0.0, "output": 0.0},  # Free tier
}
