"""
AI GOVERNANCE FRAMEWORK
=======================
Consolidated AI functionality with governance checks, hard daily limits, and zero duplication.

Provider: OpenAI (pay-as-you-go) for all AI operations.

This module is the SINGLE entry point for all AI operations.
"""

from .ai_gateway import (
    AIGateway,
    get_ai_gateway,
    classify_email,
    summarize_email,
    extract_leads_from_email,
    EmailAlreadyClassified,
)

from .governance_checks import (
    validate_no_deepseek,
    check_gemini_daily_limit,
    check_ai_daily_limit,
    check_email_classification_status,
    GovernanceViolation,
    AIDailyLimitExceeded,
    GeminiDailyLimitExceeded,
)

# Backward-compatible aliases
get_gemini_gateway = get_ai_gateway
GeminiGateway = AIGateway

# Try importing openai_gateway if it still exists (for web_search)
try:
    from .openai_gateway import (
        OpenAIGateway,
        get_openai_gateway,
        web_search,
        discover_leads_external,
        OpenAIWebSearchOnly,
    )
except ImportError:
    OpenAIGateway = None
    get_openai_gateway = None
    web_search = None
    discover_leads_external = None
    OpenAIWebSearchOnly = None

__all__ = [
    # AI Gateway (OpenAI-powered)
    'AIGateway',
    'get_ai_gateway',
    'GeminiGateway',  # backward compat alias
    'get_gemini_gateway',  # backward compat alias
    'classify_email',
    'summarize_email',
    'extract_leads_from_email',
    'AIDailyLimitExceeded',
    'GeminiDailyLimitExceeded',  # backward compat alias
    'EmailAlreadyClassified',
    
    # OpenAI Web Search (if available)
    'OpenAIGateway',
    'get_openai_gateway',
    'web_search',
    'discover_leads_external',
    'OpenAIWebSearchOnly',
    
    # Governance
    'validate_no_deepseek',
    'check_gemini_daily_limit',
    'check_ai_daily_limit',
    'check_email_classification_status',
    'GovernanceViolation',
]
