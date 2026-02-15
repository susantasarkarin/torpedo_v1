"""
Automation Module - Autonomous lead routing, campaign setup, and decision logging

Provides:
- Autonomous lead routing based on campaign ICP matching
- AI-optimized email variant generation
- Intelligent campaign scheduling with historical data
- Full compliance logging with decision reasoning

Decision Logging:
All autonomous decisions are logged to campaign_decisions collection with:
- confidence_score
- reasoning (why this decision was made)
- input_context (what led to this decision)
- audit_signature (for compliance)

This enables:
- GDPR compliance (explainability)
- CAN-SPAM compliance (audit trail)
- Manual override/adjustment
"""

from .decision_logger import DecisionLogger
from .lead_router import LeadRouter
from .email_optimizer import EmailOptimizer
from .campaign_scheduler import CampaignScheduler

__all__ = [
    "DecisionLogger",
    "LeadRouter",
    "EmailOptimizer",
    "CampaignScheduler"
]
