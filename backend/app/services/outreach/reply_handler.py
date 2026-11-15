"""
Reply Handler Service.

Classifies incoming email replies and generates appropriate responses.
"""

import asyncio
import json
import logging
from typing import Literal, Optional, Any, get_args
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


# JSON shapes for the ladder (escalate_json). The check reuses the pydantic
# models so a malformed answer climbs to the next tier instead of being used.
_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {"type": "string", "enum": list(get_args(ReplyClassification))},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "sentiment": {"type": "string", "enum": list(get_args(Sentiment))},
        "key_phrases": {"type": "array", "items": {"type": "string"}},
        "recommended_action": {"type": "string"},
    },
    "required": ["classification", "confidence", "sentiment", "recommended_action"],
}

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "tone_used": {"type": "string"},
    },
    "required": ["subject", "body", "tone_used"],
}


def _check_classified(data: Any) -> list[str]:
    try:
        ClassifiedReply(**data)
        return []
    except Exception as e:
        return [str(e).splitlines()[0][:200]]


def _check_response(data: Any) -> list[str]:
    try:
        AutoResponse(**data)
        return []
    except Exception as e:
        return [str(e).splitlines()[0][:200]]


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
            from platform_core import ladder

            # The ladder blocks on network I/O; run it on a thread so the event loop stays free.
            data, _tier, _attempts = await asyncio.to_thread(
                ladder.escalate_json,
                task="reply_classification",
                system=REPLY_CLASSIFIER_PROMPT,
                user=f"REPLY TO CLASSIFY:\n{prompt_context}",
                schema=_CLASSIFY_SCHEMA,
                check=_check_classified,
                max_tokens=400,
            )
            if not data:
                raise ValueError("no cloud tier answered the reply classification")
            return ClassifiedReply(**data)

        except Exception as e:
            logger.error(f"Reply classification failed: {e}")
            return ClassifiedReply(
                classification="Unclear",
                confidence=0.0,
                sentiment="neutral",
                key_phrases=[],
                recommended_action="Manual review required - classification failed"
            )
    
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
            from platform_core import ladder

            data, _tier, _attempts = await asyncio.to_thread(
                ladder.escalate_json,
                task="reply_draft",
                system=AUTO_RESPONSE_PROMPT,
                user=prompt_context,
                schema=_RESPONSE_SCHEMA,
                check=_check_response,
                max_tokens=400,
            )
            if not data:
                return None
            return AutoResponse(**data)

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
