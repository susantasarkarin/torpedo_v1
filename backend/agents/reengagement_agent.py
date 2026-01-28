"""
Reengagement Agent - Analyze dormant leads and create reengagement strategies
"""

import logging
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent, LEADS_PER_BATCH
from .schemas import (
    ReengagementAgentConfig,
    DormancyAnalysis,
    ReengagementStrategy,
    FreshAngle,
    ReengagementPlan,
    ReengagementResult,
)

logger = logging.getLogger(__name__)


class ReengagementAgent(BaseAgent[ReengagementResult]):
    """
    Agent that analyzes dormant leads and creates reengagement strategies.
    Identifies why leads went dormant and recommends fresh angles to re-engage them.
    
    Input: List of leads with outreach history
    Output: Reengagement plans with strategies and fresh angles
    """
    
    agent_name = "reengagement_agent"
    agent_description = "Analyzes dormant leads and creates reengagement strategies"
    output_model = ReengagementResult
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.agent_config = ReengagementAgentConfig(**(config or {}))
    
    def get_system_prompt(self) -> str:
        config = self.agent_config
        
        return f"""You are an expert B2B sales strategist specializing in reengaging dormant leads. Your task is to analyze why leads have gone dormant and create personalized reengagement strategies.

REENGAGEMENT FOCUS:
- Analyze engagement patterns and identify dormancy reasons
- Recommend specific reengagement strategies (soft-drip, trigger-based, or reset)
- Suggest fresh angles that differ from previous outreach
- Recommend sender rotation to break pattern
- Optimize timing for reengagement

DORMANCY CATEGORIES:
1. Never Opened: Lead never opened initial emails - needs attention-grabbing subject lines
2. Opened But No Reply: Lead showed interest but didn't respond - needs easier CTA
3. Replied Then Silent: Previous engagement stopped - needs to acknowledge relationship
4. Industry Changes: Company undergoing changes - needs timing awareness

REENGAGEMENT STRATEGIES:
1. SOFT_DRIP: Low-pressure educational content, wait for right moment to pitch
2. TRIGGER_BASED: Look for signals (job changes, company news, funding) to time outreach
3. RESET: Start fresh with completely new angle and value prop

SENDER ROTATION OPTIONS:
- Different team member (different first name to avoid being marked spam)
- Different title level (manager instead of individual contributor, or vice versa)
- Different tone from original sender

OUTPUT FORMAT (JSON):
{{
    "reengagement_plans": [
        {{
            "lead_id": "original_lead_id",
            "full_name": "John Smith",
            "email": "john@company.com",
            "company_name": "Acme Corp",
            "dormancy_analysis": {{
                "reason": "never_opened",
                "opened_last_email": false,
                "clicked_any_link": false,
                "replied_any": false,
                "days_since_last_engagement": 45,
                "engagement_pattern": "No opens in 3-email sequence",
                "industry_context": "SaaS sector facing budget cuts"
            }},
            "recommended_strategy": {{
                "strategy_type": "reset",
                "description": "Complete restart with new angle focused on cost savings",
                "expected_response_lift": 0.35,
                "next_action": "Send new 3-email sequence starting with attention-grabbing stat"
            }},
            "fresh_angle": {{
                "angle": "ROI-focused approach instead of feature-focused",
                "reasoning": "Previous outreach was feature-heavy; dormancy suggests leads care more about business outcomes",
                "suggested_copy": "Most SaaS teams are cutting software spend in 2024. Here's how we help companies do more with less..."
            }},
            "sender_to_use": "Sarah Chen, VP Sales (rotate from original sender)",
            "optimal_send_day": "Tuesday",
            "optimal_send_time": "10:00 AM",
            "subject_line_suggestion": "Quick win: Reduce your SaaS spend by 40%"
        }}
    ],
    "total_analyzed": 10,
    "total_dormant": 8,
    "strategy_distribution": {{
        "reset": 4,
        "soft_drip": 3,
        "trigger_based": 1
    }}
}}"""
    
    def build_prompt(self, input_data: Any) -> str:
        """Build the prompt for analyzing dormant leads."""
        leads = []
        
        if isinstance(input_data, list):
            leads = input_data
        elif isinstance(input_data, dict):
            leads = input_data.get("leads", [input_data])
        
        config = self.agent_config
        
        # Format leads with outreach history
        leads_formatted = []
        for i, lead in enumerate(leads[:LEADS_PER_BATCH]):
            outreach_history = lead.get('outreach_history', [])
            
            # Calculate engagement stats
            emails_sent = len(outreach_history)
            opened_count = sum(1 for e in outreach_history if e.get('opened'))
            clicked_count = sum(1 for e in outreach_history if e.get('clicked'))
            replied_count = sum(1 for e in outreach_history if e.get('replied'))
            
            # Get last engagement
            last_email = outreach_history[-1] if outreach_history else {}
            days_since = lead.get('days_since_last_email', 0)
            
            lead_str = f"""Lead {i+1}:
  - ID: {lead.get('lead_id', lead.get('_id', f'lead_{i+1}'))}
  - Name: {lead.get('full_name', lead.get('name', 'Unknown'))}
  - Title: {lead.get('title', 'Unknown')}
  - Email: {lead.get('email', 'Not available')}
  - Company: {lead.get('company_name', 'Unknown')}
  - Industry: {lead.get('company_industry', lead.get('industry', 'Unknown'))}
  - Company Size: {lead.get('company_size', 'Unknown')}
  - Location: {lead.get('location', 'Unknown')}
  
  OUTREACH HISTORY:
  - Total Emails Sent: {emails_sent}
  - Opened: {opened_count} ({opened_count*100//max(emails_sent,1)}%)
  - Clicked: {clicked_count}
  - Replied: {replied_count}
  - Days Since Last Email: {days_since}
  - Last Email Subject: {last_email.get('subject', 'Unknown')}
  - Last Email Opened: {last_email.get('opened', False)}
  - Last Email Clicked: {last_email.get('clicked', False)}"""
            
            leads_formatted.append(lead_str)
        
        leads_text = "\n\n".join(leads_formatted)
        
        prompt = f"""Create reengagement strategies for the following {len(leads_formatted)} dormant leads:

{leads_text}

**Reengagement Parameters:**
- Inactivity threshold that triggered reengagement: {config.inactivity_threshold_days} days
- Maximum reengagement attempts to allow: {config.max_reengagement_attempts}
- Focus value proposition: {config.focus_value_proposition}

**Sender Information:**
- Available sender: {config.sender_name or "Sales team member"}
- Title: {config.sender_title or "Sales Development Rep"}
- Company: {config.company_name or "Our company"}

**Requirements:**
1. Analyze why each lead went dormant based on engagement patterns
2. Recommend one of three strategies: reset, soft_drip, or trigger_based
3. For each lead, create a completely fresh angle that differs from previous outreach
4. Suggest sender rotation when appropriate (different person/title than original)
5. Recommend optimal day/time for reengagement
6. Provide a new subject line that breaks the pattern

Focus on leads that have been dormant for {config.inactivity_threshold_days}+ days. Return reengagement plans for all {len(leads_formatted)} leads in the specified JSON format."""
        
        return prompt
    
    def parse_response(self, response_text: str) -> ReengagementResult:
        """Parse the AI response into ReengagementResult."""
        data = self._extract_json_from_response(response_text)
        
        reengagement_plans = []
        strategy_distribution = {}
        
        for plan_data in data.get("reengagement_plans", []):
            try:
                # Parse dormancy analysis
                dormancy_data = plan_data.get("dormancy_analysis", {})
                dormancy = DormancyAnalysis(
                    reason=dormancy_data.get("reason", "unknown"),
                    opened_last_email=dormancy_data.get("opened_last_email", False),
                    clicked_any_link=dormancy_data.get("clicked_any_link", False),
                    replied_any=dormancy_data.get("replied_any", False),
                    days_since_last_engagement=dormancy_data.get("days_since_last_engagement", 0),
                    engagement_pattern=dormancy_data.get("engagement_pattern", ""),
                    industry_context=dormancy_data.get("industry_context", "")
                )
                
                # Parse strategy
                strategy_data = plan_data.get("recommended_strategy", {})
                strategy = ReengagementStrategy(
                    strategy_type=strategy_data.get("strategy_type", "reset"),
                    description=strategy_data.get("description", ""),
                    expected_response_lift=strategy_data.get("expected_response_lift", 0.0),
                    next_action=strategy_data.get("next_action", "")
                )
                
                # Track strategy distribution
                strategy_type = strategy.strategy_type
                strategy_distribution[strategy_type] = strategy_distribution.get(strategy_type, 0) + 1
                
                # Parse fresh angle
                angle_data = plan_data.get("fresh_angle", {})
                angle = FreshAngle(
                    angle=angle_data.get("angle", ""),
                    reasoning=angle_data.get("reasoning", ""),
                    suggested_copy=angle_data.get("suggested_copy", "")
                )
                
                # Create plan
                plan = ReengagementPlan(
                    lead_id=plan_data.get("lead_id", ""),
                    full_name=plan_data.get("full_name", ""),
                    email=plan_data.get("email"),
                    company_name=plan_data.get("company_name", ""),
                    dormancy_analysis=dormancy,
                    recommended_strategy=strategy,
                    fresh_angle=angle,
                    sender_to_use=plan_data.get("sender_to_use", ""),
                    optimal_send_day=plan_data.get("optimal_send_day", ""),
                    optimal_send_time=plan_data.get("optimal_send_time", ""),
                    subject_line_suggestion=plan_data.get("subject_line_suggestion", "")
                )
                reengagement_plans.append(plan)
            except Exception as e:
                logger.warning(f"Failed to parse reengagement plan: {e}")
                continue
        
        total_dormant = sum(1 for p in reengagement_plans 
                           if p.dormancy_analysis.days_since_last_engagement > 0)
        
        return ReengagementResult(
            reengagement_plans=reengagement_plans,
            total_analyzed=len(reengagement_plans),
            total_dormant=total_dormant,
            strategy_distribution=strategy_distribution
        )
    
    async def analyze_dormancy(self, lead: Dict, outreach_history: List[Dict]) -> DormancyAnalysis:
        """
        Analyze why a lead went dormant.
        
        Args:
            lead: Lead data
            outreach_history: List of outreach records
            
        Returns:
            DormancyAnalysis with reason and details
        """
        emails_sent = len(outreach_history)
        opened_count = sum(1 for e in outreach_history if e.get('opened'))
        clicked_count = sum(1 for e in outreach_history if e.get('clicked'))
        replied_count = sum(1 for e in outreach_history if e.get('replied'))
        
        # Determine reason based on patterns
        if emails_sent == 0:
            reason = "no_outreach"
        elif replied_count > 0:
            reason = "replied_then_silent"
        elif clicked_count > 0:
            reason = "clicked_but_no_reply"
        elif opened_count > 0:
            reason = "opened_but_no_reply"
        else:
            reason = "never_opened"
        
        engagement_pattern = f"{opened_count}/{emails_sent} opens, {clicked_count} clicks, {replied_count} replies"
        
        return DormancyAnalysis(
            reason=reason,
            opened_last_email=outreach_history[-1].get('opened', False) if outreach_history else False,
            clicked_any_link=clicked_count > 0,
            replied_any=replied_count > 0,
            days_since_last_engagement=lead.get('days_since_last_email', 0),
            engagement_pattern=engagement_pattern
        )
    
    async def generate_fresh_angle(self, lead: Dict, previous_campaigns: List[Dict]) -> FreshAngle:
        """
        Generate a completely fresh angle/value prop for this lead.
        
        Args:
            lead: Lead data
            previous_campaigns: List of previous campaigns sent to lead
            
        Returns:
            FreshAngle with new value proposition
        """
        # This would typically call the AI, but we provide a basic implementation
        # In practice, this would be integrated with the full agent execution
        
        # Extract previous themes to avoid repeating
        previous_angles = [c.get('angle', '') for c in previous_campaigns]
        
        return FreshAngle(
            angle="Fresh approach based on dormancy analysis",
            reasoning="Previous angles didn't resonate; suggest different value prop",
            suggested_copy="Consider a new angle that addresses unstated needs"
        )
    
    def create_reengagement_plan(self, leads: List[Dict[str, Any]]) -> ReengagementResult:
        """
        Create reengagement plans for dormant leads.
        
        Args:
            leads: List of lead dicts with outreach history
            
        Returns:
            ReengagementResult with reengagement plans
        """
        result = self.execute({"leads": leads}, use_web_search=False)
        if result.success and result.data:
            return ReengagementResult(**result.data)
        return ReengagementResult()
