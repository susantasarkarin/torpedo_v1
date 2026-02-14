"""
ENTERPRISE OUTBOUND ENGINE
==========================

Consolidated, enterprise-grade email outreach system.

Features:
- Template-based email structure
- Optional AI-generated contextual block (NOT full email rewrite)
- Sticky mailbox assignment per lead
- Dynamic mailbox signature
- Thread continuity for follow-ups
- Controlled AI usage (150 token cap)
- State-machine based workflow progression
- Enterprise-safe sending limits
- Rate limiting and deliverability controls
- Comprehensive logging and observability

Architecture:
- models.py: Data models for leads, mailboxes, workflows
- workflow_engine.py: State machine for email sequence progression
- mailbox_manager.py: Mailbox assignment and health tracking
- ai_context_generator.py: AI context block generation (capped)
- template_renderer.py: Token replacement and template rendering
- sending_engine.py: Email sending with thread continuity
- rate_limiter.py: Per-mailbox rate limiting
- scheduler.py: Job queue for scheduled sends
- logging_service.py: Comprehensive logging

Usage:
    from outreach_engine import OutreachEngine
    
    engine = OutreachEngine(db)
    engine.send_campaign(campaign_id, lead_ids)
"""

from .models import (
    Lead,
    Mailbox,
    Campaign,
    WorkflowStep,
    EmailSend,
    WorkflowStatus,
    PersonalizationLevel,
    MailboxHealth,
)
from .workflow_engine import WorkflowEngine
from .mailbox_manager import MailboxManager
from .ai_context_generator import AIContextGenerator
from .template_renderer import TemplateRenderer
from .sending_engine import SendingEngine
from .rate_limiter import RateLimiter
from .scheduler import SendScheduler
from .logging_service import OutreachLogger

__all__ = [
    # Models
    "Lead",
    "Mailbox",
    "Campaign", 
    "WorkflowStep",
    "EmailSend",
    "WorkflowStatus",
    "PersonalizationLevel",
    "MailboxHealth",
    # Services
    "WorkflowEngine",
    "MailboxManager",
    "AIContextGenerator",
    "TemplateRenderer",
    "SendingEngine",
    "RateLimiter",
    "SendScheduler",
    "OutreachLogger",
]
