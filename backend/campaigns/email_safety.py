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
