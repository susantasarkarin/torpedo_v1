"""
Email safety guards - kill switch, validation, and pre-send checks.
"""
import os
import logging
from typing import Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# Environment variable controls
DISABLE_EMAIL_SENDING = os.getenv("DISABLE_EMAIL_SENDING", "true").lower() in ("true", "1", "yes")
DRY_RUN_MODE = os.getenv("DRY_RUN_MODE", "true").lower() in ("true", "1", "yes")


class EmailKillSwitchActiveError(Exception):
    """Raised when email sending is disabled via kill switch."""
    pass


class EmailSuppressedError(Exception):
    """Raised when recipient is on suppression list."""
    def __init__(self, email: str, reason: str):
        self.email = email
        self.reason = reason
        super().__init__(f"Email suppressed: {email} (reason: {reason})")


class EmailRateLimitError(Exception):
    """Raised when rate limit is exceeded."""
    pass


def is_email_sending_enabled() -> bool:
    """Check if email sending is enabled (kill switch off)."""
    return not DISABLE_EMAIL_SENDING


def is_dry_run_mode() -> bool:
    """Check if dry-run mode is active."""
    return DRY_RUN_MODE


def can_send_real_emails() -> Tuple[bool, Optional[str]]:
    """
    Check if real emails can be sent.
    Returns (can_send, reason_if_blocked)
    """
    if DISABLE_EMAIL_SENDING:
        return False, "kill_switch_active"
    if DRY_RUN_MODE:
        return False, "dry_run_mode"
    return True, None


def get_email_status() -> dict:
    """Get current email sending status for API response."""
    can_send, reason = can_send_real_emails()
    return {
        "email_sending_enabled": not DISABLE_EMAIL_SENDING,
        "dry_run_mode": DRY_RUN_MODE,
        "can_send_real_emails": can_send,
        "blocked_reason": reason,
        "environment": {
            "DISABLE_EMAIL_SENDING": os.getenv("DISABLE_EMAIL_SENDING", "true"),
            "DRY_RUN_MODE": os.getenv("DRY_RUN_MODE", "true")
        }
    }


def check_kill_switch():
    """
    Guard function to check kill switch before sending.
    Raises EmailKillSwitchActiveError if sending is disabled.
    """
    if DISABLE_EMAIL_SENDING:
        logger.warning("[KILL SWITCH] Email sending blocked by DISABLE_EMAIL_SENDING")
        raise EmailKillSwitchActiveError("Email sending is disabled via kill switch")


async def pre_send_checks(
    recipient_email: str,
    suppression_manager,
    rate_limiter=None,
    account_id: str = None
) -> Tuple[bool, Optional[str]]:
    """
    Run all pre-send safety checks.
    Returns (can_proceed, error_message)
    """
    # 1. Kill switch check
    if DISABLE_EMAIL_SENDING:
        return False, "kill_switch_active"
    
    # 2. Dry-run mode check
    if DRY_RUN_MODE:
        logger.info(f"[DRY RUN] Would send to {recipient_email}")
        return False, "dry_run_mode"
    
    # 3. Suppression check
    if suppression_manager:
        if await suppression_manager.is_suppressed(recipient_email):
            reason = await suppression_manager.get_reason(recipient_email)
            logger.info(f"[SUPPRESSED] {recipient_email} - {reason}")
            return False, f"suppressed:{reason}"
    
    # 4. Rate limit check
    if rate_limiter and account_id:
        can_send = await rate_limiter.check_can_send(account_id)
        if not can_send.get("allowed", False):
            logger.warning(f"[RATE LIMITED] Account {account_id}")
            return False, "rate_limited"
    
    return True, None


# ============== KEYWORD-BASED SPAM CHECK (No AI) ==============

# Spam trigger words/phrases that commonly cause deliverability issues
SPAM_TRIGGER_WORDS = {
    "high": [
        "act now", "buy now", "click here", "free money", "no obligation",
        "limited time offer", "congratulations", "you have been selected",
        "100% free", "risk free", "no cost", "winner", "cash bonus",
        "double your", "earn extra cash", "fast cash", "free access",
        "free gift", "free trial", "great offer", "guarantee",
        "incredible deal", "order now", "special promotion", "urgent",
        "while supplies last", "you're a winner", "apply now",
        "be your own boss", "billion dollars", "cash prize",
    ],
    "medium": [
        "as seen on", "call now", "dear friend", "don't delete",
        "don't hesitate", "exclusive deal", "for free", "get it now",
        "information you requested", "instant", "new customers only",
        "once in a lifetime", "please read", "satisfied customers",
        "this isn't spam", "unsubscribe", "what are you waiting for",
        "will not believe", "amazing", "lowest price",
    ],
    "low": [
        "click below", "discount", "increase", "no strings attached",
        "offer", "opt in", "opt-in", "remove", "success",
        "traffic", "unsolicited", "visit our website",
    ]
}

# Patterns that are red flags
SPAM_PATTERNS = [
    r'\$\d{3,}',              # Dollar amounts ($100+)
    r'\d+%\s*off',            # Percentage discounts
    r'!!!+',                  # Multiple exclamation marks
    r'\?\?\?+',               # Multiple question marks
    r'[A-Z\s]{20,}',          # ALL CAPS blocks (20+ chars)
    r'https?://\S+',         # URLs in body
    r'<a\s+href',            # HTML links
]


def check_spam_keywords(subject: str, body_plain: str) -> dict:
    """
    Rule-based spam check using keyword matching and pattern detection.
    No AI/LLM calls — runs in <1ms.
    
    Args:
        subject: Email subject line
        body_plain: Plain text email body (strip HTML first)
    
    Returns:
        {
            "spam_score": int (0-100),
            "is_safe_to_send": bool,
            "issues_found": list of str,
            "method": "keyword_blacklist"
        }
    """
    import re
    
    content = f"{subject} {body_plain}".lower()
    issues = []
    score = 0
    
    # Check trigger words
    for word in SPAM_TRIGGER_WORDS["high"]:
        if word in content:
            score += 8
            issues.append(f"High-risk phrase: '{word}'")
    
    for word in SPAM_TRIGGER_WORDS["medium"]:
        if word in content:
            score += 4
            issues.append(f"Medium-risk phrase: '{word}'")
    
    for word in SPAM_TRIGGER_WORDS["low"]:
        if word in content:
            score += 2
            issues.append(f"Low-risk phrase: '{word}'")
    
    # Check patterns
    for pattern in SPAM_PATTERNS:
        matches = re.findall(pattern, f"{subject} {body_plain}")
        if matches:
            score += 5 * len(matches)
            issues.append(f"Pattern match: {pattern} ({len(matches)}x)")
    
    # Subject-specific checks
    subject_lower = subject.lower()
    if subject_lower == subject_lower.upper() and len(subject) > 10:
        score += 10
        issues.append("Subject is ALL CAPS")
    
    if subject.count("!") > 1:
        score += 5
        issues.append("Multiple exclamation marks in subject")
    
    if subject.startswith("Re:") or subject.startswith("Fwd:"):
        score += 3
        issues.append("Fake Re:/Fwd: in subject")
    
    # Cap at 100
    score = min(score, 100)
    
    return {
        "spam_score": score,
        "is_safe_to_send": score <= 30,
        "issues_found": issues[:10],  # Limit to top 10 issues
        "method": "keyword_blacklist"
    }
