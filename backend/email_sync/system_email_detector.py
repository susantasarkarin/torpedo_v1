"""
SYSTEM EMAIL DETECTOR
=====================

Rule-based detection of system emails (bounce, OOO, auto-reply).

CRITICAL: System emails MUST be detected BEFORE any LLM call.
This module provides the hard short-circuit guarantee for cost control.

Design Principles:
1. Zero false negatives for bounce detection (never miss a bounce)
2. Low false positives (prefer to let ambiguous emails through to LLM)
3. Deterministic, testable rules (no ML/AI in this module)
4. Global deduplication via content-based hashing

Usage:
    from email_sync.system_email_detector import (
        detect_system_email,
        compute_dedupe_hash,
        is_system_email
    )
    
    # Before LLM call:
    detection = detect_system_email(email_doc)
    if detection.is_system:
        # Skip LLM, use detection.email_type and detection.system_subtype
        pass
"""

import re
import hashlib
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple

from .models import EmailType, SystemSubtype

logger = logging.getLogger(__name__)


# ============== DETECTION PATTERNS ==============

# Bounce sender patterns (case-insensitive)
BOUNCE_SENDER_PATTERNS = [
    r"mailer-daemon@",
    r"postmaster@",
    r"mail-delivery-subsystem@",
    r"noreply.*bounce",
    r"bounce.*@",
    r"returned-mail@",
    r"auto-notify@",
]

# Bounce subject patterns (case-insensitive)
BOUNCE_SUBJECT_PATTERNS = [
    r"delivery\s+(status\s+)?notification",
    r"undeliverable",
    r"undelivered\s+mail",
    r"delivery\s+fail(ed|ure)?",
    r"mail\s+delivery\s+fail(ed|ure)?",
    r"returned\s+(mail|message)",
    r"recipient\s+rejected",
    r"mailbox\s+(unavailable|not\s+found|full)",
    r"user\s+unknown",
    r"address\s+rejected",
    r"could\s+not\s+be\s+delivered",
    r"permanent\s+(failure|error)",
    r"550\s+",  # SMTP error code
    r"554\s+",  # SMTP error code
]

# Bounce body patterns (case-insensitive, first 1000 chars)
BOUNCE_BODY_PATTERNS = [
    r"delivery\s+to\s+the\s+following\s+recipient\s+failed",
    r"this\s+is\s+an\s+automatically\s+generated\s+delivery\s+status\s+notification",
    r"message\s+was\s+undeliverable",
    r"could\s+not\s+be\s+delivered\s+to",
    r"recipient\s+address\s+rejected",
    r"mailbox\s+unavailable",
    r"user\s+unknown",
    r"no\s+such\s+user",
    r"account\s+disabled",
    r"over\s+quota",
    r"smtp\s+error",
    r"550\s+5\.\d+\.\d+",  # Extended SMTP codes
    r"554\s+5\.\d+\.\d+",
]

# Out of Office patterns (case-insensitive)
OOO_SUBJECT_PATTERNS = [
    r"out\s+of\s+(the\s+)?office",
    r"automatic\s+reply",
    r"auto[\s-]?reply",
    r"away\s+from\s+(the\s+)?office",
    r"on\s+vacation",
    r"currently\s+unavailable",
    r"will\s+be\s+(out|away|back)",
    r"autoresponder",
    r"absence\s+notification",
    r"i('m|\s+am)\s+out\s+of",
]

OOO_BODY_PATTERNS = [
    r"i('m|\s+am)\s+(currently\s+)?(out\s+of\s+(the\s+)?office|away|on\s+vacation)",
    r"will\s+be\s+(out\s+of\s+office|away|back\s+on)",
    r"have\s+limited\s+access\s+to\s+email",
    r"this\s+is\s+an?\s+auto(matic|mated)?\s+(reply|response)",
    r"thank\s+you\s+for\s+your\s+(email|message).*will\s+(respond|reply|get\s+back)",
]

# Auto-reply patterns (generic automated responses, not OOO)
AUTO_REPLY_SENDER_PATTERNS = [
    r"noreply@",
    r"no-reply@",
    r"donotreply@",
    r"do-not-reply@",
    r"automated@",
    r"notification@",
]

AUTO_REPLY_SUBJECT_PATTERNS = [
    r"^re:\s*\[?auto(matic)?\s*(reply|response)\]?",
    r"auto[\s-]?generated",
    r"automated\s+(message|response|notification)",
    r"this\s+is\s+an?\s+automated",
    r"acknowledgement",
    r"confirmation\s+of\s+receipt",
]

# Unsubscribe patterns
UNSUBSCRIBE_SUBJECT_PATTERNS = [
    r"^unsubscribe",
    r"unsubscribe\s+(request|confirmed?|successful)",
    r"you('ve|\s+have)\s+been\s+unsubscribed",
    r"subscription\s+(removed|cancelled|canceled)",
]


# ============== DATA STRUCTURES ==============

@dataclass
class SystemEmailDetection:
    """Result of system email detection"""
    is_system: bool
    email_type: EmailType
    system_subtype: Optional[SystemSubtype]
    confidence: float  # 0.0-1.0, for audit/debugging only
    detection_reason: str  # Human-readable explanation


# ============== CORE DETECTION FUNCTIONS ==============

def detect_system_email(
    email: Dict[str, Any],
    strict_mode: bool = True
) -> SystemEmailDetection:
    """
    Detect if email is a system email (bounce, OOO, auto-reply).
    
    MUST be called BEFORE any LLM classification to guarantee
    zero wasted LLM calls on system emails.
    
    Args:
        email: Email document with from_address, subject, body_plain
        strict_mode: If True, require higher confidence for detection
        
    Returns:
        SystemEmailDetection with is_system flag and subtype
    """
    # Extract fields safely
    from_email = _extract_email_address(email.get("from_address", {}))
    subject = (email.get("subject") or "").strip()
    body = (email.get("body_plain") or email.get("snippet") or "")[:1500]
    
    # Normalize for matching
    from_email_lower = from_email.lower()
    subject_lower = subject.lower()
    body_lower = body.lower()
    
    # Priority 1: Bounce detection (highest priority)
    bounce_result = _detect_bounce(from_email_lower, subject_lower, body_lower)
    if bounce_result[0]:
        return SystemEmailDetection(
            is_system=True,
            email_type=EmailType.SYSTEM,
            system_subtype=SystemSubtype.BOUNCE,
            confidence=bounce_result[1],
            detection_reason=bounce_result[2]
        )
    
    # Priority 2: Out of Office detection
    ooo_result = _detect_out_of_office(from_email_lower, subject_lower, body_lower)
    if ooo_result[0]:
        return SystemEmailDetection(
            is_system=True,
            email_type=EmailType.SYSTEM,
            system_subtype=SystemSubtype.OUT_OF_OFFICE,
            confidence=ooo_result[1],
            detection_reason=ooo_result[2]
        )
    
    # Priority 3: Unsubscribe confirmation
    unsub_result = _detect_unsubscribe(subject_lower, body_lower)
    if unsub_result[0]:
        return SystemEmailDetection(
            is_system=True,
            email_type=EmailType.SYSTEM,
            system_subtype=SystemSubtype.UNSUBSCRIBE,
            confidence=unsub_result[1],
            detection_reason=unsub_result[2]
        )
    
    # Priority 4: Generic auto-reply (lowest priority system type)
    auto_result = _detect_auto_reply(from_email_lower, subject_lower, body_lower)
    if auto_result[0]:
        return SystemEmailDetection(
            is_system=True,
            email_type=EmailType.SYSTEM,
            system_subtype=SystemSubtype.AUTO_REPLY,
            confidence=auto_result[1],
            detection_reason=auto_result[2]
        )
    
    # Not a system email - requires AI classification
    return SystemEmailDetection(
        is_system=False,
        email_type=EmailType.NORMAL,
        system_subtype=None,
        confidence=1.0,
        detection_reason="No system email patterns detected"
    )


def _detect_bounce(
    from_email: str,
    subject: str,
    body: str
) -> Tuple[bool, float, str]:
    """
    Detect bounce/delivery failure emails.
    
    Returns: (is_bounce, confidence, reason)
    """
    reasons = []
    
    # Check sender
    for pattern in BOUNCE_SENDER_PATTERNS:
        if re.search(pattern, from_email, re.IGNORECASE):
            reasons.append(f"sender matches: {pattern}")
            break
    
    # Check subject
    for pattern in BOUNCE_SUBJECT_PATTERNS:
        if re.search(pattern, subject, re.IGNORECASE):
            reasons.append(f"subject matches: {pattern}")
            break
    
    # Check body
    body_matches = 0
    for pattern in BOUNCE_BODY_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            body_matches += 1
            if body_matches == 1:
                reasons.append(f"body matches: {pattern}")
    
    # Scoring: sender match + (subject or body) = high confidence
    if reasons:
        has_sender = any("sender" in r for r in reasons)
        has_content = any("subject" in r or "body" in r for r in reasons)
        
        if has_sender and has_content:
            return True, 0.95, f"Bounce detected: {'; '.join(reasons)}"
        elif has_sender:
            return True, 0.85, f"Bounce detected (sender): {'; '.join(reasons)}"
        elif len(reasons) >= 2 or body_matches >= 2:
            return True, 0.80, f"Bounce detected (content): {'; '.join(reasons)}"
    
    return False, 0.0, ""


def _detect_out_of_office(
    from_email: str,
    subject: str,
    body: str
) -> Tuple[bool, float, str]:
    """
    Detect Out of Office / vacation auto-responders.
    
    Returns: (is_ooo, confidence, reason)
    """
    reasons = []
    
    # Subject is strong indicator
    for pattern in OOO_SUBJECT_PATTERNS:
        if re.search(pattern, subject, re.IGNORECASE):
            reasons.append(f"subject matches OOO: {pattern}")
            return True, 0.90, reasons[0]
    
    # Body patterns need multiple matches for confidence
    body_matches = 0
    for pattern in OOO_BODY_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            body_matches += 1
            reasons.append(f"body matches OOO: {pattern}")
    
    if body_matches >= 2:
        return True, 0.85, f"OOO detected: {'; '.join(reasons[:2])}"
    elif body_matches == 1:
        return True, 0.70, reasons[0]
    
    return False, 0.0, ""


def _detect_unsubscribe(
    subject: str,
    body: str
) -> Tuple[bool, float, str]:
    """
    Detect unsubscribe confirmation emails.
    
    Returns: (is_unsubscribe, confidence, reason)
    """
    for pattern in UNSUBSCRIBE_SUBJECT_PATTERNS:
        if re.search(pattern, subject, re.IGNORECASE):
            return True, 0.90, f"Unsubscribe detected: subject matches {pattern}"
    
    return False, 0.0, ""


def _detect_auto_reply(
    from_email: str,
    subject: str,
    body: str
) -> Tuple[bool, float, str]:
    """
    Detect generic automated replies (not OOO or bounce).
    
    Returns: (is_auto_reply, confidence, reason)
    """
    reasons = []
    
    # Check sender patterns
    sender_match = False
    for pattern in AUTO_REPLY_SENDER_PATTERNS:
        if re.search(pattern, from_email, re.IGNORECASE):
            reasons.append(f"sender: {pattern}")
            sender_match = True
            break
    
    # Check subject
    subject_match = False
    for pattern in AUTO_REPLY_SUBJECT_PATTERNS:
        if re.search(pattern, subject, re.IGNORECASE):
            reasons.append(f"subject: {pattern}")
            subject_match = True
            break
    
    # Need both sender and subject for auto-reply (avoid false positives)
    if sender_match and subject_match:
        return True, 0.80, f"Auto-reply detected: {'; '.join(reasons)}"
    
    return False, 0.0, ""


# ============== DEDUPLICATION ==============

def compute_dedupe_hash(
    email: Dict[str, Any],
    body_fingerprint_length: int = 500
) -> str:
    """
    Compute global content-based deduplication hash.
    
    Hash components:
    1. Normalized subject (strip Re:/Fw:/Fwd: prefixes, lowercase)
    2. Canonical sender email (lowercase, stripped)
    3. Stable body fingerprint (first N chars, whitespace normalized)
    
    This ensures the same logical email produces the same hash
    regardless of which mailbox receives it.
    
    Args:
        email: Email document
        body_fingerprint_length: Chars of body to include (default 500)
        
    Returns:
        SHA256 hex digest string
    """
    # 1. Normalize subject
    subject = (email.get("subject") or "").strip()
    normalized_subject = _normalize_subject(subject)
    
    # 2. Canonical sender
    sender = _extract_email_address(email.get("from_address", {}))
    canonical_sender = sender.lower().strip()
    
    # 3. Body fingerprint (whitespace-normalized prefix)
    body = (email.get("body_plain") or email.get("snippet") or "")
    body_fingerprint = _compute_body_fingerprint(body, body_fingerprint_length)
    
    # Combine components
    dedupe_string = f"{normalized_subject}|{canonical_sender}|{body_fingerprint}"
    
    # SHA256 hash
    return hashlib.sha256(dedupe_string.encode("utf-8")).hexdigest()


def _normalize_subject(subject: str) -> str:
    """
    Normalize email subject for deduplication.
    
    - Remove Re:/RE:/Fw:/FW:/Fwd:/FWD: prefixes (recursive)
    - Lowercase
    - Strip whitespace
    - Collapse multiple spaces
    """
    if not subject:
        return ""
    
    # Remove common reply/forward prefixes (recursive)
    prefix_pattern = r"^(re|fw|fwd)\s*:\s*"
    normalized = subject.lower().strip()
    
    # Repeatedly strip prefixes
    while True:
        new_normalized = re.sub(prefix_pattern, "", normalized, flags=re.IGNORECASE).strip()
        if new_normalized == normalized:
            break
        normalized = new_normalized
    
    # Collapse whitespace
    normalized = re.sub(r"\s+", " ", normalized)
    
    return normalized


def _compute_body_fingerprint(body: str, length: int) -> str:
    """
    Compute stable body fingerprint.
    
    - Strip common boilerplate patterns BEFORE normalization
    - Take first N characters of core content
    - Normalize whitespace
    
    This ensures emails with different signatures/footers hash the same.
    """
    if not body:
        return ""
    
    # Work on lowercase for pattern matching
    text = body
    text_lower = body.lower()
    
    # Strip signature markers and what follows (BEFORE whitespace normalization)
    signature_markers = [
        r"\n\s*--\s*\n",     # Standard sig delimiter: \n--\n
        r"\n\s*--\s*$",      # Sig delimiter at end
        r"\nsent from my ",
        r"\nget outlook for",
        r"\n\s*best regards",
        r"\n\s*kind regards",
        r"\n\s*sincerely",
        r"\n\s*thanks,",
        r"\n\s*thank you,",
        r"\n\s*regards,",
        r"\n\s*cheers,",
        r"\n\s*best,",
    ]
    
    # Find earliest signature marker
    earliest_cut = len(text)
    for marker in signature_markers:
        match = re.search(marker, text_lower)
        if match and match.start() < earliest_cut:
            earliest_cut = match.start()
    
    # Cut at earliest signature marker
    if earliest_cut < len(text):
        text = text[:earliest_cut]
    
    # Now normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    
    # Take first N chars and lowercase
    return text[:length].lower()


def _extract_email_address(addr: Any) -> str:
    """Extract email string from address object or string."""
    if isinstance(addr, dict):
        return addr.get("email", "") or addr.get("address", "") or ""
    elif isinstance(addr, str):
        # Try to extract email from "Name <email@domain.com>" format
        match = re.search(r"<([^>]+)>", addr)
        if match:
            return match.group(1)
        return addr
    return ""


# ============== CONVENIENCE FUNCTIONS ==============

def is_system_email(email: Dict[str, Any]) -> bool:
    """
    Quick check if email is a system email.
    
    Args:
        email: Email document
        
    Returns:
        True if system email, False if normal email requiring classification
    """
    return detect_system_email(email).is_system


def should_skip_llm_classification(email: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Determine if email should skip LLM classification entirely.
    
    Use this as the guard before any LLM call.
    
    Args:
        email: Email document
        
    Returns:
        Tuple of (should_skip, reason)
    """
    # Check if already marked as system
    if email.get("email_type") == EmailType.SYSTEM.value:
        return True, f"Already marked as system email: {email.get('system_subtype')}"
    
    # Check if already has dedupe_hash and was processed
    if email.get("dedupe_hash") and email.get("processed"):
        return True, "Already processed (has dedupe_hash and processed=True)"
    
    # Run detection
    detection = detect_system_email(email)
    if detection.is_system:
        return True, detection.detection_reason
    
    return False, "Normal email - requires classification"


def generate_system_email_summary(
    email: Dict[str, Any],
    system_subtype: SystemSubtype
) -> str:
    """
    Generate deterministic summary for system emails.
    
    System emails do NOT go through LLM for summarization.
    
    Args:
        email: Email document
        system_subtype: The detected system subtype
        
    Returns:
        Short, deterministic summary string
    """
    sender = _extract_email_address(email.get("from_address", {}))
    subject = (email.get("subject") or "")[:50]
    
    if system_subtype == SystemSubtype.BOUNCE:
        return f"Delivery failure notification for message to {sender or 'recipient'}"
    elif system_subtype == SystemSubtype.OUT_OF_OFFICE:
        return f"Out of office auto-reply from {sender}"
    elif system_subtype == SystemSubtype.AUTO_REPLY:
        return f"Automated response: {subject}" if subject else f"Automated response from {sender}"
    elif system_subtype == SystemSubtype.UNSUBSCRIBE:
        return f"Unsubscribe confirmation"
    else:
        return f"System notification from {sender}"
