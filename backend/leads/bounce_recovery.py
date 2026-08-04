"""
Bounce Recovery Module
======================

3-attempt chain to recover a lead whose email bounced:

  Attempt 1 (original send): handled by normal outreach pipeline.
  Attempt 2 (this module, method='alt_format'):
      Rules-based predictor tries 6 common email formats in order,
      skipping any already tried. Sends to the first untried format.
  Attempt 3 (this module, method='skrapp'):
      Calls EmailPatternSystem.discover_company_email_pattern(domain)
      (which uses Skrapp.io / Hunter.io / web-scrape as fallback).
      Stores any discovered pattern and applies it to all domain leads.
      Sends to the recovered email.
  All attempts exhausted:
      Marks lead 'needs_human_intervention'. No more automated sends.

New fields on outreach_leads_v2 (backward-compatible, added only when
bounce recovery is triggered):
  bounce_recovery_attempt       int   â€” how many recovery cycles have run
  bounce_recovery_status        str   â€” 'recovering' | 'recovered' | 'needs_human_intervention'
  bounce_recovery_emails_tried  list  â€” all emails attempted (original + each recovery)
  bounce_recovery_method        str   â€” last method used ('alt_format' | 'skrapp')

New fields on leads_enriched (updated in parallel):
  email_status                  str   â€” 'Predicted' when a recovery email is set
  email_source                  str   â€” 'bounce_recovery_alt' | 'bounce_recovery_skrapp'
  bounce_recovery_status        str   â€” mirrors outreach_leads_v2

Usage (called from cold_outreach_router.py bounce scanner):
    from leads.bounce_recovery import attempt_recovery
    result = attempt_recovery(outreach_lead_id, bounced_email)
    # result = {"action": "retry", "email": "...", "method": "..."}
    # result = {"action": "human_intervention"}
    # result = {"action": "already_recovering"}
    # result = {"action": "no_lead_found"}
"""

import logging
import os
import re
from datetime import datetime
from typing import Optional, Dict, Any

from bson import ObjectId
from pymongo import MongoClient

logger = logging.getLogger(__name__)

# Attempt-2 alt-format guessing. Off by default — see the note at its call
# site for the bounce-rate data that motivated this.
_ALT_FORMAT_ENABLED = (
    os.getenv("OUTREACH_BOUNCE_RECOVERY_ALT", "false").lower() == "true")

# ---------------------------------------------------------------------------
# Common email format templates (rules-based, attempt 2)
# Placeholders: {first}, {last}, {f} (first initial), {l} (last initial)
# ---------------------------------------------------------------------------
ALT_FORMAT_TEMPLATES = [
    "{first}.{last}@{domain}",       # john.doe   â€” most common
    "{first}{last}@{domain}",        # johndoe
    "{f}{last}@{domain}",            # jdoe
    "{first}@{domain}",              # john
    "{first}_{last}@{domain}",       # john_doe
    "{first}.{l}@{domain}",          # john.d
]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_outreach_db():
    uri = os.getenv("MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
    db_name = os.getenv("MONGO_DB_NAME") or "torpedo"
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return client[db_name]


def _get_leads_db():
    uri = os.getenv("MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return client["email_automation"]


# ---------------------------------------------------------------------------
# Core: build a new email for a given name + domain using a format template
# ---------------------------------------------------------------------------

def _render_format(template: str, first: str, last: str, domain: str) -> str:
    first = (first or "").strip().lower()
    last = (last or "").strip().lower()
    f = first[0] if first else ""
    l = last[0] if last else ""
    return template.format(first=first, last=last, f=f, l=l, domain=domain)


def _is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


# ---------------------------------------------------------------------------
# Core: schedule a resend for an outreach_leads_v2 lead with a new email
# ---------------------------------------------------------------------------

def _schedule_resend(db, lead_doc: dict, new_email: str, method: str) -> None:
    """
    Update outreach_leads_v2 to retry the sequence with a new email address.
    Resets workflow_status to 'not_started' so the send runner picks it up.
    Only resends from step 0 (fresh sequence start).
    """
    now = datetime.utcnow()
    db["outreach_leads_v2"].update_one(
        {"_id": lead_doc["_id"]},
        {"$set": {
            "email": new_email,
            "workflow_status": "not_started",
            "current_step": 0,
            "next_send_at": now,
            "bounced_at": None,
            "bounce_recovery_method": method,
            "bounce_recovery_status": "recovering",
            "updated_at": now,
        }}
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def attempt_recovery(outreach_lead_id: str, bounced_email: str) -> Dict[str, Any]:
    """
    Called immediately after a bounce is detected for a lead.

    Parameters
    ----------
    outreach_lead_id : str
        _id of the record in outreach_leads_v2
    bounced_email : str
        The email address that bounced (for suppression tracking)

    Returns
    -------
    dict with 'action' key:
        {"action": "retry",              "email": <new_email>, "method": <method>}
        {"action": "human_intervention"}
        {"action": "already_recovering"}
        {"action": "no_lead_found"}
        {"action": "insufficient_name_data"}
        {"action": "no_domain"}
    """
    try:
        db = _get_outreach_db()
        leads_db = _get_leads_db()
        now = datetime.utcnow()

        # Load the outreach lead record
        try:
            oid = ObjectId(outreach_lead_id)
        except Exception:
            logger.warning(f"[BounceRecovery] Invalid ObjectId: {outreach_lead_id}")
            return {"action": "no_lead_found"}

        lead_doc = db["outreach_leads_v2"].find_one({"_id": oid})
        if not lead_doc:
            return {"action": "no_lead_found"}

        # Don't re-trigger if already flagged for human review
        if lead_doc.get("bounce_recovery_status") == "needs_human_intervention":
            return {"action": "human_intervention"}

        # Track which emails we've already tried
        emails_tried: list = lead_doc.get("bounce_recovery_emails_tried") or []
        if bounced_email and bounced_email not in emails_tried:
            emails_tried.append(bounced_email.lower().strip())

        # Persist the updated tried-list immediately
        db["outreach_leads_v2"].update_one(
            {"_id": oid},
            {"$set": {
                "bounce_recovery_emails_tried": emails_tried,
                "updated_at": now,
            }}
        )

        recovery_attempt = lead_doc.get("bounce_recovery_attempt", 0)

        # ----------------------------------------------------------------
        # Resolve name and domain from outreach_leads_v2 â†’ leads_enriched
        # ----------------------------------------------------------------
        lead_id = lead_doc.get("lead_id") or lead_doc.get("enriched_lead_id")
        enriched_lead = None
        if lead_id:
            try:
                enriched_lead = leads_db["leads_enriched"].find_one(
                    {"_id": ObjectId(str(lead_id))}
                )
            except Exception:
                pass

        # Prefer data from leads_enriched; fall back to outreach record
        source = enriched_lead or lead_doc
        first = source.get("first_name") or ""
        last = source.get("last_name") or ""
        # If no split name, try splitting the full name
        if not first:
            full_name = source.get("name") or ""
            parts = full_name.strip().split()
            if parts:
                first = parts[0]
                last = parts[-1] if len(parts) > 1 else ""

        # Extract domain from the bounced email as the most reliable source
        domain = ""
        if "@" in (bounced_email or ""):
            domain = bounced_email.split("@")[1].lower().strip()
        if not domain:
            domain = (
                source.get("company_domain") or
                source.get("company_website") or ""
            ).lower().strip()
            # Strip scheme/path if a URL slipped in
            domain = re.sub(r"^https?://", "", domain).split("/")[0]

        if not domain:
            logger.warning(f"[BounceRecovery] No domain for lead {outreach_lead_id}")
            _flag_human_intervention(db, leads_db, oid, lead_id, emails_tried, "no_domain")
            return {"action": "no_domain"}

        if not first:
            logger.warning(f"[BounceRecovery] No first name for lead {outreach_lead_id}")
            _flag_human_intervention(db, leads_db, oid, lead_id, emails_tried, "no_name")
            return {"action": "insufficient_name_data"}

        # ----------------------------------------------------------------
        # Pre-recovery domain blacklist check — don't burn 6+ bounces on a
        # domain already known to have a >60% bounce rate.
        # ----------------------------------------------------------------
        try:
            from leads.email_pattern_system import get_pattern_system as _get_ps_rc
            if domain:
                _domain_risk = _get_ps_rc().get_domain_risk(domain)
                if _domain_risk.get("pattern_blacklisted"):
                    logger.warning(
                        f"[BounceRecovery] Domain '{domain}' is blacklisted "
                        f"(bounce_rate={_domain_risk.get('bounce_rate', 0):.0%}). "
                        f"Skipping recovery for {outreach_lead_id}."
                    )
                    _flag_human_intervention(db, leads_db, oid, lead_id, emails_tried, "domain_blacklisted")
                    return {"action": "human_intervention"}
        except Exception as _bl_err:
            logger.debug(f"[BounceRecovery] Domain blacklist check skipped: {_bl_err}")

        # ----------------------------------------------------------------
        # Attempt 2 — rules-based format guessing
        # ----------------------------------------------------------------
        # DISABLED BY DEFAULT. Measured 2026-08-03: this path enrolled 1,216
        # guessed addresses in 24h and drove indira@ to 45.6% and meera@ to
        # 44.2% bounce rates (susanta@, which this path does not feed, sat at
        # 0.6%). Guessing up to 6 formats per contact manufactures bounces
        # faster than the >60% domain blacklist can catch them, and mailbox
        # providers suspend senders well below that.
        # Set OUTREACH_BOUNCE_RECOVERY_ALT=true to re-enable once addresses
        # come from a verified source rather than pattern guesses.
        if recovery_attempt < 1 and not _ALT_FORMAT_ENABLED:
            logger.info(
                f"[BounceRecovery] alt-format guessing disabled — routing "
                f"{outreach_lead_id} to human intervention instead"
            )
            _flag_human_intervention(db, leads_db, oid, lead_id, emails_tried,
                                     "alt_format_disabled")
            return {"action": "human_intervention", "reason": "alt_format_disabled"}

        if recovery_attempt < 1:
            new_email = _attempt_alt_format(first, last, domain, emails_tried)
            if new_email:
                logger.info(
                    f"[BounceRecovery] Attempt 2 (alt_format): {outreach_lead_id} "
                    f"â†’ {new_email}"
                )
                _schedule_resend(db, lead_doc, new_email, "alt_format")
                db["outreach_leads_v2"].update_one(
                    {"_id": oid},
                    {"$set": {"bounce_recovery_attempt": 1}}
                )
                _update_enriched_email(leads_db, lead_id, new_email, "bounce_recovery_alt")
                return {"action": "retry", "email": new_email, "method": "alt_format"}
            else:
                # All 6 formats already tried â€” skip straight to attempt 3
                logger.info(
                    f"[BounceRecovery] All alt formats exhausted for {outreach_lead_id}, "
                    f"escalating to Skrapp"
                )

        # ----------------------------------------------------------------
        # Attempt 3 â€” Skrapp.io / EmailPatternSystem discovery
        # ----------------------------------------------------------------
        if recovery_attempt < 2:
            new_email = _attempt_skrapp_discovery(first, last, domain, emails_tried, leads_db)
            if new_email:
                logger.info(
                    f"[BounceRecovery] Attempt 3 (skrapp): {outreach_lead_id} "
                    f"â†’ {new_email}"
                )
                _schedule_resend(db, lead_doc, new_email, "skrapp")
                db["outreach_leads_v2"].update_one(
                    {"_id": oid},
                    {"$set": {"bounce_recovery_attempt": 2}}
                )
                _update_enriched_email(leads_db, lead_id, new_email, "bounce_recovery_skrapp")
                return {"action": "retry", "email": new_email, "method": "skrapp"}

        # ----------------------------------------------------------------
        # All attempts exhausted â†’ human intervention
        # ----------------------------------------------------------------
        logger.warning(
            f"[BounceRecovery] All recovery attempts exhausted for {outreach_lead_id}. "
            f"Emails tried: {emails_tried}"
        )
        _flag_human_intervention(db, leads_db, oid, lead_id, emails_tried, "all_attempts_exhausted")
        return {"action": "human_intervention"}

    except Exception as e:
        logger.error(f"[BounceRecovery] Unexpected error for {outreach_lead_id}: {e}")
        return {"action": "error", "detail": str(e)}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _attempt_alt_format(
    first: str, last: str, domain: str, emails_tried: list
) -> Optional[str]:
    """
    Try ALT_FORMAT_TEMPLATES in order, skipping already-tried addresses.
    Returns the first untried valid candidate, or None if all exhausted.
    """
    tried_set = {e.lower() for e in emails_tried}
    for template in ALT_FORMAT_TEMPLATES:
        candidate = _render_format(template, first, last, domain)
        if _is_valid_email(candidate) and candidate not in tried_set:
            return candidate
    return None


def _attempt_skrapp_discovery(
    first: str, last: str, domain: str, emails_tried: list, leads_db
) -> Optional[str]:
    """
    Use EmailPatternSystem (Skrapp / Hunter / web-scrape) to discover the
    company email pattern. Store the pattern for future reuse, then derive
    an email for this person.
    """
    tried_set = {e.lower() for e in emails_tried}
    try:
        from leads.email_pattern_system import get_pattern_system
        ps = get_pattern_system()

        # Discover pattern via full 5-tier hierarchy
        pattern_str = ps.discover_company_email_pattern(domain)
        if not pattern_str:
            return None

        # Apply the discovered pattern to all no-email leads with this domain
        try:
            ps.apply_pattern_to_domain_leads(domain, pattern_str)
        except Exception as _e:
            logger.debug(f"[BounceRecovery] apply_pattern_to_domain_leads failed: {_e}")

        # Build email for this specific person
        email, confidence = ps.build_email(first, last, domain)
        if email and _is_valid_email(email) and email.lower() not in tried_set:
            return email

    except Exception as e:
        logger.warning(f"[BounceRecovery] Skrapp discovery failed for {domain}: {e}")

    return None


def _update_enriched_email(
    leads_db, lead_id, new_email: str, source: str
) -> None:
    """Update the leads_enriched record with the recovery email."""
    if not lead_id:
        return
    try:
        leads_db["leads_enriched"].update_one(
            {"_id": ObjectId(str(lead_id))},
            {"$set": {
                "email": new_email,
                "email_status": "Predicted",
                "email_source": source,
                "bounce_recovery_status": "recovering",
                "updated_at": datetime.utcnow(),
            }}
        )
    except Exception as e:
        logger.debug(f"[BounceRecovery] Could not update leads_enriched: {e}")


def _flag_human_intervention(
    db, leads_db, oid: ObjectId, lead_id, emails_tried: list, reason: str
) -> None:
    """Mark the lead as needing human intervention in both collections."""
    now = datetime.utcnow()
    db["outreach_leads_v2"].update_one(
        {"_id": oid},
        {"$set": {
            "bounce_recovery_status": "needs_human_intervention",
            "bounce_recovery_reason": reason,
            "bounce_recovery_emails_tried": emails_tried,
            "workflow_status": "needs_human_intervention",
            "updated_at": now,
        }}
    )
    if not lead_id:
        return
    try:
        leads_db["leads_enriched"].update_one(
            {"_id": ObjectId(str(lead_id))},
            {"$set": {
                "bounce_recovery_status": "needs_human_intervention",
                "bounce_recovery_reason": reason,
                "bounce_recovery_emails_tried": emails_tried,
                "updated_at": now,
            }}
        )
    except Exception as e:
        logger.debug(f"[BounceRecovery] Could not update leads_enriched for human flag: {e}")

