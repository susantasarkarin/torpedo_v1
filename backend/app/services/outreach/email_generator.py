"""
Email Generator Service.

Generates personalized initial outreach emails and follow-ups
using AI and structured lead intelligence.
"""

import json
import logging
from typing import Literal, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime

from .lead_intelligence import LeadIntelligence

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================

class GeneratedEmail(BaseModel):
    """Generated email with subject and body."""
    subject: str = Field(..., min_length=1, max_length=100)
    body: str = Field(..., min_length=50, max_length=2000)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    word_count: Optional[int] = None
    strategy_used: Optional[str] = None
    
    def model_post_init(self, __context):
        """Calculate word count after initialization."""
        if self.word_count is None:
            self.word_count = len(self.body.split())


class EmailGenerationRequest(BaseModel):
    """Request parameters for email generation."""
    contact_name: str
    contact_role: str
    company_name: str
    intelligence: LeadIntelligence
    trigger_event: str = ""
    campaign_positioning: str = ""
    cta_style: Literal["soft", "direct", "binary"] = "soft"
    sender_name: str = ""
    sender_title: str = ""
    sender_company: str = ""


class FollowUpRequest(BaseModel):
    """Request parameters for follow-up generation."""
    original_email: GeneratedEmail
    days_since_sent: int
    open_count: int = 0
    click_count: int = 0
    intelligence_summary: str = ""
    followup_number: int = 1  # 1st, 2nd, 3rd follow-up
    contact_name: str = ""
    company_name: str = ""


class SpamCheckResult(BaseModel):
    """Result of spam check analysis."""
    spam_score: int = Field(..., ge=0, le=100)
    issues_found: list[dict] = Field(default_factory=list)
    is_safe_to_send: bool = True
    recommendations: list[str] = Field(default_factory=list)


# =============================================================================
# Service Implementation
# =============================================================================

class EmailGeneratorService:
    """
    Service for generating personalized outreach emails.
    
    This service:
    1. Generates initial cold outreach emails
    2. Creates intelligent follow-ups based on engagement
    3. Checks emails for spam triggers
    """
    
    def __init__(self, ai_client: Any):
        """
        Initialize with an AI client.
        
        Args:
            ai_client: Client for AI API calls
        """
        self.ai_client = ai_client
    
    async def generate_initial_email(
        self,
        request: EmailGenerationRequest
    ) -> GeneratedEmail:
        """
        Generate a personalized initial outreach email.
        
        Args:
            request: Email generation parameters
            
        Returns:
            GeneratedEmail: Generated email with subject and body
        """
        from .master_prompts import MASTER_SYSTEM_PROMPT, EMAIL_GENERATION_PROMPT
        
        context = self._build_email_context(request)
        
        try:
            response = await self.ai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": MASTER_SYSTEM_PROMPT},
                    {"role": "user", "content": f"{EMAIL_GENERATION_PROMPT}\n\n---\n\nCONTEXT:\n{context}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.7,  # Slightly higher for creativity
                max_tokens=800
            )
            
            result = json.loads(response.choices[0].message.content)
            return GeneratedEmail(**result)
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse email generation response: {e}")
            raise ValueError("AI returned invalid JSON for email generation")
        except Exception as e:
            logger.error(f"Email generation failed: {e}")
            raise
    
    async def generate_followup(self, request: FollowUpRequest) -> GeneratedEmail:
        """
        Generate a follow-up email based on engagement signals.
        
        Args:
            request: Follow-up generation parameters
            
        Returns:
            GeneratedEmail: Generated follow-up email
        """
        from .master_prompts import MASTER_SYSTEM_PROMPT, FOLLOWUP_GENERATION_PROMPT
        
        context = self._build_followup_context(request)
        
        try:
            response = await self.ai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": MASTER_SYSTEM_PROMPT},
                    {"role": "user", "content": f"{FOLLOWUP_GENERATION_PROMPT}\n\n---\n\nCONTEXT:\n{context}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=600
            )
            
            result = json.loads(response.choices[0].message.content)
            return GeneratedEmail(**result)
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse follow-up response: {e}")
            raise ValueError("AI returned invalid JSON for follow-up generation")
        except Exception as e:
            logger.error(f"Follow-up generation failed: {e}")
            raise
    
    async def check_spam(self, email: GeneratedEmail) -> SpamCheckResult:
        """
        Check email content for potential spam triggers.
        
        Args:
            email: Email to check
            
        Returns:
            SpamCheckResult: Spam analysis results
        """
        from .master_prompts import SPAM_CHECK_PROMPT
        
        context = f"""
SUBJECT: {email.subject}

BODY:
{email.body}
"""
        
        try:
            response = await self.ai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "user", "content": f"{SPAM_CHECK_PROMPT}\n\n---\n\nEMAIL TO CHECK:\n{context}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,  # Low temperature for consistency
                max_tokens=500
            )
            
            result = json.loads(response.choices[0].message.content)
            return SpamCheckResult(**result)
            
        except Exception as e:
            logger.error(f"Spam check failed: {e}")
            # Return safe default on error
            return SpamCheckResult(
                spam_score=50,
                is_safe_to_send=True,
                recommendations=["Manual review recommended due to check failure"]
            )
    
    async def generate_and_validate(
        self,
        request: EmailGenerationRequest,
        spam_threshold: int = 30
    ) -> tuple[GeneratedEmail, SpamCheckResult]:
        """
        Generate email and validate it's not spammy.
        
        Args:
            request: Email generation parameters
            spam_threshold: Maximum acceptable spam score
            
        Returns:
            Tuple of (GeneratedEmail, SpamCheckResult)
            
        Raises:
            ValueError: If generated email exceeds spam threshold
        """
        email = await self.generate_initial_email(request)
        spam_result = await self.check_spam(email)
        
        if spam_result.spam_score > spam_threshold:
            logger.warning(
                f"Generated email exceeded spam threshold: {spam_result.spam_score}"
            )
            # Regenerate with stricter guidance
            email = await self._regenerate_safer(request, spam_result)
            spam_result = await self.check_spam(email)
        
        return email, spam_result
    
    async def _regenerate_safer(
        self,
        request: EmailGenerationRequest,
        spam_result: SpamCheckResult
    ) -> GeneratedEmail:
        """Regenerate email avoiding previous spam triggers."""
        from .master_prompts import MASTER_SYSTEM_PROMPT, EMAIL_GENERATION_PROMPT
        
        issues_text = "\n".join([
            f"- {issue['type']}: {issue.get('problematic_text', 'N/A')}"
            for issue in spam_result.issues_found
        ])
        
        context = self._build_email_context(request)
        context += f"""

IMPORTANT: Previous generation had spam issues. Avoid these:
{issues_text}

Be more conservative and professional. Avoid any promotional language.
"""
        
        response = await self.ai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": MASTER_SYSTEM_PROMPT},
                {"role": "user", "content": f"{EMAIL_GENERATION_PROMPT}\n\n---\n\nCONTEXT:\n{context}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.5,  # Lower temperature for safer output
            max_tokens=800
        )
        
        result = json.loads(response.choices[0].message.content)
        return GeneratedEmail(**result)
    
    def _build_email_context(self, request: EmailGenerationRequest) -> str:
        """Build context string for email generation."""
        return f"""
CONTACT INFORMATION:
- Name: {request.contact_name}
- Role: {request.contact_role}
- Company: {request.company_name}

INTELLIGENCE:
{request.intelligence.model_dump_json(indent=2)}

TRIGGER EVENT:
{request.trigger_event or "None specified"}

CAMPAIGN POSITIONING:
{request.campaign_positioning or "General outreach"}

CTA STYLE: {request.cta_style}

SENDER:
- Name: {request.sender_name or "[Your Name]"}
- Title: {request.sender_title or ""}
- Company: {request.sender_company or ""}
"""
    
    def _build_followup_context(self, request: FollowUpRequest) -> str:
        """Build context string for follow-up generation."""
        # Determine engagement level
        if request.open_count >= 3:
            engagement = "HIGH (opened 3+ times - they're interested but hesitant)"
        elif request.open_count == 0:
            engagement = "NONE (never opened - hook didn't work)"
        else:
            engagement = "LOW (opened once - mild interest)"
        
        return f"""
ORIGINAL EMAIL:
Subject: {request.original_email.subject}
Body: {request.original_email.body}

ENGAGEMENT METRICS:
- Days since sent: {request.days_since_sent}
- Open count: {request.open_count}
- Click count: {request.click_count}
- Engagement level: {engagement}

FOLLOW-UP NUMBER: {request.followup_number}

CONTACT: {request.contact_name} at {request.company_name}

INTELLIGENCE SUMMARY:
{request.intelligence_summary or "No additional intelligence available"}
"""
