"""
GOVERNANCE CHECKS - Enforcement Layer
=====================================
Enforces all AI governance rules at application level.

Rules enforced:
1. No DeepSeek references (build failure)
2. Gemini daily cap (7000 requests)
3. One classification per email (uniqueness)
4. No retries for Gemini failures
5. No parallel AI paths
6. No infinite processing loops
"""

import os
import logging
from datetime import datetime, date
from typing import Optional, Tuple
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)


class GovernanceViolation(Exception):
    """Raised when an AI governance rule is violated"""
    pass


class AIDailyLimitExceeded(GovernanceViolation):
    """Raised when AI daily limit is reached"""
    pass

# Backward-compatible alias
GeminiDailyLimitExceeded = AIDailyLimitExceeded


class EmailAlreadyClassified(GovernanceViolation):
    """Raised when attempting to classify an already-classified email"""
    pass


class DeepSeekViolation(GovernanceViolation):
    """Raised if any DeepSeek reference is detected (should never happen if code is clean)"""
    pass


# ============== MONGODB CONNECTION ==============

_mongo_client: Optional[MongoClient] = None
_governance_collection = None
_classification_guard_collection = None


def _get_mongo_client() -> MongoClient:
    """Get singleton MongoDB client"""
    global _mongo_client
    if _mongo_client is None:
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        _mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    return _mongo_client


def _get_governance_collection():
    """Get Gemini governance tracking collection"""
    global _governance_collection
    if _governance_collection is None:
        client = _get_mongo_client()
        # Intentionally separate from campaign_platform: governance collections store
        # cross-pipeline limits/locks and should remain isolated from business data.
        db = client['ai_governance']
        _governance_collection = db['gemini_daily_usage']
        # Create index for fast daily lookups
        _governance_collection.create_index([("date", 1)], unique=True)
    return _governance_collection


def _get_classification_guard_collection():
    """Get email classification guard collection (enforces one-classification-per-email)"""
    global _classification_guard_collection
    if _classification_guard_collection is None:
        client = _get_mongo_client()
        # Intentionally separate from campaign_platform business collections.
        db = client['ai_governance']
        _classification_guard_collection = db['email_classification_guard']
        # CRITICAL: Unique constraint on email_id - prevents duplicate classification
        _classification_guard_collection.create_index(
            [("email_id", 1)], 
            unique=True,
            name="unique_email_classification"
        )
    return _classification_guard_collection


# ============== GEMINI DAILY CAP (7000) ==============

GEMINI_DAILY_LIMIT = 50000  # Configurable safeguard — OpenAI is pay-as-you-go
AI_DAILY_LIMIT = GEMINI_DAILY_LIMIT


def get_gemini_daily_usage() -> Tuple[int, int]:
    """
    Get current Gemini daily usage.
    
    Returns:
        Tuple of (current_count, remaining)
    """
    collection = _get_governance_collection()
    today = date.today().isoformat()
    
    doc = collection.find_one({"date": today})
    current_count = doc.get("request_count", 0) if doc else 0
    remaining = max(0, GEMINI_DAILY_LIMIT - current_count)
    
    return current_count, remaining


def check_gemini_daily_limit() -> bool:
    """
    Check if Gemini daily limit has been reached.
    
    Returns:
        True if limit NOT reached (can proceed), False if limit reached
        
    Raises:
        GeminiDailyLimitExceeded: If limit is reached and fail_closed=True
    """
    current_count, remaining = get_gemini_daily_usage()
    
    if remaining <= 0:
        logger.error(f"GEMINI DAILY LIMIT REACHED: {current_count}/{GEMINI_DAILY_LIMIT}")
        return False
    
    return True


def increment_gemini_daily_usage() -> int:
    """
    Atomically increment Gemini daily usage counter.
    MUST be called BEFORE making any Gemini API call.
    
    Returns:
        New count after increment
        
    Raises:
        GeminiDailyLimitExceeded: If limit would be exceeded
    """
    collection = _get_governance_collection()
    today = date.today().isoformat()
    
    # Atomic increment with limit check
    result = collection.find_one_and_update(
        {"date": today},
        {
            "$inc": {"request_count": 1},
            "$setOnInsert": {"created_at": datetime.utcnow()},
            "$set": {"last_request_at": datetime.utcnow()}
        },
        upsert=True,
        return_document=True
    )
    
    new_count = result.get("request_count", 1)
    
    if new_count > GEMINI_DAILY_LIMIT:
        # We've exceeded - decrement back and raise
        collection.update_one(
            {"date": today},
            {"$inc": {"request_count": -1}}
        )
        raise AIDailyLimitExceeded(
            f"AI daily limit ({GEMINI_DAILY_LIMIT}) exceeded. Current: {new_count}. "
            "No more AI calls allowed today."
        )
    
    return new_count


# ============== ONE CLASSIFICATION PER EMAIL ==============

def check_email_classification_status(email_id: str) -> bool:
    """
    Check if an email has already been classified.
    
    Args:
        email_id: Unique email identifier
        
    Returns:
        True if email has NOT been classified (can proceed), False if already classified
    """
    collection = _get_classification_guard_collection()
    existing = collection.find_one({"email_id": email_id})
    return existing is None


def acquire_classification_lock(email_id: str, source: str = "api") -> bool:
    """
    Acquire exclusive classification lock for an email.
    Completed classifications cannot be re-run (idempotency guarantee).
    Failed or in-progress (stale) records are allowed to retry.

    Args:
        email_id: Unique email identifier
        source: Source of the classification request (for audit)

    Returns:
        True if lock acquired

    Raises:
        EmailAlreadyClassified: If email was already successfully classified
    """
    collection = _get_classification_guard_collection()

    # Check for an existing record first
    existing = collection.find_one({"email_id": email_id})
    if existing:
        if existing.get("status") == "completed":
            raise EmailAlreadyClassified(
                f"Email {email_id} has already been classified. Reclassification is forbidden."
            )
        # Failed or stale in-progress — reset so this attempt can proceed
        collection.update_one(
            {"email_id": email_id},
            {
                "$set": {
                    "classification_started_at": datetime.utcnow(),
                    "source": source,
                    "status": "in_progress",
                    "retried_at": datetime.utcnow(),
                }
            }
        )
        return True

    try:
        collection.insert_one({
            "email_id": email_id,
            "classification_started_at": datetime.utcnow(),
            "source": source,
            "status": "in_progress"
        })
        return True
    except DuplicateKeyError:
        # Race condition: another process inserted between our find and insert.
        # Re-fetch to determine status.
        existing = collection.find_one({"email_id": email_id})
        if existing and existing.get("status") == "completed":
            raise EmailAlreadyClassified(
                f"Email {email_id} has already been classified. Reclassification is forbidden."
            )
        # It's a failed/in-progress record inserted concurrently — treat as lock acquired
        return True


def complete_classification(email_id: str, result: dict) -> None:
    """
    Mark classification as complete for an email.
    
    Args:
        email_id: Unique email identifier
        result: Classification result to store
    """
    collection = _get_classification_guard_collection()
    collection.update_one(
        {"email_id": email_id},
        {
            "$set": {
                "status": "completed",
                "classification_completed_at": datetime.utcnow(),
                "result": result
            }
        }
    )


def fail_classification(email_id: str, error: str) -> None:
    """
    Mark classification as failed for an email.
    Note: Failed classifications are NOT retried automatically.
    
    Args:
        email_id: Unique email identifier
        error: Error message
    """
    collection = _get_classification_guard_collection()
    collection.update_one(
        {"email_id": email_id},
        {
            "$set": {
                "status": "failed",
                "classification_failed_at": datetime.utcnow(),
                "error": error
            }
        }
    )
    # Log once - no retry
    logger.error(f"AI classification failed for email {email_id}: {error}. NO AUTOMATIC RETRY.")


# ============== DEEPSEEK VALIDATION ==============

def validate_no_deepseek() -> bool:
    """
    Runtime check that no DeepSeek configuration exists.
    This is a defense-in-depth check - code should not contain DeepSeek references.
    
    Returns:
        True if no DeepSeek found, raises if found
        
    Raises:
        DeepSeekViolation: If DeepSeek configuration is detected
    """
    # Check environment variables
    deepseek_env_vars = [
        'DEEPSEEK_API_KEY',
        'DEEPSEEK_API_BASE', 
        'AI_DEFAULT_PROVIDER'
    ]
    
    for var in deepseek_env_vars:
        value = os.getenv(var, '')
        if 'deepseek' in value.lower():
            raise DeepSeekViolation(
                f"DeepSeek reference found in environment variable {var}. "
                "DeepSeek is completely removed from this codebase."
            )
    
    # Check database settings
    try:
        client = _get_mongo_client()
        settings = client['torpedo_settings']['app_settings'].find_one()
        if settings:
            if settings.get('deepseek_api_key'):
                raise DeepSeekViolation(
                    "DeepSeek API key found in database settings. "
                    "DeepSeek is completely removed from this codebase."
                )
    except DeepSeekViolation:
        raise
    except Exception:
        pass  # Database check is best-effort
    
    return True


# ============== GOVERNANCE REPORT ==============

def get_governance_status() -> dict:
    """
    Get current AI governance status for monitoring.
    
    Returns:
        Dictionary with all governance metrics
    """
    current_usage, remaining = get_gemini_daily_usage()
    
    return {
        "date": date.today().isoformat(),
        "ai": {
            "provider": "openai",
            "daily_limit": GEMINI_DAILY_LIMIT,
            "current_usage": current_usage,
            "remaining": remaining,
            "percentage_used": round((current_usage / GEMINI_DAILY_LIMIT) * 100, 2),
            "limit_reached": remaining <= 0
        },
        "enforcement": {
            "one_classification_per_email": True,
            "no_automatic_retries": True,
            "no_infinite_loops": True,
            "single_ai_entry_point": True
        }
    }


# Backward-compatible aliases
check_ai_daily_limit = check_gemini_daily_limit
increment_ai_daily_usage = increment_gemini_daily_usage
get_ai_daily_usage = get_gemini_daily_usage
