"""
Hunter.io email enricher — pattern-based approach.

Flow per lead:
  1. Split name into first / last
  2. Resolve domain:
       a. Check domain_patterns table in SQLite (free, no API call)
       b. If not found → call Hunter domain-search, save pattern + company
          metadata for every future lead at this domain
  3. Apply the pattern to construct the email address
       e.g. pattern "{first}.{last}" + "Priya Sharma" → priya.sharma@nielsen.com
  4. Store email_pattern on the lead for audit

This means a single Hunter API call covers every future lead at the same
company — much more credit-efficient than calling email-finder per person.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .schemas import DomainPattern, EnrichedLead, EnrichOutput, ScoredLead
from . import state as st

HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")
HUNTER_BASE = "https://api.hunter.io/v2"

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


async def _hunter_domain_search(
    client: httpx.AsyncClient,
    company: str,
) -> Optional[Dict[str, Any]]:
    """
    Call Hunter domain-search by company name.
    Returns a dict with domain, pattern, and company metadata, or None on failure.
    """
    try:
        resp = await client.get(
            f"{HUNTER_BASE}/domain-search",
            params={"company": company, "api_key": HUNTER_API_KEY},
            timeout=12,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        domain = data.get("domain")
        pattern = data.get("pattern")
        if not domain or not pattern:
            return None

        # Extract company metadata Hunter returns alongside the pattern
        metadata: Dict[str, Any] = {
            "organization":       data.get("organization"),
            "company_type":       data.get("type"),
            "company_industry":   None,    # not in standard domain-search v2
            "company_country":    data.get("country"),
            "company_city":       data.get("city"),
            "company_state":      data.get("state"),
            "company_employees":  str(data.get("employees", "")) or None,
            "company_revenue":    None,
            "company_website":    f"https://{domain}",
            "company_linkedin":   data.get("linkedin"),
            "company_twitter":    data.get("twitter"),
            "company_founded":    None,
        }

        return {"domain": domain, "pattern": pattern, **metadata}
    except Exception:
        return None


async def _resolve_domain_and_pattern(
    client: httpx.AsyncClient,
    company: str,
    company_domain: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    1. If company_domain is known, check SQLite cache first.
    2. Otherwise try company name lookup via Hunter.
    Returns the full domain row dict (domain, pattern, metadata) or None.
    """
    # Check SQLite cache by domain if we already know it
    if company_domain:
        cached = st.get_domain_pattern(company_domain)
        if cached:
            return cached

    # Check by company name — derive domain from a prior Hunter call if available
    # (can't cache-lookup by company name directly, so skip to Hunter)
    if not company:
        return None

    result = await _hunter_domain_search(client, company)
    if not result:
        return None

    domain = result["domain"]
    pattern = result["pattern"]
    metadata = {k: v for k, v in result.items() if k not in ("domain", "pattern")}

    # Cache for future leads at the same domain
    st.save_domain_pattern(domain, pattern, metadata)
    return {"domain": domain, "pattern": pattern, **metadata}


async def enrich_emails(
    leads: List[ScoredLead],
    min_confidence: int = _DEFAULT_MIN_CONFIDENCE,
) -> EnrichOutput:
    """
    Enrich scored leads with emails constructed from Hunter.io domain patterns.

    One Hunter API call per *domain* (not per person) — the pattern is cached
    in SQLite and reused for every subsequent lead at the same company.
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

            # 1. Resolve domain + pattern (DB-first, Hunter fallback)
            row = await _resolve_domain_and_pattern(client, company)
            if not row:
                skipped.append(lead)
                continue

            domain = row["domain"]
            pattern = row["pattern"]

            # 2. Construct email from pattern
            local = apply_pattern(pattern, first, last)
            if not local:
                skipped.append(lead)
                continue

            email = f"{local}@{domain}"

            # 3. Derive email_status from domain type
            # Hunter "type" for the domain: "personal" | "generic" | "professional"
            # We don't call email-verifier here to save credits; mark as "constructed"
            email_status = "constructed"

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
