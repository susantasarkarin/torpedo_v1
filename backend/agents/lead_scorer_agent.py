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
        Score a batch of leads using AI.
        
        Args:
            leads: List of lead dicts with enriched information
            
        Returns:
            LeadScorerResult with scored leads
        """
        result = self.execute({"leads": leads}, use_web_search=False)  # No web search needed for scoring
        if result.success and result.data:
            return LeadScorerResult(**result.data)
        return LeadScorerResult()

    def score_leads_rule_based(self, leads: List[Dict[str, Any]]) -> LeadScorerResult:
        """
        Score leads using hardcoded weights — NO AI calls.
        Same output format as AI scoring for drop-in compatibility.
        """
        config = self.agent_config
        weights = config.scoring_weights
        
        scored_leads = []
        for i, lead in enumerate(leads):
            try:
                score_breakdown = {}
                
                # 1. Title match scoring
                title = (lead.get("title") or "").lower()
                title_score = 0.0
                seniority_level = "Unknown"
                decision_level = "Unknown"
                buying_role = "Unknown"
                department = "Other"
                
                title_tiers = {
                    "c-level": (1.0, ["ceo", "cto", "cfo", "coo", "cmo", "cro", "chief"]),
                    "vp": (0.85, ["vp", "vice president", "evp", "svp"]),
                    "director": (0.7, ["director", "head of"]),
                    "manager": (0.5, ["manager", "lead", "senior"]),
                    "ic": (0.25, ["analyst", "specialist", "coordinator", "associate", "engineer"]),
                }
                for tier_name, (multiplier, keywords) in title_tiers.items():
                    if any(kw in title for kw in keywords):
                        title_score = weights.get("title_match", 25.0) * multiplier
                        seniority_level = {"c-level": "C-Level", "vp": "VP", "director": "Director", "manager": "Manager", "ic": "IC"}.get(tier_name, "Unknown")
                        break
                
                # Decision level from seniority
                decision_map = {
                    "C-Level": "Economic Buyer", "VP": "Economic Buyer",
                    "Director": "Technical Buyer", "Manager": "User Buyer", "IC": "Influencer",
                }
                decision_level = decision_map.get(seniority_level, "Unknown")
                
                # Buying role from seniority
                buying_map = {
                    "C-Level": "Decision Maker", "VP": "Decision Maker",
                    "Director": "Influencer", "Manager": "Practitioner", "IC": "Practitioner",
                }
                buying_role = buying_map.get(seniority_level, "Unknown")
                
                # Department detection
                dept_keywords = {
                    "Sales": ["sales", "business development", "account", "revenue"],
                    "Marketing": ["marketing", "growth", "brand", "content", "demand gen"],
                    "Engineering": ["engineering", "development", "software", "tech", "devops"],
                    "Operations": ["operations", "ops", "supply chain", "logistics"],
                    "Finance": ["finance", "accounting", "controller", "treasury"],
                    "HR": ["human resources", "hr", "people", "talent", "recruiting"],
                    "Product": ["product", "ux", "design"],
                }
                for dept_name, keywords in dept_keywords.items():
                    if any(kw in title for kw in keywords):
                        department = dept_name
                        break
                
                score_breakdown["title_match"] = round(title_score, 1)
                
                # Check if title is in ideal_titles
                if config.ideal_titles:
                    ideal_match = any(t.lower() in title for t in config.ideal_titles)
                    if ideal_match:
                        score_breakdown["title_match"] = weights.get("title_match", 25.0)
                
                # 2. Company size scoring
                company_size = str(lead.get("company_size", lead.get("company_employee_count", "")))
                # "Unknown" is the classifier saying it could not tell — it is the
                # ABSENCE of data, not data. Treat it like an empty string so it
                # cannot earn the "some data > no data" credit below. This matters
                # now that CompanySize.UNKNOWN exists (models.py): before it was
                # added, such leads failed classification outright and never
                # reached the scorer, so the truthiness check was harmless.
                if company_size.strip() in ("Unknown", ""):
                    company_size = ""
                size_score = 0.0
                if company_size and config.ideal_company_sizes:
                    if company_size in config.ideal_company_sizes:
                        size_score = weights.get("company_size", 20.0)
                    elif any(s in company_size for s in ["51", "200", "1000"]):
                        size_score = weights.get("company_size", 20.0) * 0.5
                elif company_size:
                    size_score = weights.get("company_size", 20.0) * 0.3  # Some data > no data
                score_breakdown["company_size"] = round(size_score, 1)
                
                # 3. Industry fit scoring
                industry = (lead.get("company_industry") or lead.get("industry") or "").lower()
                industry_score = 0.0
                if industry and config.ideal_industries:
                    if any(ind.lower() in industry for ind in config.ideal_industries):
                        industry_score = weights.get("industry_fit", 20.0)
                    else:
                        industry_score = weights.get("industry_fit", 20.0) * 0.2  # Non-ideal but known
                elif industry:
                    industry_score = weights.get("industry_fit", 20.0) * 0.3
                score_breakdown["industry_fit"] = round(industry_score, 1)
                
                # 4. Decision level scoring (derived from title)
                decision_scores = {
                    "Economic Buyer": 1.0, "Technical Buyer": 0.7,
                    "User Buyer": 0.4, "Influencer": 0.3, "Unknown": 0.1,
                }
                dl_score = weights.get("decision_level", 15.0) * decision_scores.get(decision_level, 0.1)
                score_breakdown["decision_level"] = round(dl_score, 1)
                
                # 5. Email available
                has_email = bool(lead.get("email"))
                email_score = weights.get("email_available", 10.0) if has_email else 0.0
                score_breakdown["email_available"] = round(email_score, 1)
                
                # 6. LinkedIn complete
                has_linkedin = bool(lead.get("linkedin_url"))
                linkedin_score = weights.get("linkedin_complete", 10.0) if has_linkedin else 0.0
                score_breakdown["linkedin_complete"] = round(linkedin_score, 1)
                
                # Total
                total_score = sum(score_breakdown.values())
                total_score = round(min(total_score, 100.0), 1)
                is_qualified = total_score >= config.minimum_score_threshold
                
                # Persona
                persona = f"{department} {seniority_level}".strip()
                if persona == "Other Unknown":
                    persona = "Unknown"
                
                # Recommended approach based on seniority
                approach_map = {
                    "C-Level": "Executive positioning — focus on strategic ROI and competitive advantage",
                    "VP": "Department-level impact — emphasize efficiency gains and team productivity",
                    "Director": "Operational value — highlight process improvement and implementation ease",
                    "Manager": "Day-to-day benefit — show how it makes their job easier",
                    "IC": "Technical merit — demonstrate capabilities and ease of use",
                }
                recommended_approach = approach_map.get(seniority_level, "Research required — insufficient data for approach recommendation")
                
                scored = ScoredLeadResult(
                    lead_id=str(lead.get("lead_id", lead.get("_id", f"lead_{i+1}"))),
                    full_name=lead.get("full_name", lead.get("name", "")),
                    email=lead.get("email"),
                    title=lead.get("title", ""),
                    company_name=lead.get("company_name", ""),
                    total_score=total_score,
                    score_breakdown=score_breakdown,
                    is_qualified=is_qualified,
                    seniority_level=seniority_level,
                    decision_level=decision_level,
                    buying_role=buying_role,
                    department=department,
                    persona=persona,
                    priority_rank=0,  # Will be set after sorting
                    recommended_approach=recommended_approach,
                    reasoning=f"Rule-based scoring: {total_score}/100 ({'qualified' if is_qualified else 'not qualified'})"
                )
                scored_leads.append(scored)
            except Exception as e:
                logger.warning(f"Failed to score lead rule-based: {e}")
                continue
        
        # Assign priority ranks
        scored_leads.sort(key=lambda l: l.total_score, reverse=True)
        for rank, lead in enumerate(scored_leads, 1):
            lead.priority_rank = rank
        
        qualified_count = len([l for l in scored_leads if l.is_qualified])
        total_score = sum(l.total_score for l in scored_leads)
        average_score = total_score / len(scored_leads) if scored_leads else 0
        
        return LeadScorerResult(
            scored_leads=scored_leads,
            total_scored=len(scored_leads),
            qualified_count=qualified_count,
            average_score=round(average_score, 1)
        )
