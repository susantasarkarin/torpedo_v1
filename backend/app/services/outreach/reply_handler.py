"""
Reply Handler Service.

Classifies incoming email replies and generates appropriate responses.
"""

import json
import logging
from typing import Literal, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime

logger = logging.getLogger(__name__)


# =============================================================================
# Type Definitions
# =============================================================================

ReplyClassification = Literal[
    "Interested",
    "Meeting Request",
    "Pricing Inquiry",
    "Referral",
    "Objection",
    "Not Interested",
    "Out of Office",
    "Legal Warning",
    "Spam Complaint Risk",
    "Unclear"
]

Sentiment = Literal["positive", "neutral", "negative"]


# =============================================================================
# Data Models
# =============================================================================

class ClassifiedReply(BaseModel):
    """Result of reply classification."""
    classification: ReplyClassification
    confidence: float = Field(..., ge=0.0, le=1.0)
    sentiment: Sentiment
    key_phrases: list[str] = Field(default_factory=list)
    recommended_action: str
    classified_at: datetime = Field(default_factory=datetime.utcnow)
    
    @property
    def is_positive(self) -> bool:
        """Check if this is a positive response."""
        return self.classification in [
            "Interested",
            "Meeting Request",
            "Pricing Inquiry",
            "Referral"
        ]
    
    @property
    def is_negative(self) -> bool:
        """Check if this is a negative response."""
        return self.classification in [
            "Not Interested",
            "Legal Warning",
            "Spam Complaint Risk"
        ]
    
    @property
    def needs_human_review(self) -> bool:
        """Check if this needs human intervention."""
        return (
            self.classification in ["Legal Warning", "Spam Complaint Risk"] or
            self.confidence < 0.6 or
            self.classification == "Unclear"
        )


class AutoResponse(BaseModel):
    """Auto-generated response to a reply."""
    subject: str
    body: str
    tone_used: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ReplyContext(BaseModel):
    """Context for reply classification and response."""
    reply_text: str
    original_email_subject: str = ""
    original_email_body: str = ""
    thread_history: list[str] = Field(default_factory=list)
    contact_name: str = ""
    company_name: str = ""


# =============================================================================
# Service Implementation
# =============================================================================

class ReplyHandlerService:
    """
    Service for handling incoming email replies.
    
    This service:
    1. Classifies reply intent
    2. Determines next action
    3. Generates auto-responses when appropriate
    """
    
    # Classifications that should trigger auto-response
    AUTO_RESPOND_CLASSIFICATIONS = [
        "Interested",
        "Meeting Request",
        "Pricing Inquiry",
        "Objection"
    ]
    
    # Classifications that should halt all automation
    HALT_CLASSIFICATIONS = [
        "Legal Warning",
        "Spam Complaint Risk"
    ]
    
    # Classifications that should remove from sequence
    REMOVE_CLASSIFICATIONS = [
        "Not Interested",
        "Legal Warning",
        "Spam Complaint Risk"
    ]
    
    def __init__(self, ai_client: Any):
        """
        Initialize with an AI client.
        
        Args:
            ai_client: Client for AI API calls
        """
        self.ai_client = ai_client
    
    async def classify_reply(self, context: ReplyContext) -> ClassifiedReply:
        """
        Classify an incoming reply.
        
        Args:
            context: Reply context including original thread
            
        Returns:
            ClassifiedReply: Classification result
        """
        from .master_prompts import REPLY_CLASSIFIER_PROMPT
        
        prompt_context = self._build_classification_context(context)
        
        try:
            response = await self.ai_client.chat.completions.create(
                model="claude-opus-4-8",
                messages=[
                    {"role": "user", "content": f"{REPLY_CLASSIFIER_PROMPT}\n\n---\n\nREPLY TO CLASSIFY:\n{prompt_context}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,  # Low temperature for consistent classification
                max_tokens=400
            )
            
            result = json.loads(response.choices[0].message.content)
            return ClassifiedReply(**result)
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse classification response: {e}")
            # Return conservative default
            return ClassifiedReply(
                classification="Unclear",
                confidence=0.0,
                sentiment="neutral",
                key_phrases=[],
                recommended_action="Manual review required - classification failed"
            )
        except Exception as e:
            logger.error(f"Reply classification failed: {e}")
            raise
    
    async def generate_auto_response(
        self,
        classification: ClassifiedReply,
        context: ReplyContext
    ) -> Optional[AutoResponse]:
        """
        Generate an auto-response if appropriate.
        
        Args:
            classification: The classified reply
            context: Reply context
            
        Returns:
            AutoResponse if appropriate, None otherwise
        """
        from .master_prompts import AUTO_RESPONSE_PROMPT
        
        # Check if we should auto-respond
        if classification.classification not in self.AUTO_RESPOND_CLASSIFICATIONS:
            logger.info(
                f"Skipping auto-response for classification: {classification.classification}"
            )
            return None
        
        # Don't auto-respond if confidence is too low
        if classification.confidence < 0.7:
            logger.info(
                f"Skipping auto-response due to low confidence: {classification.confidence}"
            )
            return None
        
        prompt_context = f"""
CLASSIFICATION: {classification.classification}
CONFIDENCE: {classification.confidence}
SENTIMENT: {classification.sentiment}
RECOMMENDED ACTION: {classification.recommended_action}

THEIR REPLY:
{context.reply_text}

ORIGINAL EMAIL:
Subject: {context.original_email_subject}
Body: {context.original_email_body}

CONTACT: {context.contact_name} at {context.company_name}
"""
        
        try:
            response = await self.ai_client.chat.completions.create(
                model="claude-opus-4-8",
                messages=[
                    {"role": "user", "content": f"{AUTO_RESPONSE_PROMPT}\n\n---\n\n{prompt_context}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.5,
                max_tokens=400
            )
            
            result = json.loads(response.choices[0].message.content)
            return AutoResponse(**result)
            
        except Exception as e:
            logger.error(f"Auto-response generation failed: {e}")
            return None
    
    async def process_reply(
        self,
        context: ReplyContext
    ) -> dict:
        """
        Full reply processing pipeline.
        
        Args:
            context: Reply context
            
        Returns:
            Dict with classification, auto_response, and action recommendations
        """
        # Classify the reply
        classification = await self.classify_reply(context)
        
        result = {
            "classification": classification.model_dump(),
            "auto_response": None,
            "should_halt": classification.classification in self.HALT_CLASSIFICATIONS,
            "should_remove_from_sequence": classification.classification in self.REMOVE_CLASSIFICATIONS,
            "needs_human_review": classification.needs_human_review,
            "is_positive": classification.is_positive
        }
        
        # Generate auto-response if appropriate
        if not result["should_halt"] and not result["needs_human_review"]:
            auto_response = await self.generate_auto_response(classification, context)
            if auto_response:
                result["auto_response"] = auto_response.model_dump()
        
        return result
    
    def _build_classification_context(self, context: ReplyContext) -> str:
        """Build context string for classification."""
        thread = ""
        if context.thread_history:
            thread = "\n---\n".join(context.thread_history[-3:])  # Last 3 messages
        
        return f"""
REPLY TEXT:
{context.reply_text}

ORIGINAL EMAIL SUBJECT: {context.original_email_subject}

ORIGINAL EMAIL BODY:
{context.original_email_body}

{"THREAD HISTORY:" + chr(10) + thread if thread else ""}
"""
