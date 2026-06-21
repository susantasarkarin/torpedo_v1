"""
Bounce re-enrichment using Claude AI.

When a sent email hard-bounces, this module:

  1. Logs the bounce in bounce_log
  2. Tries cheap pattern variants first (no API cost):
       {first}{last}@domain, {f}.{last}@domain, {first}_{last}@domain, etc.
  3. If all variants fail → asks Claude to reason about the person and
       suggest alternative email formats, nickname expansions, or alias
       patterns specific to this company
  4. Tries each AI candidate in ranked order
  5. Falls back to Hunter email-finder as last resort (costs a credit)
  6. Updates the lead row and bounce_log with the outcome

Email "trying" at this stage means checking deliverability via a lightweight
SMTP verification (MX + RCPT TO probe using smtplib) rather than sending a
real message. This avoids burning send credits on guesses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import smtplib
import socket
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import anthropic
import httpx

from . import state as st
from .enricher import apply_pattern, _hunter_domain_search
from .schemas import EnrichedLead

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")
HUNTER_BASE = "https://api.hunter.io/v2"
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Alternative patterns to try before calling any API
_PATTERN_VARIANTS = [
    "{first}.{last}",
    "{first}{last}",
    "{f}.{last}",
    "{f}{last}",
    "{first}_{last}",
    "{first}",
    "{first}{l}",
    "{first}.{l}",
]

# ---------------------------------------------------------------------------
# SMTP deliverability probe (no email sent)
# ---------------------------------------------------------------------------

def _smtp_verify(email: str, timeout: int = 6) -> bool:
    """
    Lightweight SMTP probe: resolve MX, open connection, RCPT TO.
    Returns True if the server accepts the address (250), False otherwise.
    Does NOT send any email.
    """
    import dns.resolver  # dnspython
    domain = email.split("@")[-1]
    try:
        mx_records = dns.resolver.resolve(domain, "MX")
        mx_host = str(sorted(mx_records, key=lambda r: r.preference)[0].exchange).rstrip(".")
    except Exception:
        return False

    try:
        with smtplib.SMTP(mx_host, 25, timeout=timeout) as smtp:
            smtp.ehlo("torpedo-verify.local")
            code, _ = smtp.rcpt(email)
            return code == 250
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Pattern variant generator
# ---------------------------------------------------------------------------

def _generate_variants(first: str, last: str, domain: str) -> List[Tuple[str, str]]:
    """
    Return (email, pattern) pairs for each standard variant.
    Skips variants that produce an empty local part.
    """
    results = []
    for pattern in _PATTERN_VARIANTS:
        local = apply_pattern(pattern, first, last)
        if local:
            results.append((f"{local}@{domain}", pattern))
    # Deduplicate preserving order
    seen: set = set()
    unique = []
    for item in results:
        if item[0] not in seen:
            seen.add(item[0])
            unique.append(item)
    return unique


# ---------------------------------------------------------------------------
# Claude AI re-enrichment
# ---------------------------------------------------------------------------

_AI_SYSTEM = """You are an expert at B2B email deliverability.
Given a person's name, job title, company, and domain, generate alternative
professional email formats that might exist at that company.

Consider:
- Common nickname expansions (William→Bill, Robert→Rob, Elizabeth→Liz, etc.)
- Middle name usage (if inferable from the full name)
- Hyphenated names (Mary-Jane→maryjane, mary-jane, mj, maryjane)
- Regional naming conventions
- How the company's existing pattern differs from what bounced

Output ONLY a JSON object:
{
  "candidates": [
    {"email": "...", "rationale": "...", "confidence": 0.0-1.0}
  ]
}

Order by confidence descending. Maximum 8 candidates.
"""


def _call_claude_for_candidates(
    first: str,
    last: str,
    domain: str,
    title: Optional[str],
    company: Optional[str],
    bounced_email: str,
    known_pattern: Optional[str],
    existing_patterns_at_domain: List[str],
) -> List[Dict[str, Any]]:
    """
    Ask Claude to suggest alternative email candidates.
    Returns list of {email, rationale, confidence} dicts, sorted by confidence.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""
Person:
  Full name: {first} {last}
  Title: {title or 'unknown'}
  Company: {company or 'unknown'}
  Domain: {domain}

Email that bounced: {bounced_email}
Known Hunter.io pattern for this domain: {known_pattern or 'none'}
Other patterns seen at this domain: {existing_patterns_at_domain or []}

Generate alternative email candidates.
"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=_AI_SYSTEM,
            messages=[{"role": "user", "content": prompt.strip()}],
        )
        raw = response.content[0].text
        logger.debug("BounceHandler Claude raw: %s", raw[:400])

        # Parse JSON
        text = raw.strip()
        if "```" in text:
            for part in text.split("```"):
                if "{" in part:
                    text = part.lstrip("json").strip()
                    break
        data = json.loads(text)
        candidates = data.get("candidates", [])
        return sorted(candidates, key=lambda c: c.get("confidence", 0), reverse=True)

    except Exception as exc:
        logger.error("BounceHandler Claude call failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Hunter email-finder fallback
# ---------------------------------------------------------------------------

async def _hunter_email_finder(
    first: str, last: str, domain: str
) -> Optional[str]:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{HUNTER_BASE}/email-finder",
                params={
                    "domain": domain,
                    "first_name": first,
                    "last_name": last,
                    "api_key": HUNTER_API_KEY,
                },
                timeout=12,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            email = data.get("email")
            score = data.get("score", 0)
            return email if email and score >= 50 else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def handle_bounce(
    bounced_email: str,
    bounce_type: str = "hard",
    external_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Handle a bounce for a given email address.

    Lookup order:
      1. Cheap pattern variants (SMTP probe each, no API)
      2. Claude AI candidates (SMTP probe each)
      3. Hunter email-finder (last resort, costs a credit)

    Returns a dict describing the outcome:
      {
        "status": "resolved" | "unresolved",
        "new_email": "...",      # only if resolved
        "source": "...",         # how we found it
        "bounce_log_id": int,
        "candidates_tried": [...],
      }
    """
    # Resolve the lead
    lead_row: Optional[Dict[str, Any]] = None
    if external_id:
        lead_row = st.get_lead_by_external_id(external_id)
    if not lead_row:
        lead_row = st.get_lead_by_email(bounced_email)

    if not lead_row:
        return {
            "status": "unresolved",
            "error": f"No lead found for email {bounced_email}",
        }

    eid = lead_row["external_id"]
    first = lead_row.get("first_name") or ""
    last = lead_row.get("last_name") or ""
    domain = lead_row.get("company_domain") or bounced_email.split("@")[-1]
    title = lead_row.get("title")
    company = lead_row.get("company")

    if not first:
        # Try splitting from name field
        parts = (lead_row.get("name") or "").split()
        first = parts[0] if parts else ""
        last = " ".join(parts[1:]) if len(parts) > 1 else ""

    # 1. Log the bounce
    bounce_log_id = st.log_bounce(eid, bounced_email, bounce_type)

    known_pattern = None
    cached = st.get_domain_pattern(domain)
    if cached:
        known_pattern = cached.get("pattern")

    candidates_tried: List[str] = []

    # 2. Try cheap pattern variants first
    variants = _generate_variants(first, last, domain)
    # Remove the already-bounced email
    variants = [(e, p) for e, p in variants if e.lower() != bounced_email.lower()]

    for candidate_email, pattern_used in variants:
        candidates_tried.append(candidate_email)
        if _smtp_verify(candidate_email):
            st.record_re_enrichment(
                bounce_log_id, eid, candidate_email,
                source="pattern_variant",
                ai_candidates=candidates_tried,
            )
            logger.info("Bounce resolved via pattern variant: %s", candidate_email)
            return {
                "status": "resolved",
                "new_email": candidate_email,
                "source": "pattern_variant",
                "bounce_log_id": bounce_log_id,
                "candidates_tried": candidates_tried,
            }

    # 3. Claude AI candidates
    existing_domain_patterns = [known_pattern] if known_pattern else []
    ai_suggestions = _call_claude_for_candidates(
        first, last, domain, title, company, bounced_email,
        known_pattern, existing_domain_patterns,
    )

    for suggestion in ai_suggestions:
        candidate_email = suggestion.get("email", "").lower().strip()
        if not candidate_email or candidate_email in candidates_tried:
            continue
        if candidate_email.lower() == bounced_email.lower():
            continue
        candidates_tried.append(candidate_email)
        if _smtp_verify(candidate_email):
            st.record_re_enrichment(
                bounce_log_id, eid, candidate_email,
                source="ai_guess",
                ai_candidates=candidates_tried,
            )
            logger.info("Bounce resolved via AI: %s", candidate_email)
            return {
                "status": "resolved",
                "new_email": candidate_email,
                "source": "ai_guess",
                "bounce_log_id": bounce_log_id,
                "candidates_tried": candidates_tried,
            }

    # 4. Hunter email-finder (last resort)
    if first and domain:
        hunter_email = await _hunter_email_finder(first, last, domain)
        if hunter_email and hunter_email.lower() != bounced_email.lower():
            candidates_tried.append(hunter_email)
            st.record_re_enrichment(
                bounce_log_id, eid, hunter_email,
                source="hunter_finder",
                ai_candidates=candidates_tried,
            )
            logger.info("Bounce resolved via Hunter email-finder: %s", hunter_email)
            return {
                "status": "resolved",
                "new_email": hunter_email,
                "source": "hunter_finder",
                "bounce_log_id": bounce_log_id,
                "candidates_tried": candidates_tried,
            }

    # All attempts failed
    logger.warning("Could not resolve bounce for %s after %d candidates", bounced_email, len(candidates_tried))
    return {
        "status": "unresolved",
        "bounce_log_id": bounce_log_id,
        "candidates_tried": candidates_tried,
        "message": "All resolution strategies exhausted. Lead marked bounced.",
    }
