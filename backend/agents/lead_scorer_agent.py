"""
Lead Scorer Agent - Score and classify leads based on fit criteria
"""

import logging
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent, LEADS_PER_BATCH
from .schemas import (
    LeadScorerConfig,
    ScoredLeadResult,
    LeadScorerResult,
)

logger = logging.getLogger(__name__)


class LeadScorerAgent(BaseAgent[LeadScorerResult]):
    """
    Agent that scores and classifies leads based on fit criteria.
    Uses ChatGPT to analyze lead data and assign scores.
    
    Input: List of leads with enriched information
    Output: Scored leads with classification and recommendations
    """
    
    agent_name = "lead_scorer"
    agent_description = "Scores and classifies leads based on ICP fit"
    output_model = LeadScorerResult
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.agent_config = LeadScorerConfig(**(config or {}))
    
    def get_system_prompt(self) -> str:
        config = self.agent_config
        weights = config.scoring_weights
        
        weights_str = "\n".join([f"  - {k}: {v} points" for k, v in weights.items()])
        
        return f"""You are an expert B2B lead scoring specialist. Your task is to score and classify leads based on their fit with ideal customer criteria.

SCORING CRITERIA (Total: 100 points):
{weights_str}

CLASSIFICATION LEVELS:
- Seniority: C-Level, VP, Director, Manager, Senior, IC, Unknown
- Decision Level: Economic Buyer, Technical Buyer, User Buyer, Champion, Influencer, Unknown
- Buying Role: Decision Maker, Influencer, Gatekeeper, Practitioner, Unknown
- Department: Sales, Marketing, Engineering, Operations, Finance, HR, Product, Other

MINIMUM QUALIFICATION THRESHOLD: {config.minimum_score_threshold} points

OUTPUT FORMAT (JSON):
{{
    "scored_leads": [
        {{
            "lead_id": "original_lead_id",
            "full_name": "John Smith",
            "email": "john@company.com",
            "title": "VP of Sales",
            "company_name": "Acme Corp",
            "total_score": 85.0,
            "score_breakdown": {{
                "title_match": 25.0,
                "company_size": 20.0,
                "industry_fit": 20.0,
                "decision_level": 15.0,
                "email_available": 10.0,
                "linkedin_complete": 10.0
            }},
            "is_qualified": true,
            "seniority_level": "VP",
            "decision_level": "Economic Buyer",
            "buying_role": "Decision Maker",
            "department": "Sales",
            "persona": "Sales Leader",
            "priority_rank": 1,
            "recommended_approach": "Direct outreach emphasizing ROI and efficiency gains",
            "reasoning": "VP of Sales at mid-market SaaS company, strong decision-making authority"
        }}
    ],
    "total_scored": 10,
    "qualified_count": 7,
    "average_score": 72.5
}}"""
    
    def build_prompt(self, input_data: Any) -> str:
        """Build the prompt for scoring a batch of leads."""
        leads = []
        
        if isinstance(input_data, list):
            leads = input_data
        elif isinstance(input_data, dict):
            leads = input_data.get("leads", [input_data])
        
        config = self.agent_config
        
        # Format ideal criteria
        ideal_titles_str = ", ".join(config.ideal_titles) if config.ideal_titles else "any senior role"
        ideal_industries_str = ", ".join(config.ideal_industries) if config.ideal_industries else "any B2B industry"
        ideal_sizes_str = ", ".join(config.ideal_company_sizes) if config.ideal_company_sizes else "any size"
        
        # Format leads for the prompt
        leads_formatted = []
        for i, lead in enumerate(leads[:LEADS_PER_BATCH]):
            lead_str = f"""Lead {i+1}:
  - ID: {lead.get('lead_id', lead.get('_id', f'lead_{i+1}'))}
  - Name: {lead.get('full_name', lead.get('name', 'Unknown'))}
  - Title: {lead.get('title', 'Unknown')}
  - Email: {lead.get('email', 'Not available')}
  - Company: {lead.get('company_name', 'Unknown')}
  - Industry: {lead.get('company_industry', lead.get('industry', 'Unknown'))}
  - Company Size: {lead.get('company_size', lead.get('company_employee_count', 'Unknown'))}
  - LinkedIn: {lead.get('linkedin_url', 'Not provided')}
  - Location: {lead.get('location', lead.get('company_headquarters', 'Unknown'))}"""
            leads_formatted.append(lead_str)
        
        leads_text = "\n\n".join(leads_formatted)
        
        prompt = f"""Score and classify the following {len(leads_formatted)} leads:

{leads_text}

**Ideal Customer Profile:**
- Ideal Titles: {ideal_titles_str}
- Ideal Industries: {ideal_industries_str}
- Ideal Company Sizes: {ideal_sizes_str}
- Minimum Score for Qualification: {config.minimum_score_threshold}

**Requirements:**
1. Score each lead on a 0-100 scale based on the criteria
2. Provide a breakdown of points for each criterion
3. Classify the lead's seniority, decision level, buying role, and department
4. Mark leads as qualified if they meet the minimum score threshold
5. Rank leads by priority (1 = highest priority)
6. Provide a recommended approach and reasoning for each lead

Return all {len(leads_formatted)} leads with scores in the specified JSON format."""
        
        return prompt
    
    def parse_response(self, response_text: str) -> LeadScorerResult:
        """Parse the AI response into LeadScorerResult."""
        data = self._extract_json_from_response(response_text)
        
        scored_leads = []
        for lead_data in data.get("scored_leads", []):
            try:
                scored = ScoredLeadResult(
                    lead_id=lead_data.get("lead_id", ""),
                    full_name=lead_data.get("full_name", ""),
                    email=lead_data.get("email"),
                    title=lead_data.get("title", ""),
                    company_name=lead_data.get("company_name", ""),
                    total_score=float(lead_data.get("total_score", 0)),
                    score_breakdown=lead_data.get("score_breakdown", {}),
                    is_qualified=lead_data.get("is_qualified", False),
                    seniority_level=lead_data.get("seniority_level", "Unknown"),
                    decision_level=lead_data.get("decision_level", "Unknown"),
                    buying_role=lead_data.get("buying_role", "Unknown"),
                    department=lead_data.get("department", "Other"),
                    persona=lead_data.get("persona", "Unknown"),
                    priority_rank=lead_data.get("priority_rank", 0),
                    recommended_approach=lead_data.get("recommended_approach", ""),
                    reasoning=lead_data.get("reasoning", "")
                )
                scored_leads.append(scored)
            except Exception as e:
                logger.warning(f"Failed to parse scored lead: {e}")
                continue
        
        # Calculate stats
        qualified_count = len([l for l in scored_leads if l.is_qualified])
        total_score = sum(l.total_score for l in scored_leads)
        average_score = total_score / len(scored_leads) if scored_leads else 0
        
        return LeadScorerResult(
            scored_leads=scored_leads,
            total_scored=len(scored_leads),
            qualified_count=qualified_count,
            average_score=round(average_score, 1)
        )
    
    def score_leads_batch(self, leads: List[Dict[str, Any]]) -> LeadScorerResult:
        """
        Score a batch of leads.
        
        Args:
            leads: List of lead dicts with enriched information
            
        Returns:
            LeadScorerResult with scored leads
        """
        result = self.execute({"leads": leads}, use_web_search=False)  # No web search needed for scoring
        if result.success and result.data:
            return LeadScorerResult(**result.data)
        return LeadScorerResult()
