"""
REPLY ENGINE
============

Enterprise Reply Intelligence Layer for email classification.

Modules:
- models: Data structures (ReplyIntent, ReplyLog, ClassificationResult)
- matcher: Multi-layer thread matching (4 fallback levels)
- cleaner: Text extraction (quote/signature stripping)
- classifier: Hybrid classification (rules + AI)

Phase 1: Core Classification (this release)
- Match replies to outbound sends
- Clean text for classification
- Classify intent with confidence
- Log all results

Phase 2: Action Routing (future)
- Trigger workflow actions
- Create sales tasks
- Handle DNC flags
- Process referrals

Usage:
    from outreach_engine.reply_engine import (
        ReplyMatcher,
        TextCleaner,
        HybridClassifier,
        ReplyIntent,
        ReplyLog
    )
    
    # Match reply to outbound
    matcher = ReplyMatcher(db)
    match_result = matcher.match_reply(
        in_reply_to=headers.get("In-Reply-To"),
        references=headers.get("References", []),
        thread_id=gmail_thread_id,
        subject=subject,
        from_email=sender,
        mailbox_id=mailbox_id
    )
    
    # Clean reply text
    cleaner = TextCleaner()
    cleaned_text, _ = cleaner.clean(raw_body, is_html=True)
    
    # Classify intent
    classifier = HybridClassifier()
    result = classifier.classify(cleaned_text)
    
    # Log result
    reply_log = ReplyLog(
        reply_id=gmail_message_id,
        mailbox_id=mailbox_id,
        from_email=sender,
        received_at=received_at,
        raw_text=raw_body,
        cleaned_text=cleaned_text,
        classification=result.intent.value,
        confidence=result.confidence,
        ...
    )
"""

# Models
from .models import (
    # Enums
    ProcessingStatus,
    ReplyIntent,
    MatchMethod,
    ClassificationMethod,
    
    # Result models
    ExtractedData,
    ClassificationResult,
    MatchResult,
    
    # Main document
    ReplyLog,
    
    # Constants
    CONFIDENCE_THRESHOLD,
    MAX_AI_TEXT_LENGTH,
    MAX_RETRY_COUNT,
    
    # Index setup
    REPLY_LOG_INDEXES,
    setup_reply_log_indexes,
)

# Matcher
from .matcher import (
    ReplyMatcher,
    MATCH_CONFIDENCE,
    MIN_MATCH_CONFIDENCE,
)

# Cleaner
from .cleaner import (
    TextCleaner,
    clean_reply_text,
    MAX_CLEANED_LENGTH,
    MIN_REPLY_LENGTH,
)

# Classifier
from .classifier import (
    RuleClassifier,
    AIClassifier,
    HybridClassifier,
    RulePatterns,
    classify_reply,
    get_classification_stats,
)

__all__ = [
    # Enums
    "ProcessingStatus",
    "ReplyIntent",
    "MatchMethod",
    "ClassificationMethod",
    
    # Models
    "ExtractedData",
    "ClassificationResult",
    "MatchResult",
    "ReplyLog",
    
    # Constants
    "CONFIDENCE_THRESHOLD",
    "MAX_AI_TEXT_LENGTH",
    "MAX_RETRY_COUNT",
    "MATCH_CONFIDENCE",
    "MIN_MATCH_CONFIDENCE",
    "MAX_CLEANED_LENGTH",
    "MIN_REPLY_LENGTH",
    
    # Classes
    "ReplyMatcher",
    "TextCleaner",
    "RuleClassifier",
    "AIClassifier",
    "HybridClassifier",
    "RulePatterns",
    
    # Functions
    "setup_reply_log_indexes",
    "clean_reply_text",
    "classify_reply",
    "get_classification_stats",
]
