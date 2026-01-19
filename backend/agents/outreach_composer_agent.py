"""
Outreach Composer Agent - Generate personalized outreach emails
"""

import logging
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent, LEADS_PER_BATCH
from .schemas import (
    OutreachComposerConfig,
    OutreachTone,
    OutreachDraftResult,
    OutreachComposerResult,
)

logger = logging.getLogger(__name__)


class OutreachComposerAgent(BaseAgent[OutreachComposerResult]):
    """
    Agent that generates personalized outreach emails for leads.
    Uses ChatGPT to create tailored email drafts based on lead and company information.
    
    Input: List of leads with enriched information
    Output: Personalized email drafts with subject lines
    """
    
    agent_name = "outreach_composer"
    agent_description = "Generates personalized outreach emails for leads"
    output_model = OutreachComposerResult
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.agent_config = OutreachComposerConfig(**(config or {}))
    
    def get_system_prompt(self) -> str:
        config = self.agent_config
        
        tone_descriptions = {
            OutreachTone.FORMAL: "formal and professional, suitable for enterprise executives",
            OutreachTone.PROFESSIONAL: "professional but approachable, balanced tone",
            OutreachTone.FRIENDLY: "friendly and conversational, warm but still business-appropriate",
            OutreachTone.CASUAL: "casual and relaxed, like messaging a colleague"
        }
        
        tone = config.tone
        if isinstance(tone, str):
            tone = OutreachTone(tone)
        tone_desc = tone_descriptions.get(tone, tone_descriptions[OutreachTone.PROFESSIONAL])
        
        return f"""You are an expert B2B sales copywriter. Your task is to write personalized outreach emails that get responses.

TONE: {tone_desc}

VALUE PROPOSITION: {config.value_proposition}

CALL TO ACTION: {config.call_to_action}

{"SENDER: " + config.sender_name + ", " + config.sender_title + " at " + config.company_name if config.sender_name else ""}

EMAIL GUIDELINES:
1. Keep emails under {config.max_words} words
2. {"Include a compelling subject line" if config.include_subject_line else "Do not include subject line"}
3. Personalization level: {config.personalization_level}
4. Start with something personal about them or their company
5. Connect their potential pain points to our value proposition
6. End with a clear, low-commitment call to action
7. No pushy sales language - be helpful and genuine

PERSONALIZATION HOOKS TO USE:
- Their specific job title and responsibilities
- Their company's industry and challenges
- Recent company news or achievements
- Common connections or mutual interests
- Their location/market

OUTPUT FORMAT (JSON):
{{
    "drafts": [
        {{
            "lead_id": "original_lead_id",
            "recipient_name": "John Smith",
            "recipient_email": "john@company.com",
            "recipient_company": "Acme Corp",
            "subject_line": "Quick question about [specific topic]",
            "email_body": "Hi John,\\n\\n[Email content here]\\n\\nBest,\\n[Sender name]",
            "personalization_hooks": ["VP of Sales role", "SaaS industry", "growth-stage company"],
            "tone_used": "professional",
            "word_count": 95,
            "variant_number": 1
        }}
    ],
    "total_generated": 10,
    "average_word_count": 92.5
}}"""
    
    def build_prompt(self, input_data: Any) -> str:
        """Build the prompt for composing emails for a batch of leads."""
        leads = []
        
        if isinstance(input_data, list):
            leads = input_data
        elif isinstance(input_data, dict):
            leads = input_data.get("leads", [input_data])
        
        config = self.agent_config
        
        # Format leads for the prompt
        leads_formatted = []
        for i, lead in enumerate(leads[:LEADS_PER_BATCH]):
            # Get name parts
            full_name = lead.get('full_name', lead.get('name', ''))
            first_name = lead.get('first_name', '')
            if not first_name and full_name:
                first_name = full_name.split()[0] if full_name else ''
            
            lead_str = f"""Lead {i+1}:
  - ID: {lead.get('lead_id', lead.get('_id', f'lead_{i+1}'))}
  - Name: {full_name}
  - First Name: {first_name}
  - Title: {lead.get('title', 'Unknown')}
  - Email: {lead.get('email', 'Not available')}
  - Company: {lead.get('company_name', 'Unknown')}
  - Industry: {lead.get('company_industry', lead.get('industry', 'Unknown'))}
  - Company Size: {lead.get('company_size', lead.get('company_employee_count', 'Unknown'))}
  - Location: {lead.get('location', lead.get('company_headquarters', 'Unknown'))}
  - LinkedIn: {lead.get('linkedin_url', 'Not provided')}
  - Score: {lead.get('total_score', 'Not scored')}
  - Recommended Approach: {lead.get('recommended_approach', 'Standard outreach')}"""
            leads_formatted.append(lead_str)
        
        leads_text = "\n\n".join(leads_formatted)
        
        prompt = f"""Write personalized outreach emails for the following {len(leads_formatted)} leads:

{leads_text}

**Email Requirements:**
- Tone: {config.tone.value if hasattr(config.tone, 'value') else config.tone}
- Maximum words: {config.max_words}
- Personalization level: {config.personalization_level}
- Include subject line: {config.include_subject_line}

**Value Proposition to Communicate:**
{config.value_proposition}

**Call to Action:**
{config.call_to_action}

{f"**Sign off as:** {config.sender_name}, {config.sender_title} at {config.company_name}" if config.sender_name else ""}

**Requirements:**
1. Write a unique, personalized email for each lead
2. Use their first name in the greeting
3. Reference something specific about their role or company
4. Keep each email under {config.max_words} words
5. Make the subject line compelling and specific to them
6. Include 2-3 personalization hooks per email

Return all {len(leads_formatted)} email drafts in the specified JSON format."""
        
        return prompt
    
    def parse_response(self, response_text: str) -> OutreachComposerResult:
        """Parse the AI response into OutreachComposerResult."""
        data = self._extract_json_from_response(response_text)
        
        drafts = []
        total_words = 0
        
        for draft_data in data.get("drafts", []):
            try:
                word_count = draft_data.get("word_count", 0)
                if not word_count and draft_data.get("email_body"):
                    word_count = len(draft_data["email_body"].split())
                
                total_words += word_count
                
                draft = OutreachDraftResult(
                    lead_id=draft_data.get("lead_id", ""),
                    recipient_name=draft_data.get("recipient_name", ""),
                    recipient_email=draft_data.get("recipient_email"),
                    recipient_company=draft_data.get("recipient_company", ""),
                    subject_line=draft_data.get("subject_line", ""),
                    email_body=draft_data.get("email_body", ""),
                    personalization_hooks=draft_data.get("personalization_hooks", []),
                    tone_used=draft_data.get("tone_used", "professional"),
                    word_count=word_count,
                    variant_number=draft_data.get("variant_number", 1)
                )
                drafts.append(draft)
            except Exception as e:
                logger.warning(f"Failed to parse email draft: {e}")
                continue
        
        average_words = total_words / len(drafts) if drafts else 0
        
        return OutreachComposerResult(
            drafts=drafts,
            total_generated=len(drafts),
            average_word_count=round(average_words, 1)
        )
    
    def compose_emails_batch(self, leads: List[Dict[str, Any]]) -> OutreachComposerResult:
        """
        Compose emails for a batch of leads.
        
        Args:
            leads: List of lead dicts with enriched information
            
        Returns:
            OutreachComposerResult with email drafts
        """
        result = self.execute({"leads": leads}, use_web_search=False)  # No web search needed
        if result.success and result.data:
            return OutreachComposerResult(**result.data)
        return OutreachComposerResult()
