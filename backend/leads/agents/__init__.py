"""
Multi-Agent Lead Generation System
===================================

Phase-based agents for automated lead processing pipeline:

- Phase 3 Agent: Email Pattern Discovery + Company Cache Intelligence
- Phase 4 Agent: Testing & Validation 
- Phase 5 Agent: Automated Enrichment Pipeline
- Phase 6 Agent: CRM Integration
- Orchestrator: Combines, validates, and coordinates all agents

Each agent is autonomous and can be run independently or orchestrated together.
"""

from .base_agent import BaseAgent, AgentResult, AgentStatus
from .phase3_agent import Phase3Agent
from .phase4_agent import Phase4Agent
from .phase5_agent import Phase5Agent
from .phase6_agent import Phase6Agent
from .orchestrator import OrchestratorAgent

__all__ = [
    'BaseAgent',
    'AgentResult', 
    'AgentStatus',
    'Phase3Agent',
    'Phase4Agent',
    'Phase5Agent',
    'Phase6Agent',
    'OrchestratorAgent',
]
