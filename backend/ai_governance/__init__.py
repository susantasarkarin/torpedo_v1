"""
AI GOVERNANCE FRAMEWORK
=======================
Consolidated AI functionality with strict provider boundaries, hard daily limits, and zero duplication.

Provider Responsibilities (STRICT):
- Gemini: ONLY for email classification, summarization, lead extraction from emails
- ChatGPT/OpenAI: ONLY for web search and external lead discovery
- DeepSeek: COMPLETELY REMOVED (any reference = build failure)

This module is the SINGLE entry point for all AI operations.
"""

from .gemini_gateway import (
    GeminiGateway,
    get_gemini_gateway,
    classify_email,
    summarize_email,
    extract_leads_from_email,
    GeminiDailyLimitExceeded,
    EmailAlreadyClassified,
)

from .openai_gateway import (
    OpenAIGateway,
    get_openai_gateway,
    web_search,
    discover_leads_external,
    OpenAIWebSearchOnly,
)

from .governance_checks import (
    validate_no_deepseek,
    check_gemini_daily_limit,
    check_email_classification_status,
    GovernanceViolation,
)

__all__ = [
    # Gemini (Email Intelligence ONLY)
    'GeminiGateway',
    'get_gemini_gateway',
    'classify_email',
    'summarize_email',
    'extract_leads_from_email',
    'GeminiDailyLimitExceeded',
    'EmailAlreadyClassified',
    
    # OpenAI (Web Search ONLY)
    'OpenAIGateway',
    'get_openai_gateway',
    'web_search',
    'discover_leads_external',
    'OpenAIWebSearchOnly',
    
    # Governance
    'validate_no_deepseek',
    'check_gemini_daily_limit',
    'check_email_classification_status',
    'GovernanceViolation',
]
