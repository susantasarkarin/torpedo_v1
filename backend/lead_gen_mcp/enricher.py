"""
Email enricher -- Skrapp.io person lookup (owner, 2026-10-15: Hunter removed).

Flow per lead:
  1. Split name into first / last
  2. Ask Skrapp for this person's address by name + company (skrapp.py).
     Skrapp verifies what it returns; only "valid" is used.
  3. Save the company's domain + pattern (and company data) in SQLite for
     audit and reuse.
  4. Store email_pattern on the lead.

Hunter used to be asked for the company's PATTERN, which was then applied to
names -- a guess per person. Skrapp answers for the person.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .schemas import DomainPattern, EnrichedLead, EnrichOutput, ScoredLead
from . import state as st
from . import skrapp

_DEFAULT_MIN_CONFIDENCE = 70

# Hunter pattern tokens → substitution rules
_PATTERN_SUBS = [
    ("{first}",  lambda f, l: f.lower()),
    ("{last}",   lambda f, l: l.lower()),
    ("{f}",      lambda f, l: f[0].lower() if f else ""),
    ("{l}",      lambda f, l: l[0].lower() if l else ""),
    ("{F}",      lambda f, l: f[0].upper() if f else ""),
    ("{L}",      lambda f, l: l[0].upper() if l else ""),
    ("{First}",  lambda f, l: f.capitalize()),
    ("{Last}",   lambda f, l: l.capitalize()),
]


def _split_name(full_name: Optional[str]) -> Tuple[str, str]:
    if not full_name:
        return "", ""
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _clean_domain(website: Optional[str]) -> Optional[str]:
    if not website:
        return None
    website = re.sub(r"^https?://", "", website).rstrip("/")
    website = re.sub(r"^www\.", "", website).split("/")[0]
    return website if "." in website else None


def apply_pattern(pattern: str, first: str, last: str) -> Optional[str]:
    """
    Construct a local-part from a Hunter pattern and first/last name.
    Returns None if essential tokens can't be filled (e.g. no last name for {last}).
    """
    result = pattern
    for token, fn in _PATTERN_SUBS:
        if token in result:
            replacement = fn(first, last)
            if not replacement and token not in ("{F}", "{L}", "{f}", "{l}"):
                return None   # required token is empty
            result = result.replace(token, replacement)
    # Remove any remaining unfilled tokens
    result = re.sub(r"\{[^}]+\}", "", result)
    # Sanitise: allow only valid email local-part chars
    result = re.sub(r"[^a-z0-9._+-]", "", result.lower())
    return result if result else None


async def _skrapp_lookup(
    client: httpx.AsyncClient,
    first: str,
    last: str,
    company: str,
) -> Optional[Dict[str, Any]]:
    """Skrapp's verified address for one person at a company, plus the domain
    row (domain, pattern, company metadata) it implies -- cached in SQLite."""
    found = await skrapp.find(client, first, last, company=company, company_data=True)
    if not found or found["quality"] != "valid":
        return None
    domain = found["email"].split("@", 1)[1]
    c = found.get("company") or {}
    metadata: Dict[str, Any] = {
        "organization":      c.get("name") or company,
        "company_type":      c.get("type"),
        "company_industry":  c.get("industry"),
        "company_country":   c.get("country"),
        "company_city":      c.get("city"),
        "company_state":     c.get("state"),
        "company_employees": str(c.get("size") or c.get("employees") or "") or None,
        "company_revenue":   None,
        "company_website":   f"https://{domain}",
        "company_linkedin":  c.get("linkedin"),
        "company_twitter":   c.get("twitter"),
        "company_founded":   c.get("founded"),
    }
    pattern = found.get("pattern") or ""
    if pattern:
        st.save_domain_pattern(domain, pattern, metadata)
    return {"email": found["email"], "domain": domain, "pattern": pattern, **metadata}


async def enrich_emails(
    leads: List[ScoredLead],
    min_confidence: int = _DEFAULT_MIN_CONFIDENCE,
) -> EnrichOutput:
    """
    Enrich scored leads with Skrapp-verified email addresses (one lookup per
    person; a 404 is not charged).
    """
    enriched: List[EnrichedLead] = []
    skipped: List[ScoredLead] = []

    async with httpx.AsyncClient() as client:
        for lead in leads:
            first, last = _split_name(lead.name)
            company = lead.company or ""

            if not first:
                skipped.append(lead)
                continue

            # 1. Skrapp: this person's verified address
            row = await _skrapp_lookup(client, first, last, company)
            if not row:
                skipped.append(lead)
                continue

            domain = row["domain"]
            pattern = row["pattern"]
            email = row["email"]
            email_status = "valid"   # Skrapp-verified

            # 4. Build enriched lead with all company metadata from the cached row
            enriched.append(
                EnrichedLead.from_scored(
                    lead,
                    first_name=first,
                    last_name=last,
                    email=email,
                    email_status=email_status,
                    email_pattern=pattern,
                    company_domain=domain,
                    company_website=row.get("company_website"),
                    company_linkedin=row.get("company_linkedin"),
                    company_twitter=row.get("company_twitter"),
                    company_type=row.get("company_type"),
                    company_country=row.get("company_country"),
                    company_city=row.get("company_city"),
                    company_state=row.get("company_state"),
                    company_employees=row.get("company_employees"),
                    company_location=_build_location(row),
                    added_on=_now_iso(),
                )
            )

    return EnrichOutput(enriched=enriched, skipped=skipped)


def _build_location(row: Dict[str, Any]) -> Optional[str]:
    parts = [row.get("company_city"), row.get("company_state"), row.get("company_country")]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else None


def _now_iso() -> str:
    from datetime import datetime
    return datetime.utcnow().isoformat()
