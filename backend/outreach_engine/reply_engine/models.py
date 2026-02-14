"""
REPLY ENGINE MODELS
===================

Data structures for the Reply Intelligence Layer.

Enums:
- ProcessingStatus: Queue state tracking
- ReplyIntent: Classification categories
- MatchMethod: How reply was matched to outbound

Models:
- ClassificationResult: AI/rule output with confidence
- MatchResult: Thread matching result
- ReplyLog: Full audit trail document

Enterprise Features:
- Confidence threshold (0.65 floor)
- Extracted data for OOO/referral
- Processing status for debugging
- Idempotency via unique reply_id
"""

from enum import Enum
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from bson import ObjectId


# ============== ENUMS ==============

class ProcessingStatus(str, Enum):
    """Reply processing state machine."""
    QUEUED = "queued"           # Fetched from Gmail, awaiting processing
    PROCESSING = "processing"   # Currently being classified
    CLASSIFIED = "classified"   # Classification complete, awaiting action
    ACTIONED = "actioned"       # Action taken (Phase 2)
    FAILED = "failed"           # Processing error


class ReplyIntent(str, Enum):
    """Classification categories for reply intent."""
    INTERESTED = "interested"           # Wants to learn more, schedule meeting
    SOFT_INTEREST = "soft_interest"     # Open but not urgent
    NOT_NOW = "not_now"                 # Bad timing, try later
    NOT_INTERESTED = "not_interested"   # Clear rejection
    REFERRAL = "referral"               # Suggests contacting someone else
    OOO = "ooo"                         # Out of office
    SPAM_COMPLAINT = "spam_complaint"   # Angry, threatens to report
    BOUNCE = "bounce"                   # Delivery failure
    UNKNOWN = "unknown"                 # Low confidence, needs review


class MatchMethod(str, Enum):
    """How the reply was matched to an outbound email."""
    IN_REPLY_TO = "in_reply_to"         # Exact In-Reply-To header match
    REFERENCES = "references"            # Match via References array
    THREAD_ID = "thread_id"             # Gmail thread_id match
    SUBJECT_SENDER = "subject_sender"   # Fallback: subject + sender
    UNMATCHED = "unmatched"             # Could not match to any outbound


class ClassificationMethod(str, Enum):
    """How the classification was determined."""
    RULE = "rule"       # Deterministic rule match
    AI = "ai"           # AI classification
    MANUAL = "manual"   # Human override


# ============== RESULT MODELS ==============

class ExtractedData(BaseModel):
    """
    Structured data extracted from reply.
    
    Used for:
    - OOO: return date
    - Referral: contact info
    """
    # OOO extraction
    return_date: Optional[str] = None  # ISO format YYYY-MM-DD
    
    # Referral extraction
    referral_name: Optional[str] = None
    referral_email: Optional[str] = None
    referral_title: Optional[str] = None
    referral_company: Optional[str] = None
    
    # General
    mentioned_timeframe: Optional[str] = None  # "next quarter", "after holidays"
    

class ClassificationResult(BaseModel):
    """
    Result from hybrid classifier.
    
    Contains intent + confidence + extracted data.
    """
    intent: ReplyIntent
    confidence: float = Field(ge=0.0, le=1.0)
    method: ClassificationMethod
    
    # Rule that matched (if method=rule)
    matched_rule: Optional[str] = None
    matched_pattern: Optional[str] = None
    
    # Extracted data (for OOO, referral)
    extracted_data: Optional[ExtractedData] = None
    
    # AI metadata
    ai_model: Optional[str] = None
    ai_tokens_used: Optional[int] = None
    ai_raw_response: Optional[str] = None
    
    # Validation
    below_confidence_threshold: bool = False
    
    class Config:
        use_enum_values = True


class MatchResult(BaseModel):
    """
    Result from reply-to-outbound matching.
    
    Links incoming reply to the original campaign/lead.
    """
    matched: bool
    method: MatchMethod
    confidence: float = Field(ge=0.0, le=1.0)
    
    # Matched entities
    lead_id: Optional[str] = None
    campaign_id: Optional[str] = None
    mailbox_id: Optional[str] = None
    original_send_id: Optional[str] = None
    workflow_step: Optional[int] = None
    
    # Match details
    matched_message_id: Optional[str] = None
    matched_thread_id: Optional[str] = None
    
    # For subject_sender fallback
    matched_subject: Optional[str] = None
    matched_sender: Optional[str] = None
    
    # CANDIDATE tracking for low-confidence matches
    # Store potential match even if below threshold for manual review
    lead_id_candidate: Optional[str] = None
    campaign_id_candidate: Optional[str] = None
    flag_for_manual_review: bool = False
    
    class Config:
        use_enum_values = True


# ============== MAIN DOCUMENT MODEL ==============

class ReplyLog(BaseModel):
    """
    Full audit trail for a processed reply.
    
    This is the main document stored in outreach_reply_logs.
    
    Idempotency:
    - reply_id is unique (Gmail message ID)
    - Duplicate processing prevented at DB level
    """
    # Identity (unique)
    reply_id: str  # Gmail message ID - UNIQUE INDEX
    
    # Gmail metadata
    gmail_thread_id: Optional[str] = None
    gmail_history_id: Optional[str] = None
    mailbox_id: str
    from_email: str
    from_name: Optional[str] = None
    subject: Optional[str] = None
    received_at: datetime
    
    # Headers for matching
    in_reply_to: Optional[str] = None
    references: List[str] = Field(default_factory=list)
    
    # Match result
    match_method: str = MatchMethod.UNMATCHED.value
    match_confidence: float = 0.0
    lead_id: Optional[str] = None
    campaign_id: Optional[str] = None
    original_send_id: Optional[str] = None
    workflow_step: Optional[int] = None
    
    # Content
    raw_text: str
    cleaned_text: Optional[str] = None
    text_length: int = 0
    
    # Classification
    classification: str = ReplyIntent.UNKNOWN.value
    classification_method: str = ClassificationMethod.AI.value
    confidence: float = 0.0
    below_threshold: bool = False
    matched_rule: Optional[str] = None
    
    # Extracted data (JSON)
    extracted_data: Optional[Dict[str, Any]] = None
    
    # AI usage
    ai_model: Optional[str] = None
    ai_tokens_used: int = 0
    
    # Processing state
    processing_status: str = ProcessingStatus.QUEUED.value
    error_message: Optional[str] = None
    retry_count: int = 0
    
    # Actions (Phase 2)
    action_taken: Optional[str] = None
    actioned_at: Optional[datetime] = None
    
    # Timestamps
    queued_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True
    
    def to_mongo_dict(self) -> Dict[str, Any]:
        """Convert to MongoDB document."""
        data = self.model_dump()
        data["updated_at"] = datetime.utcnow()
        return data


# ============== CONSTANTS ==============

import os

# Confidence threshold - below this = unknown + manual review
# CONFIGURABLE via environment variable for tuning
CONFIDENCE_THRESHOLD = float(os.getenv("REPLY_CONFIDENCE_THRESHOLD", "0.65"))

# Max text length sent to AI
MAX_AI_TEXT_LENGTH = 2000

# Processing retry limit
MAX_RETRY_COUNT = 3

# Minimum match confidence to accept (subject/sender falls below)
MIN_MATCH_CONFIDENCE = float(os.getenv("REPLY_MATCH_CONFIDENCE", "0.65"))


# ============== INDEX DEFINITIONS ==============

REPLY_LOG_INDEXES = [
    # UNIQUE - idempotency guarantee
    {
        "keys": [("reply_id", 1)],
        "unique": True,
        "name": "reply_id_unique"
    },
    # Query by lead
    {
        "keys": [("lead_id", 1), ("received_at", -1)],
        "name": "lead_id_received"
    },
    # Campaign analytics
    {
        "keys": [("campaign_id", 1), ("classification", 1)],
        "name": "campaign_classification"
    },
    # Mailbox risk monitoring
    {
        "keys": [("mailbox_id", 1), ("classification", 1)],
        "name": "mailbox_classification"
    },
    # Queue processing
    {
        "keys": [("processing_status", 1), ("queued_at", 1)],
        "name": "processing_queue"
    },
    # Manual review queue
    {
        "keys": [("below_threshold", 1), ("processing_status", 1)],
        "name": "manual_review_queue"
    },
]


def setup_reply_log_indexes(db):
    """
    Create indexes for outreach_reply_logs collection.
    
    Args:
        db: MongoDB database instance
    """
    collection = db["outreach_reply_logs"]
    
    for index_def in REPLY_LOG_INDEXES:
        try:
            collection.create_index(
                index_def["keys"],
                unique=index_def.get("unique", False),
                name=index_def["name"]
            )
        except Exception as e:
            # Index may already exist
            pass
