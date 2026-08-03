"""
COLD OUTREACH QUALIFICATION
===========================

A lead may enter a cold-outreach bucket only if ALL of these hold:

  1. A real email address — present, syntactically valid, not an AI guess,
     and not a generic mailbox (info@, sales@, careers@ ...)
  2. ICP score above threshold AND lead_bracket == 'contact'
  3. An assigned bucket (SFW / COGENTIX_RESEARCH / BIM) with confidence at or
     above the configured threshold
  4. Not on the suppression list, and not previously contacted

Suppression reuses the existing `campaigns.suppression.SuppressionListManager`
(collection `suppression_list`, already indexed in indexes.py and fed by the
SES bounce sync) rather than introducing a second store. The one thing it does
not track — "we already emailed this person" — is derived here from the
outreach send log.

Every rejection carries a machine-readable reason so the funnel is auditable:

    qualify(lead) -> QualificationResult(qualified=False, reason='generic_email')
"""

import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pymongo import MongoClient

try:
    from .outreach_config import (
        CONFIDENCE_THRESHOLD,
        GENERIC_EMAIL_PREFIXES,
        MIN_ICP_SCORE,
        REQUIRED_LEAD_BRACKET,
        VALID_BUCKETS,
    )
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from leads.outreach_config import (
        CONFIDENCE_THRESHOLD,
        GENERIC_EMAIL_PREFIXES,
        MIN_ICP_SCORE,
        REQUIRED_LEAD_BRACKET,
        VALID_BUCKETS,
    )

logger = logging.getLogger("outreach_qualification")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_db = _client["email_automation"]

# Email statuses that mean "this address was inferred, not verified".
UNVERIFIED_EMAIL_STATUSES = {
    "pending_pattern", "guessed", "unverified", "pattern_guess", "invalid",
}

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


@dataclass
class QualificationResult:
    qualified: bool
    reason: str
    bucket: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# EMAIL CHECKS
# ============================================================

def is_generic_mailbox(email: str) -> bool:
    """True for role addresses that are not a specific person."""
    local = (email or "").split("@")[0].lower().strip()
    if not local:
        return True
    if local in GENERIC_EMAIL_PREFIXES:
        return True
    # Handle info.india@, sales-uk@, contact_us@
    first_token = re.split(r"[.\-_+]", local)[0]
    return first_token in GENERIC_EMAIL_PREFIXES


def check_email(lead: Dict[str, Any]) -> Optional[str]:
    """Return a rejection reason, or None when the email is usable."""
    email = (lead.get("email") or "").strip().lower()
    if not email:
        return "no_email"
    if not EMAIL_RE.match(email):
        return "malformed_email"

    status = (lead.get("email_status") or "").strip().lower()
    if status in UNVERIFIED_EMAIL_STATUSES:
        return "unverified_email"

    # An email that only ever came from an AI guess is not a real address.
    if lead.get("email_is_guess") or lead.get("email_candidate") == email:
        return "guessed_email"

    if is_generic_mailbox(email):
        return "generic_email"

    return None


# ============================================================
# SUPPRESSION
# ============================================================

_suppression_manager = None


def _get_suppression_manager():
    """Lazily bind the existing campaigns.suppression manager."""
    global _suppression_manager
    if _suppression_manager is None:
        try:
            from campaigns.suppression import get_suppression_manager
        except ImportError:
            from backend.campaigns.suppression import get_suppression_manager
        _suppression_manager = get_suppression_manager(_db)
    return _suppression_manager


def is_previously_contacted(email: str) -> bool:
    """
    True when we have already sent this address something. The suppression list
    intentionally does not track this — it is derived from the send log.
    """
    email_lower = (email or "").lower().strip()
    if not email_lower:
        return False
    for collection in ("outreach_sends_v2", "outreach_send_logs"):
        try:
            if _db[collection].count_documents({"email": email_lower}, limit=1):
                return True
        except Exception as e:
            logger.debug("send-history check failed on %s: %s", collection, e)
    return False


def check_suppression(email: str) -> Optional[str]:
    """Return a rejection reason, or None when the address is clear to email."""
    try:
        manager = _get_suppression_manager()
        if manager.is_suppressed(email):
            return f"suppressed_{manager.get_reason(email) or 'unknown'}"
    except Exception as e:
        # Fail closed: if we cannot verify suppression, do not send.
        logger.error("suppression check failed for %s: %s", email, e)
        return "suppression_check_failed"

    if is_previously_contacted(email):
        return "previously_contacted"

    return None


# ============================================================
# QUALIFICATION
# ============================================================

def qualify(lead: Dict[str, Any],
            confidence_threshold: float = CONFIDENCE_THRESHOLD,
            min_icp_score: int = MIN_ICP_SCORE,
            required_bracket: str = REQUIRED_LEAD_BRACKET,
            check_suppression_list: bool = True) -> QualificationResult:
    """
    Apply every cold-outreach gate. Returns the first failure, so the reason is
    the most significant one rather than a list.
    """
    lead_id = str(lead.get("_id", "?"))

    # --- 1. Email ----------------------------------------------------
    email_problem = check_email(lead)
    if email_problem:
        logger.info("lead=%s not qualified: %s", lead_id, email_problem)
        return QualificationResult(False, email_problem)

    email = lead["email"].strip().lower()

    # --- 2. ICP score and bracket -------------------------------------
    score = lead.get("icp_score")
    try:
        score = int(score) if score is not None else 0
    except (TypeError, ValueError):
        score = 0
    if score < min_icp_score:
        logger.info("lead=%s not qualified: icp_score %s < %s",
                    lead_id, score, min_icp_score)
        return QualificationResult(False, "icp_score_below_threshold",
                                   details={"icp_score": score})

    bracket = (lead.get("lead_bracket") or "").strip().lower()
    if bracket != required_bracket:
        logger.info("lead=%s not qualified: bracket %r != %r",
                    lead_id, bracket, required_bracket)
        return QualificationResult(False, "wrong_lead_bracket",
                                   details={"lead_bracket": bracket})

    # --- 3. Bucket and confidence -------------------------------------
    bucket = (lead.get("outreach_bucket") or "").strip().upper()
    if bucket not in VALID_BUCKETS:
        logger.info("lead=%s not qualified: bucket %r", lead_id, bucket or None)
        return QualificationResult(False, "no_bucket_assigned",
                                   details={"bucket": bucket or None})

    try:
        confidence = float(lead.get("outreach_bucket_confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < confidence_threshold:
        logger.info("lead=%s not qualified: confidence %.2f < %.2f",
                    lead_id, confidence, confidence_threshold)
        return QualificationResult(False, "bucket_confidence_below_threshold",
                                   bucket=bucket,
                                   details={"confidence": confidence})

    # --- 4. Suppression ----------------------------------------------
    if check_suppression_list:
        suppression_problem = check_suppression(email)
        if suppression_problem:
            logger.info("lead=%s not qualified: %s", lead_id, suppression_problem)
            return QualificationResult(False, suppression_problem, bucket=bucket)

    logger.info("lead=%s QUALIFIED bucket=%s score=%d confidence=%.2f",
                lead_id, bucket, score, confidence)
    return QualificationResult(True, "qualified", bucket=bucket,
                               details={"icp_score": score,
                                        "confidence": confidence})


def qualified_leads(bucket: Optional[str] = None,
                    limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Fetch leads that pass every gate. The Mongo query pre-filters on the cheap
    indexed conditions; the per-lead gates then run in Python.
    """
    query: Dict[str, Any] = {
        "email": {"$nin": [None, ""]},
        "outreach_bucket": {"$in": [bucket] if bucket else list(VALID_BUCKETS)},
    }

    out: List[Dict[str, Any]] = []
    for lead in _db["leads_raw"].find(query):
        if qualify(lead).qualified:
            out.append(lead)
            if limit and len(out) >= limit:
                break
    return out


def funnel_report() -> Dict[str, int]:
    """
    Count leads at each gate. Useful for answering 'why is nothing sending?'
    without reading logs.
    """
    counts: Dict[str, int] = {"total": 0, "qualified": 0}
    for lead in _db["leads_raw"].find({}):
        counts["total"] += 1
        result = qualify(lead, check_suppression_list=False)
        if result.qualified:
            counts["qualified"] += 1
        else:
            counts[result.reason] = counts.get(result.reason, 0) + 1
    return counts
