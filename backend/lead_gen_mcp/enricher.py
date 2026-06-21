"""
Hunter.io email enricher.

Flow per lead:
  1. If company domain is unknown → Hunter domain-search by company name
  2. email-finder with first name, last name, domain
  3. Return confidence + verification status

Leads below min_confidence are placed in `skipped`.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

import httpx

from .schemas import EnrichedLead, EnrichOutput, ScoredLead

HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")
HUNTER_BASE = "https://api.hunter.io/v2"

# Override per ICP via enrich_emails(min_confidence=N)
_DEFAULT_MIN_CONFIDENCE = 70


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
    website = website.lstrip("www.").split("/")[0]
    return website if "." in website else None


async def _domain_search(client: httpx.AsyncClient, company: str) -> Optional[str]:
    """Try Hunter domain-search by company name; return domain or None."""
    try:
        resp = await client.get(
            f"{HUNTER_BASE}/domain-search",
            params={"company": company, "api_key": HUNTER_API_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        domain = data.get("domain")
        return domain or None
    except Exception:
        return None


async def _email_finder(
    client: httpx.AsyncClient,
    first_name: str,
    last_name: str,
    domain: str,
) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """
    Call Hunter email-finder.
    Returns (email, confidence, verification_status).
    """
    try:
        resp = await client.get(
            f"{HUNTER_BASE}/email-finder",
            params={
                "domain": domain,
                "first_name": first_name,
                "last_name": last_name,
                "api_key": HUNTER_API_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        email = data.get("email")
        confidence = data.get("score")
        verification = data.get("verification", {}).get("status") if data.get("verification") else None
        return email, confidence, verification
    except Exception:
        return None, None, None


async def enrich_emails(
    leads: List[ScoredLead],
    min_confidence: int = _DEFAULT_MIN_CONFIDENCE,
) -> EnrichOutput:
    """
    Enrich a list of scored leads with Hunter.io.
    Returns enriched (with email) and skipped (below threshold or error).
    """
    enriched: List[EnrichedLead] = []
    skipped: List[ScoredLead] = []

    async with httpx.AsyncClient() as client:
        for lead in leads:
            first, last = _split_name(lead.name)
            company = lead.company or ""

            # 1. Resolve domain
            domain: Optional[str] = None
            if company:
                domain = await _domain_search(client, company)

            if not domain:
                skipped.append(lead)
                continue

            # 2. Find email
            if not first:
                skipped.append(lead)
                continue

            email, confidence, verification = await _email_finder(
                client, first, last, domain
            )

            if not email or (confidence is not None and confidence < min_confidence):
                skipped.append(lead)
                continue

            enriched.append(
                EnrichedLead.from_scored(
                    lead,
                    email=email,
                    hunter_confidence=confidence,
                    verification_status=verification,
                    domain=domain,
                )
            )

    return EnrichOutput(enriched=enriched, skipped=skipped)
