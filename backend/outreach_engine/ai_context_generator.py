"""
AI CONTEXT GENERATOR
====================

Generates AI contextual paragraph for personalization.

STRICT RULES:
- AI does NOT rewrite entire email
- AI only generates a contextual paragraph block (2-3 sentences)
- AI output capped at 150 tokens
- AI block generated ONCE per lead per campaign
- Follow-ups REUSE stored AI block (no regeneration)
- AI block stored in lead record

Personalization Levels:
- Light: No AI, token replacement only
- Medium: Token replacement + AI context block
- Heavy: Token replacement + AI context block + one AI hook sentence
"""

import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from pymongo.database import Database
import openai

from .models import PersonalizationLevel

logger = logging.getLogger(__name__)

# AI Configuration
AI_TOKEN_LIMIT = 150  # Hard cap on AI tokens per lead
AI_MODEL = "gpt-4o-mini"  # Cost-effective model for short generations


class AIContextGenerator:
    """
    Generates AI contextual paragraphs for email personalization.
    
    Responsibilities:
    - Generate context block for new leads
    - Reuse existing context block for follow-ups
    - Enforce token limits
    - Log token usage
    """
    
    # Prompt template for context generation
    CONTEXT_PROMPT = """You are writing a short contextual paragraph for a B2B outreach email.

Do NOT rewrite the entire email.
Only write 2-3 sentences.

Context:
Company: {company}
Industry: {industry}
Role: {title}
Offering: Market research, consumer insights, ad testing, brand lift studies.

Write a relevant observation or potential research angle that could be useful to this company.

Keep it professional, neutral, and non-salesy.
Maximum 120 words.
No greeting.
No closing."""

    HOOK_PROMPT = """Write ONE compelling opening sentence that could be used in a B2B email.

Context:
Company: {company}
Industry: {industry}
Role: {title}

The sentence should:
- Be professional and relevant
- Reference something specific about their industry or role
- Not be salesy
- Be under 30 words

Only output the sentence, nothing else."""
    
    def __init__(
        self,
        db: Database,
        api_key: Optional[str] = None
    ):
        """
        Initialize AI context generator.
        
        Args:
            db: MongoDB database instance
            api_key: OpenAI API key (falls back to env)
        """
        self.db = db
        self.leads_collection = db["outreach_leads_v2"]
        self.logs_collection = db["ai_usage_logs"]
        
        # Setup OpenAI
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if self.api_key:
            openai.api_key = self.api_key
    
    def get_or_generate_context_block(
        self,
        lead_id: str,
        personalization_level: PersonalizationLevel,
        force_regenerate: bool = False
    ) -> Tuple[Optional[str], int]:
        """
        Get existing AI context block or generate new one.
        
        IMPORTANT: AI blocks are generated ONCE and reused for follow-ups.
        
        Args:
            lead_id: Lead to get/generate context for
            personalization_level: Level of personalization
            force_regenerate: Force regeneration (should rarely be True)
            
        Returns:
            Tuple of (context_block, tokens_used)
        """
        # Light personalization = no AI
        if personalization_level == PersonalizationLevel.LIGHT:
            return None, 0
        
        # Get lead
        lead = self.leads_collection.find_one({"lead_id": lead_id})
        if not lead:
            logger.error(f"Lead {lead_id} not found")
            return None, 0
        
        # Check for existing context block (REUSE for follow-ups)
        existing_block = lead.get("ai_context_block")
        if existing_block and not force_regenerate:
            logger.info(f"Reusing existing AI context block for lead {lead_id}")
            return existing_block, 0  # No new tokens used
        
        # Generate new context block
        context_block, tokens_used = self._generate_context_block(lead)
        
        if context_block:
            # Store in lead record
            now = datetime.utcnow()
            self.leads_collection.update_one(
                {"lead_id": lead_id},
                {"$set": {
                    "ai_context_block": context_block,
                    "ai_context_generated_at": now,
                    "ai_tokens_used": lead.get("ai_tokens_used", 0) + tokens_used,
                    "updated_at": now,
                }}
            )
            
            # Log usage
            self._log_ai_usage(
                lead_id=lead_id,
                campaign_id=lead.get("campaign_id"),
                tokens_used=tokens_used,
                generation_type="context_block"
            )
            
            logger.info(f"Generated AI context block for lead {lead_id} ({tokens_used} tokens)")
        
        return context_block, tokens_used
    
    def generate_hook_sentence(
        self,
        lead_id: str,
        personalization_level: PersonalizationLevel
    ) -> Tuple[Optional[str], int]:
        """
        Generate AI hook sentence for HEAVY personalization.
        
        Only used for Heavy personalization level.
        
        Args:
            lead_id: Lead to generate hook for
            personalization_level: Must be HEAVY
            
        Returns:
            Tuple of (hook_sentence, tokens_used)
        """
        if personalization_level != PersonalizationLevel.HEAVY:
            return None, 0
        
        lead = self.leads_collection.find_one({"lead_id": lead_id})
        if not lead:
            return None, 0
        
        # Check token budget
        current_usage = lead.get("ai_tokens_used", 0)
        remaining_budget = AI_TOKEN_LIMIT - current_usage
        
        if remaining_budget < 50:  # Need at least 50 tokens for hook
            logger.warning(f"Insufficient token budget for hook (lead {lead_id})")
            return None, 0
        
        hook, tokens_used = self._generate_hook(lead)
        
        if hook and tokens_used > 0:
            # Update token usage
            self.leads_collection.update_one(
                {"lead_id": lead_id},
                {"$inc": {"ai_tokens_used": tokens_used}}
            )
            
            # Log usage
            self._log_ai_usage(
                lead_id=lead_id,
                campaign_id=lead.get("campaign_id"),
                tokens_used=tokens_used,
                generation_type="hook_sentence"
            )
        
        return hook, tokens_used
    
    def _generate_context_block(
        self,
        lead: Dict[str, Any]
    ) -> Tuple[Optional[str], int]:
        """
        Generate context block using AI.
        
        Args:
            lead: Lead document
            
        Returns:
            Tuple of (context_block, tokens_used)
        """
        if not self.api_key:
            logger.warning("OpenAI API key not configured")
            return None, 0
        
        # Build prompt
        prompt = self.CONTEXT_PROMPT.format(
            company=lead.get("company", "the company"),
            industry=lead.get("industry", "their industry"),
            title=lead.get("title", "their role")
        )
        
        try:
            response = openai.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a professional B2B communication assistant."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100,  # Limit output
                temperature=0.7
            )
            
            content = response.choices[0].message.content.strip()
            tokens_used = response.usage.total_tokens if response.usage else 0
            
            # Enforce token limit on usage tracking
            if tokens_used > AI_TOKEN_LIMIT:
                tokens_used = AI_TOKEN_LIMIT
            
            return content, tokens_used
            
        except Exception as e:
            logger.error(f"AI context generation failed: {e}")
            return None, 0
    
    def _generate_hook(
        self,
        lead: Dict[str, Any]
    ) -> Tuple[Optional[str], int]:
        """
        Generate hook sentence using AI.
        
        Args:
            lead: Lead document
            
        Returns:
            Tuple of (hook_sentence, tokens_used)
        """
        if not self.api_key:
            return None, 0
        
        prompt = self.HOOK_PROMPT.format(
            company=lead.get("company", "the company"),
            industry=lead.get("industry", "their industry"),
            title=lead.get("title", "their role")
        )
        
        try:
            response = openai.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=50,  # Short output
                temperature=0.7
            )
            
            content = response.choices[0].message.content.strip()
            tokens_used = response.usage.total_tokens if response.usage else 0
            
            return content, tokens_used
            
        except Exception as e:
            logger.error(f"AI hook generation failed: {e}")
            return None, 0
    
    def _log_ai_usage(
        self,
        lead_id: str,
        campaign_id: Optional[str],
        tokens_used: int,
        generation_type: str
    ):
        """Log AI token usage for observability"""
        log_entry = {
            "lead_id": lead_id,
            "campaign_id": campaign_id,
            "tokens_used": tokens_used,
            "generation_type": generation_type,
            "model": AI_MODEL,
            "logged_at": datetime.utcnow()
        }
        
        try:
            self.logs_collection.insert_one(log_entry)
        except Exception as e:
            logger.warning(f"Failed to log AI usage: {e}")
    
    def get_token_usage(self, lead_id: str) -> int:
        """
        Get total AI tokens used for a lead.
        
        Args:
            lead_id: Lead to check
            
        Returns:
            Total tokens used
        """
        lead = self.leads_collection.find_one(
            {"lead_id": lead_id},
            {"ai_tokens_used": 1}
        )
        
        return lead.get("ai_tokens_used", 0) if lead else 0
    
    def get_remaining_budget(self, lead_id: str) -> int:
        """
        Get remaining AI token budget for a lead.
        
        Args:
            lead_id: Lead to check
            
        Returns:
            Remaining tokens available
        """
        used = self.get_token_usage(lead_id)
        return max(0, AI_TOKEN_LIMIT - used)
    
    def get_campaign_token_stats(self, campaign_id: str) -> Dict[str, Any]:
        """
        Get AI token statistics for a campaign.
        
        Returns:
            Dictionary with token usage stats
        """
        pipeline = [
            {"$match": {"campaign_id": campaign_id}},
            {"$group": {
                "_id": None,
                "total_tokens": {"$sum": "$ai_tokens_used"},
                "leads_with_ai": {"$sum": {"$cond": [{"$gt": ["$ai_tokens_used", 0]}, 1, 0]}},
                "avg_tokens_per_lead": {"$avg": "$ai_tokens_used"},
                "max_tokens": {"$max": "$ai_tokens_used"},
            }}
        ]
        
        results = list(self.leads_collection.aggregate(pipeline))
        
        if results:
            return {
                "campaign_id": campaign_id,
                "total_tokens_used": results[0].get("total_tokens", 0),
                "leads_with_ai": results[0].get("leads_with_ai", 0),
                "avg_tokens_per_lead": round(results[0].get("avg_tokens_per_lead", 0), 2),
                "max_tokens_used": results[0].get("max_tokens", 0),
                "token_limit_per_lead": AI_TOKEN_LIMIT
            }
        
        return {
            "campaign_id": campaign_id,
            "total_tokens_used": 0,
            "leads_with_ai": 0,
            "avg_tokens_per_lead": 0,
            "max_tokens_used": 0,
            "token_limit_per_lead": AI_TOKEN_LIMIT
        }


class MockAIContextGenerator(AIContextGenerator):
    """
    Mock generator for testing without API calls.
    """
    
    def _generate_context_block(
        self,
        lead: Dict[str, Any]
    ) -> Tuple[Optional[str], int]:
        """Generate mock context block"""
        company = lead.get("company", "your company")
        industry = lead.get("industry", "your industry")
        
        mock_block = (
            f"Companies in the {industry} sector are increasingly leveraging consumer insights "
            f"to drive product development and marketing strategies. Given {company}'s position "
            f"in the market, targeted research could uncover valuable growth opportunities."
        )
        
        # Simulate ~80 tokens
        return mock_block, 80
    
    def _generate_hook(
        self,
        lead: Dict[str, Any]
    ) -> Tuple[Optional[str], int]:
        """Generate mock hook sentence"""
        company = lead.get("company", "your company")
        
        mock_hook = f"I noticed {company} has been expanding into new markets recently."
        
        # Simulate ~30 tokens
        return mock_hook, 30
