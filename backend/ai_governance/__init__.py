"""
AI GOVERNANCE FRAMEWORK
=======================
Consolidated AI functionality with governance checks, hard daily limits, and zero duplication.

Provider: Anthropic Claude, called through the platform_core.ladder config
(fast = haiku, smart = sonnet, escalation on failure or low confidence).

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
    
    # Governance
    'validate_no_deepseek',
    'check_gemini_daily_limit',
    'check_ai_daily_limit',
    'check_email_classification_status',
    'GovernanceViolation',
]
