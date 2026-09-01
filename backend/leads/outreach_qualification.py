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


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    try:
        from ..database import get_client
    except ImportError:
        from database import get_client
    return get_client()


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
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
_client = _get_pooled_client()
_db = _client["email_automation"]

# The real outreach send/bounce data does NOT live in email_automation.
# is_previously_contacted() and check_suppression() below were reading
# _db (email_automation) for outreach_sends_v2 (doesn't exist there — the
# real 60,309-doc collection is on torpedo) and via SuppressionListManager
# for suppression_list (exists on email_automation but has 0 documents —
# nothing has ever written to it; not itself a wrong-pointer bug, just an
# unfed explicit-suppression store). Neither ever consulted
# torpedo.outreach_bounce_suppression, the 11,508-doc collection
# cold_outreach_router.py's own enrollment check actually reads and writes.
# This was never correct — git history shows no prior commit where these
# pointed at torpedo; it was written wrong from the start.
_torpedo_db = _client["torpedo"]

# Email statuses that mean "this address was inferred, not verified".
UNVERIFIED_EMAIL_STATUSES = {
    "pending_pattern", "guessed", "unverified", "pattern_guess", "invalid",
}

# email_status is a DELIVERABILITY label (bounced / delivered / valid / ...).
# email_source is a PROVENANCE label (how the address was obtained) — and the
# two drift independently. A lead can carry email_status="Valid" or
# "Delivered" while its email_source shows it was rendered by our own
# pattern/guess machinery, never observed anywhere — 2,888 leads sourced from
# the disabled bounce_recovery_alt guesser alone were sitting under
# Delivered/Valid/Catch-All/Unknown/bounced, none of which the status-based
# checks above ever look at. Confirmed against a full enumeration of
# leads_enriched.email_source (see the commit this set was introduced in) —
# every currently-observed non-null value is something OUR code rendered or
# found, not something given to us directly:
#   - bounce_recovery_alt / bounce_recovery_skrapp: bounce_recovery.py's
#     recovery guessers (alt_format template guessing, Skrapp lookup)
#   - pattern_applied / pattern_reapplied / pattern_migration: a stored
#     domain pattern rendered for this specific person — even
#     "pattern_applied" is a RENDERED address, not an observed one, which is
#     why cold_outreach_router.py's own pre-send bounce-risk guard
#     (line ~2330) already treats it as risky, alongside pattern_derived/
#     guessed/pattern_guess
#   - pattern_derived / name_domain_guess / name_domain_inferred: direct
#     firstname.lastname@domain construction, no pattern verification at all
#   - guess / claude_web_search: EmailPatternSystem.build_email_with_source's
#     own tier names for its last-resort guess and its web-search find
# A null/missing email_source is NOT in this set — that's the untagged
# population (raw CSV emails, Gmail-reply sender addresses, and other
# directly-observed addresses that never went through the pattern system).
GUESSED_EMAIL_SOURCES = {
    "bounce_recovery_alt", "bounce_recovery_skrapp",
    "pattern_applied", "pattern_reapplied", "pattern_migration",
    "pattern_derived", "name_domain_guess", "name_domain_inferred",
    "guess", "claude_web_search",
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

    # "Predicted" covers everything from a Hunter/Skrapp-verified pattern
    # (confidence ~0.9) down to a blind firstname.lastname guess with nobody
    # ever confirming it (confidence 0.2-0.3) — the status alone doesn't
    # distinguish them. email_pattern_confidence is set at build time by
    # EmailPatternSystem.build_email(); below 0.5 the address is still just a
    # guess (or an unconfirmed web-search hit) and must not qualify.
    #
    # Gated on status=="predicted" OR email_source in GUESSED_EMAIL_SOURCES,
    # not status alone: email_status is a DELIVERABILITY label and
    # email_source is a PROVENANCE label, and they drift independently. 2,888
    # leads whose email_source shows a guess/pattern-render (bounce_recovery_alt
    # etc.) were sitting under email_status values of Delivered/Valid/
    # Catch-All/Unknown/bounced — none of which trip the "predicted" branch —
    # and sailed through ungated. Checking provenance directly, in addition to
    # status, closes that.
    #
    # A qualifying lead with NO email_pattern_confidence at all is not a
    # verified email either — it's a legacy record from before this field
    # existed, or a write path that forgot to set it. Treating missing the
    # same as high-confidence was the exact hole that let 2,355 leads with a
    # status of "Predicted" and no confidence value sail through ungated.
    # Missing must fail closed, not open — so this only ever skips the check
    # when NEITHER trigger applies (a raw_email lead carries its source's own
    # status, e.g. "Valid", untagged email_source, and correctly has no
    # pattern confidence to speak of).
    source = (lead.get("email_source") or "").strip().lower()
    if status == "predicted" or source in GUESSED_EMAIL_SOURCES:
        confidence = lead.get("email_pattern_confidence")
        if confidence is None:
            return "unverified_email"
        try:
            if float(confidence) < 0.5:
                return "unverified_email"
        except (TypeError, ValueError):
            return "unverified_email"

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


def is_bounce_suppressed(email: str) -> bool:
    """
    True when this address is on the real bounce-suppression list.

    Reads torpedo.outreach_bounce_suppression — the collection
    cold_outreach_router.py's own enrollment check (_enroll_basket_leads)
    populates and consults directly. Nothing in this module ever checked it
    before; SuppressionListManager's email_automation.suppression_list is a
    separate, currently-unfed explicit-suppression store (unsubscribe/
    complaint additions via .add()), not a wrong pointer to the same data —
    kept as-is below.
    """
    email_lower = (email or "").lower().strip()
    if not email_lower:
        return False
    try:
        return bool(_torpedo_db["outreach_bounce_suppression"].count_documents(
            {"email": email_lower}, limit=1))
    except Exception as e:
        logger.debug("bounce-suppression check failed: %s", e)
        return False


def check_suppression(email: str) -> Optional[str]:
    """Return a rejection reason, or None when the address is clear to email."""
    if is_bounce_suppressed(email):
        return "suppressed_bounced"
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
