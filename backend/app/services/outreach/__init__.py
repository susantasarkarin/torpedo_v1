"""
AI-Powered Outreach System.

A comprehensive, modular system for intelligent cold outreach with:
- Lead intelligence extraction and scoring
- Personalized email generation
- Smart follow-up sequences
- Reply classification and auto-response
- Sender management and warmup
- Campaign optimization
- Safety guardrails

Usage:
    from app.services.outreach import OutreachOrchestrator
    
    orchestrator = OutreachOrchestrator(ai_client, db)
    result = await orchestrator.process_new_lead(...)
"""

from .orchestrator import (
    OutreachOrchestrator,
    OutreachResult,
    FollowUpResult,
    ReplyProcessingResult
)
from .lead_intelligence import (
    LeadIntelligenceService,
    LeadIntelligence,
    LeadScore,
    CompanyData
)
from .email_generator import (
    EmailGeneratorService,
    GeneratedEmail,
    EmailGenerationRequest,
    FollowUpRequest,
    SpamCheckResult
)
from .reply_handler import (
    ReplyHandlerService,
    ClassifiedReply,
    AutoResponse,
    ReplyContext
)
from .sender_manager import (
    SenderManagerService,
    SenderAccount,
    SenderAllocation,
    WarmupStage
)
from .optimizer import (
    CampaignOptimizerService,
    OptimizationReport,
    CampaignData,
    PerformanceMetrics
)
from .guardrails import (
    GuardrailsService,
    OutreachLimits,
    RiskLevel
)
from .scheduler import OutreachSchedulerService
from .webhook_handler import OutreachWebhookHandler
from .email_sender import EmailSenderService, SendEmailResult
from .master_prompts import (
    MASTER_SYSTEM_PROMPT,
    LEAD_INTELLIGENCE_PROMPT,
    LEAD_SCORING_PROMPT,
    EMAIL_GENERATION_PROMPT,
    FOLLOWUP_GENERATION_PROMPT,
    REPLY_CLASSIFIER_PROMPT,
    AUTO_RESPONSE_PROMPT,
    SENDER_ALLOCATION_PROMPT,
    WEEKLY_OPTIMIZATION_PROMPT,
    SPAM_CHECK_PROMPT
)

__all__ = [
    # Main orchestrator
    "OutreachOrchestrator",
    "OutreachResult",
    "FollowUpResult", 
    "ReplyProcessingResult",
    
    # Intelligence
    "LeadIntelligenceService",
    "LeadIntelligence",
    "LeadScore",
    "CompanyData",
    
    # Email generation
    "EmailGeneratorService",
    "GeneratedEmail",
    "EmailGenerationRequest",
    "FollowUpRequest",
    "SpamCheckResult",
    
    # Reply handling
    "ReplyHandlerService",
    "ClassifiedReply",
    "AutoResponse",
    "ReplyContext",
    
    # Sender management
    "SenderManagerService",
    "SenderAccount",
    "SenderAllocation",
    "WarmupStage",
    
    # Optimization
    "CampaignOptimizerService",
    "OptimizationReport",
    "CampaignData",
    "PerformanceMetrics",
    
    # Guardrails
    "GuardrailsService",
    "OutreachLimits",
    "RiskLevel",

    # Infra services
    "OutreachSchedulerService",
    "OutreachWebhookHandler",
    "EmailSenderService",
    "SendEmailResult",
]
