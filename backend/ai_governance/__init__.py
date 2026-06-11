"""
AI GOVERNANCE FRAMEWORK
=======================
Consolidated AI functionality with governance checks, hard daily limits, and zero duplication.

Provider: Anthropic Claude — the ONLY AI provider in this codebase.

This module is the SINGLE entry point for all AI operations:
- ai_gateway:     task-specific operations (classify/summarize/extract/draft)
- claude_gateway: generic generate()/web_search() + drop-in chat clients
                  used by migrated call sites
"""

from .claude_gateway import (
    ClaudeGateway,
    get_claude_gateway,
    claude_chat_client,
    async_claude_chat_client,
    ClaudeChatClient,
    AsyncClaudeChatClient,
    ClaudeGenerativeModel,
)

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

# Web gateway (Claude-backed; OpenAI names kept for compat)
from .openai_gateway import (
    OpenAIGateway,
    get_openai_gateway,
    web_search,
    discover_leads_external,
    OpenAIWebSearchOnly,
)

__all__ = [
    # Claude gateway (generic governed access)
    'ClaudeGateway',
    'get_claude_gateway',
    'claude_chat_client',
    'async_claude_chat_client',
    'ClaudeChatClient',
    'AsyncClaudeChatClient',
    'ClaudeGenerativeModel',

    # AI Gateway (Claude-powered task operations)
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
