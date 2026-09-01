"""
Lead Intelligence Service.

Extracts structured intelligence from company data and scores leads
to determine outreach priority.
"""

import json
import logging
from typing import Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================

class HiringSignals(BaseModel):
    active: bool = False
    types: Optional[list[str]] = None


class BuyerPersona(BaseModel):
    title: str
    reasoning: str


class LeadIntelligence(BaseModel):
    """Structured intelligence extracted from company data."""
    growth_stage: str = Field(..., description="Early / Scaling / Enterprise / Mature")
    business_priorities: list[str] = Field(default_factory=list)
    hiring_signals: HiringSignals = Field(default_factory=HiringSignals)
    expansion_indicators: list[str] = Field(default_factory=list)
    operational_bottlenecks: list[str] = Field(default_factory=list)
    revenue_pressure: int = Field(..., ge=1, le=10)
    buyer_persona: BuyerPersona
    urgency_score: int = Field(..., ge=1, le=10)
    personalization_hooks: list[str] = Field(default_factory=list, max_length=3)
    
    # Metadata
    extracted_at: datetime = Field(default_factory=datetime.utcnow)
    source_quality: Optional[str] = None


class ComponentScores(BaseModel):
    trigger_strength: int = Field(..., ge=0, le=20)
    growth_velocity: int = Field(..., ge=0, le=20)
    outbound_pain: int = Field(..., ge=0, le=20)
    solution_fit: int = Field(..., ge=0, le=20)
    accessibility: int = Field(..., ge=0, le=20)


class LeadScore(BaseModel):
    """Lead scoring result with priority tier."""
    lead_score: int = Field(..., ge=0, le=100)
    priority_tier: str = Field(..., pattern="^[ABC]$")
    component_scores: ComponentScores
    reasoning: str
    should_outreach: bool = Field(default=True)
    scored_at: datetime = Field(default_factory=datetime.utcnow)


class CompanyData(BaseModel):
    """Input data for intelligence extraction."""
    company_name: str
    website_text: str = ""
    about_text: str = ""
    careers_page: str = ""
    recent_news: str = ""
    industry: str = ""
    company_size: str = ""
    trigger_event: str = ""
    linkedin_data: Optional[dict] = None
    additional_context: Optional[str] = None


# =============================================================================
# Service Implementation
# =============================================================================

class LeadIntelligenceService:
    """
    Service for extracting and scoring lead intelligence.
    
    This service:
    1. Takes raw company data
    2. Extracts structured intelligence using AI
    3. Scores the lead for outreach priority
    """
    
    def __init__(self, ai_client: Any):
        """
        Initialize with an AI client.
        
        Args:
            ai_client: Client for AI API calls (OpenAI, Anthropic, etc.)
        """
        self.ai_client = ai_client
    
    async def extract_intelligence(self, company_data: CompanyData) -> LeadIntelligence:
        """
        Extract structured intelligence from company data.
        
        Args:
            company_data: Raw company information
            
        Returns:
            LeadIntelligence: Structured intelligence object
        """
        from .master_prompts import MASTER_SYSTEM_PROMPT, LEAD_INTELLIGENCE_PROMPT
        
        # Build context from company data
        context = self._build_extraction_context(company_data)
        
        # Truncate to avoid token limits
        context = self._truncate_context(context, max_chars=8000)
        
        try:
            response = await self.ai_client.chat.completions.create(
                model="claude-opus-4-8",
                messages=[
                    {"role": "system", "content": MASTER_SYSTEM_PROMPT},
                    {"role": "user", "content": f"{LEAD_INTELLIGENCE_PROMPT}\n\n---\n\nCOMPANY DATA:\n{context}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=1000
            )
            
            result = json.loads(response.choices[0].message.content)
            
            # Determine source quality based on available data
            source_quality = self._assess_source_quality(company_data)
            result["source_quality"] = source_quality
            
            return LeadIntelligence(**result)
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse intelligence response: {e}")
            raise ValueError("AI returned invalid JSON for intelligence extraction")
        except Exception as e:
            logger.error(f"Intelligence extraction failed: {e}")
            raise
    
    async def score_lead(
        self,
        intelligence: LeadIntelligence,
        solution_context: Optional[str] = None
    ) -> LeadScore:
        """
        Score a lead based on extracted intelligence.
        
        Args:
            intelligence: Extracted lead intelligence
            solution_context: Optional context about what we're selling
            
        Returns:
            LeadScore: Scoring result with priority tier
        """
        from .master_prompts import MASTER_SYSTEM_PROMPT, LEAD_SCORING_PROMPT
        
        context = f"""
INTELLIGENCE DATA:
{intelligence.model_dump_json(indent=2)}

{"SOLUTION CONTEXT:" + chr(10) + solution_context if solution_context else ""}
"""
        
        try:
            response = await self.ai_client.chat.completions.create(
                model="claude-opus-4-8",
                messages=[
                    {"role": "system", "content": MASTER_SYSTEM_PROMPT},
                    {"role": "user", "content": f"{LEAD_SCORING_PROMPT}\n\n---\n\n{context}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=500
            )
            
            result = json.loads(response.choices[0].message.content)
            result["should_outreach"] = result["lead_score"] >= 60
            
            return LeadScore(**result)
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse scoring response: {e}")
            raise ValueError("AI returned invalid JSON for lead scoring")
        except Exception as e:
            logger.error(f"Lead scoring failed: {e}")
            raise
    
    async def extract_and_score(
        self,
        company_data: CompanyData,
        solution_context: Optional[str] = None
    ) -> tuple[LeadIntelligence, LeadScore]:
        """
        Convenience method to extract intelligence and score in one call.
        
        Args:
            company_data: Raw company information
            solution_context: Optional context about what we're selling
            
        Returns:
            Tuple of (LeadIntelligence, LeadScore)
        """
        intelligence = await self.extract_intelligence(company_data)
        score = await self.score_lead(intelligence, solution_context)
        return intelligence, score
    
    def _build_extraction_context(self, data: CompanyData) -> str:
        """Build context string from company data."""
        sections = [
            f"Company: {data.company_name}",
            f"Industry: {data.industry}" if data.industry else None,
            f"Size: {data.company_size}" if data.company_size else None,
            f"\n--- WEBSITE CONTENT ---\n{data.website_text}" if data.website_text else None,
            f"\n--- ABOUT ---\n{data.about_text}" if data.about_text else None,
            f"\n--- CAREERS PAGE ---\n{data.careers_page}" if data.careers_page else None,
            f"\n--- RECENT NEWS ---\n{data.recent_news}" if data.recent_news else None,
            f"\n--- TRIGGER EVENT ---\n{data.trigger_event}" if data.trigger_event else None,
            f"\n--- ADDITIONAL CONTEXT ---\n{data.additional_context}" if data.additional_context else None,
        ]
        
        return "\n".join(filter(None, sections))
    
    def _truncate_context(self, context: str, max_chars: int) -> str:
        """Truncate context to stay within limits."""
        if len(context) <= max_chars:
            return context
        return context[:max_chars] + "\n\n[Content truncated for length]"
    
    def _assess_source_quality(self, data: CompanyData) -> str:
        """Assess the quality of source data."""
        score = 0
        
        if data.website_text and len(data.website_text) > 200:
            score += 2
        if data.about_text and len(data.about_text) > 100:
            score += 1
        if data.careers_page:
            score += 1
        if data.recent_news:
            score += 2
        if data.trigger_event:
            score += 2
        if data.linkedin_data:
            score += 1
        
        if score >= 7:
            return "high"
        elif score >= 4:
            return "medium"
        else:
            return "low"
