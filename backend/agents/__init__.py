"""
AI Lead Generation Agents
=========================
5 specialized agents for automated lead generation using ChatGPT 4o-mini with web search.

Agents:
1. CompanyDiscoveryAgent - Find companies matching ICP criteria
2. ContactFinderAgent - Find decision-makers at target companies
3. LeadEnricherAgent - Enrich leads with missing data
4. LeadScorerAgent - Score and classify leads
5. OutreachComposerAgent - Generate personalized outreach emails

Features:
- Batch processing (10 leads per API call)
- Daily limit of 1000 leads
- Configurable prompts via AgentConfig
- Deduplication against leads_raw collection
- Real-time progress via WebSocket
"""

from .base_agent import BaseAgent, AgentResult
from .schemas import (
    AgentConfig,
    CompanyDiscoveryConfig,
    ContactFinderConfig,
    LeadEnricherConfig,
    LeadScorerConfig,
    OutreachComposerConfig,
    CompanyResult,
    ContactResult,
    EnrichedLeadResult,
    ScoredLeadResult,
    OutreachDraftResult,
)
from .deduplication import LeadDeduplicator
from .company_discovery_agent import CompanyDiscoveryAgent
from .contact_finder_agent import ContactFinderAgent
from .lead_enricher_agent import LeadEnricherAgent
from .lead_scorer_agent import LeadScorerAgent
from .outreach_composer_agent import OutreachComposerAgent

# Agent registry for dynamic lookup
AGENT_REGISTRY = {
    "company_discovery": CompanyDiscoveryAgent,
    "contact_finder": ContactFinderAgent,
    "lead_enricher": LeadEnricherAgent,
    "lead_scorer": LeadScorerAgent,
    "outreach_composer": OutreachComposerAgent,
}

# Constants
DAILY_LEAD_LIMIT = 1000
LEADS_PER_BATCH = 10

__all__ = [
    # Base classes
    "BaseAgent",
    "AgentResult",
    # Configs
    "AgentConfig",
    "CompanyDiscoveryConfig",
    "ContactFinderConfig",
    "LeadEnricherConfig",
    "LeadScorerConfig",
    "OutreachComposerConfig",
    # Results
    "CompanyResult",
    "ContactResult",
    "EnrichedLeadResult",
    "ScoredLeadResult",
    "OutreachDraftResult",
    # Agents
    "CompanyDiscoveryAgent",
    "ContactFinderAgent",
    "LeadEnricherAgent",
    "LeadScorerAgent",
    "OutreachComposerAgent",
    # Utilities
    "LeadDeduplicator",
    "AGENT_REGISTRY",
    # Constants
    "DAILY_LEAD_LIMIT",
    "LEADS_PER_BATCH",
]
