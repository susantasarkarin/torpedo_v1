"""
COMPANY WEB-SEARCH ENRICHMENT (Claude-backed)
=============================================
Drop-in replacement for the retired OpenAI-based module (now in
backend/deprecated/ai_workflows/web_search_enrichment.py), rebuilt on the
governed Claude gateway (web_search tool + JSON extraction).

Three consumers import from here and were ALL silently broken while this
module was missing (per-call ImportError, swallowed as "no data"):

  - background_job_scheduler.background_enrich_leads  -> enrich_company_with_websearch
  - routers/operations.py (Potential Clients UI)      -> all helpers below
  - tasks/enrichment_tasks.py (Celery)                -> enrich / get_unenriched_companies

Storage is unchanged for backward compatibility with existing data and the
operations UI: enriched records upsert into
email_automation.potential_client_leads (keyed by case-insensitive company
name) and every attempt is logged to email_automation.lead_enrichment_logs.
"""

import logging
import os
import re
import time
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ENRICHED_LEADS_COLLECTION = "potential_client_leads"
ENRICHMENT_CACHE_TTL_DAYS = int(os.getenv("ENRICHMENT_CACHE_TTL_DAYS", "30"))

# Same stored shape as the retired module, so existing records and the
# Potential Clients UI keep working unchanged.
LEAD_FIELD_SCHEMA = {
    # Lead Information
    "lead_stage": "Prospect",
    "email": None,
    "lead_name": None,
    "linkedin_url": None,
    "title": None,
    "company": None,
    "location": None,
    "lead_source": "Cint API client list",
    "email_status": None,
    "seniority_level": None,
    "department": None,
    "persona": None,
    "buying_role": None,
    # Company Details
    "company_founded": None,
    "company_headquarters": None,
    "company_linkedin_url": None,
    "company_employee_count_range": None,
    "company_industry": None,
    "company_size": None,
    "company_type": None,
    "company_revenue_range": None,
    "company_domain": None,
    "company_website": None,
    # Citations (2026-08-28: previously nothing was recorded, so a
    # produced address could never be checked against what the model
    # actually saw — see HALT_AND_VERIFY_PLAN_2026-08-28.md Part 2)
    "email_source_url": None,
    "company_domain_source_url": None,
    # Metadata
    "enriched_at": None,
    "enrichment_source": "claude_websearch",
}

_EXTRACTION_PROMPT = """From the research notes below, extract structured company/lead data.

Company searched: {company}
Sources available (cite one of these URLs for company_domain and email, or
use null for either field if none of these sources actually state it):
{sources_list}

Research notes:
{answer}

Return ONLY valid JSON with exactly this shape (use null when unknown, never
invent — a plausible-looking value with no source is worse than null):
{{
  "lead_information": {{
    "lead_name": "<key decision-maker full name or null>",
    "title": "<their job title or null>",
    "linkedin_url": "<their LinkedIn profile URL or null>",
    "email": "<verified contact email or null — ONLY if literally present in the research notes>",
    "email_source_url": "<the exact URL from the sources list where this email appears, or null>",
    "location": "<lead's location or null>",
    "seniority_level": "<C-Level|VP|Director|Manager or null>",
    "department": "<Sales|Marketing|Operations|Research or null>"
  }},
  "company_details": {{
    "company_domain": "<primary website domain, e.g. acme.com — ONLY if stated or directly visible in a source URL>",
    "company_domain_source_url": "<the exact URL from the sources list that supports this domain, or null>",
    "company_website": "<https URL or null>",
    "company_headquarters": "<city, country or null>",
    "company_founded": "<year or null>",
    "company_linkedin_url": "<company LinkedIn URL or null>",
    "company_employee_count_range": "<e.g. 51-200 or null>",
    "company_industry": "<primary industry or null>",
    "company_size": "<Small|Medium|Large|Enterprise or null>",
    "company_type": "<e.g. Market Research, Agency, Panel Provider or null>",
    "company_revenue_range": "<e.g. $10M-$50M or null>"
  }},
  "confidence_score": <0.0-1.0 completeness of the data>,
  "summary": "<2 sentence company summary>"
}}"""


# ============== STORAGE ==============

def _db():
    try:
        from db_pools import get_db
    except ImportError:
        from backend.db_pools import get_db
    return get_db("email_automation")


def get_db_connection():
    """Enriched leads collection (name kept from the retired module)."""
    return _db()[ENRICHED_LEADS_COLLECTION]


def get_enrichment_logs_collection():
    return _db()["lead_enrichment_logs"]


def _domain_is_real(domain: str) -> bool:
    """
    True if `domain` has MX or A/AAAA records, i.e. could plausibly receive
    mail. Fails open (returns True) if dnspython isn't installed, so a
    missing dependency degrades to "no check" rather than dropping every
    domain.
    """
    try:
        try:
            from app.services.outreach.email_validator import EmailValidator
        except ImportError:
            from backend.app.services.outreach.email_validator import EmailValidator
        return EmailValidator(_db()).domain_exists(domain)
    except Exception as e:
        logger.debug(f"[Enrichment] domain existence check skipped: {e}")
        return True


def _log_attempt(company: str, success: bool, latency_ms: int,
                 error: Optional[str] = None) -> None:
    try:
        get_enrichment_logs_collection().insert_one({
            "company": company,
            "success": success,
            "error": error,
            "latency_ms": latency_ms,
            "source": "claude_websearch",
            "timestamp": datetime.utcnow(),
        })
    except Exception as e:
        logger.debug(f"[Enrichment] log write failed: {e}")


# ============== CORE ENRICHMENT ==============

def enrich_company_with_websearch(
    company_name: str,
    additional_context: Optional[str] = None,
    force_refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Research a company via Claude web search; upsert + return the enriched
    record. Returns None when nothing useful was found (callers fall back to
    email-pattern-only handling).
    """
    company_name = (company_name or "").strip()
    if not company_name or len(company_name) < 2:
        return {"company": company_name, "success": False,
                "error": "company name too short"}
    start_time = time.time()
    collection = get_db_connection()

    # Cache: reuse a recent record for the same company.
    if not force_refresh:
        try:
            cached = collection.find_one({
                "company": {"$regex": f"^{re.escape(company_name)}$",
                            "$options": "i"},
                "enriched_at": {"$gte": datetime.utcnow()
                                - timedelta(days=ENRICHMENT_CACHE_TTL_DAYS)},
            })
            if cached:
                cached["_id"] = str(cached["_id"])
                cached["from_cache"] = True
                return cached
        except Exception as e:
            logger.debug(f"[Enrichment] cache lookup failed: {e}")

    try:
        try:
            from ai_governance.claude_gateway import get_claude_gateway
        except ImportError:
            from backend.ai_governance.claude_gateway import get_claude_gateway
        gateway = get_claude_gateway()

        query = (f"Company research: '{company_name}'. Find their official "
                 f"website/domain, industry, headquarters, founding year, "
                 f"employee count range, company type, revenue range, and a "
                 f"key operations/partnerships decision-maker (name, title, "
                 f"LinkedIn).")
        if additional_context:
            query += f" Known context: {additional_context}"
        search = gateway.web_search(query, num_results=5,
                                    caller="lead_enrichment")
        answer = (search or {}).get("answer", "")
        source_urls = [s["url"] for s in (search or {}).get("sources", []) if s.get("url")]
        if not answer:
            _log_attempt(company_name, False,
                         int((time.time() - start_time) * 1000), "empty_search")
            return {"company": company_name, "success": False,
                    "error": "web search returned no data"}

        sources_list = "\n".join(f"- {u}" for u in source_urls) or "(none retrieved)"
        parsed = gateway.generate_json(
            _EXTRACTION_PROMPT.format(company=company_name,
                                      answer=answer[:6000],
                                      sources_list=sources_list),
            task_type="enrichment", caller="lead_enrichment")
        if not isinstance(parsed, dict):
            _log_attempt(company_name, False,
                         int((time.time() - start_time) * 1000), "parse_failed")
            return {"company": company_name, "success": False,
                    "error": "could not parse enrichment response"}

        enriched_record = {
            **LEAD_FIELD_SCHEMA,
            "company": company_name,
            "enriched_at": datetime.utcnow(),
            "enrichment_source": "claude_websearch",
            "from_cache": False,
            "success": True,
        }
        for section in ("lead_information", "company_details"):
            for key, value in (parsed.get(section) or {}).items():
                if key in enriched_record and value and value != "Unknown":
                    enriched_record[key] = value

        # Enforce the citation requirement server-side — don't just trust
        # the model followed the prompt. An email or domain whose cited
        # source_url isn't one of the URLs the web_search tool actually
        # retrieved gets nulled out rather than kept. This is the concrete
        # form of "return null rather than a constructed guess when it
        # can't cite one" — a prompt instruction alone is not a guarantee.
        email_src = enriched_record.get("email_source_url")
        if enriched_record.get("email") and email_src not in source_urls:
            logger.info(f"[Enrichment] Dropping uncited email for '{company_name}' "
                        f"(claimed source {email_src!r} not in retrieved results)")
            enriched_record["email"] = None
            enriched_record["email_source_url"] = None

        domain_src = enriched_record.get("company_domain_source_url")
        if enriched_record.get("company_domain") and domain_src not in source_urls:
            logger.info(f"[Enrichment] Dropping uncited company_domain for '{company_name}' "
                        f"(claimed source {domain_src!r} not in retrieved results)")
            enriched_record["company_domain"] = None
            enriched_record["company_domain_source_url"] = None
        # Normalise the domain (strip scheme/www/path).
        dom = enriched_record.get("company_domain") or ""
        if dom:
            dom = re.sub(r"^https?://", "", str(dom)).split("/")[0]
            dom = dom.removeprefix("www.").lower()
            # The model sometimes fabricates a domain from the company name
            # (e.g. turns a job-title snippet into
            # "pwcwithadegreeininformationsystemsand.com"). A domain that
            # doesn't resolve at all can never receive mail, so don't let a
            # fabricated one flow into email prediction downstream — drop it
            # and let this enrichment be retried/flagged instead of quietly
            # producing a guaranteed-bounce email.
            if _domain_is_real(dom):
                enriched_record["company_domain"] = dom
            else:
                logger.warning(
                    f"[Enrichment] Discarding fabricated/non-resolving "
                    f"company_domain '{dom}' for '{company_name}'")
                enriched_record["company_domain"] = None
                enriched_record["company_domain_rejected"] = dom
        enriched_record["confidence_score"] = float(parsed.get("confidence_score") or 0)
        enriched_record["summary"] = parsed.get("summary", "")
        # Alias for consumers that read company_employee_count (scheduler merge)
        enriched_record["company_employee_count"] = \
            enriched_record.get("company_employee_count_range")
        # company_name alias expected by the background enrichment merge.
        enriched_record["company_name"] = company_name

        # Useless result (no domain and no industry) → treat as a miss.
        if not enriched_record["company_domain"] \
                and not enriched_record["company_industry"]:
            _log_attempt(company_name, False,
                         int((time.time() - start_time) * 1000), "no_data")
            return {"company": company_name, "success": False,
                    "error": "no verifiable company data found"}

        collection.update_one(
            {"company": {"$regex": f"^{re.escape(company_name)}$",
                         "$options": "i"}},
            {"$set": enriched_record},
            upsert=True,
        )
        _log_attempt(company_name, True,
                     int((time.time() - start_time) * 1000))
        return enriched_record
    except Exception as e:
        logger.warning(f"[Enrichment] Claude web-search enrichment failed "
                       f"for '{company_name}': {e}")
        _log_attempt(company_name, False,
                     int((time.time() - start_time) * 1000), str(e))
        return {"company": company_name, "success": False, "error": str(e)}


# ============== HELPERS (same contracts as the retired module) ==============

def batch_enrich_companies(company_names: List[str],
                           delay_between_requests: float = 2.0
                           ) -> List[Dict[str, Any]]:
    """Enrich multiple companies sequentially with a small delay."""
    results = []
    for i, company in enumerate(company_names):
        logger.info(f"Enriching company {i + 1}/{len(company_names)}: {company}")
        results.append(enrich_company_with_websearch(company))
        if i < len(company_names) - 1:
            time.sleep(delay_between_requests)
    return results


def get_enriched_lead(company_name: str) -> Optional[Dict[str, Any]]:
    """Get an existing enriched record by company name (case-insensitive)."""
    record = get_db_connection().find_one({
        "company": {"$regex": f"^{re.escape(company_name)}$", "$options": "i"}
    })
    if record:
        record["_id"] = str(record["_id"])
        return record
    return None


def get_all_enriched_leads(limit: int = 100, skip: int = 0,
                           min_confidence: float = 0.0) -> List[Dict[str, Any]]:
    """Paginated enriched records, newest first."""
    query: Dict[str, Any] = {}
    if min_confidence > 0:
        query["confidence_score"] = {"$gte": min_confidence}
    records = list(get_db_connection().find(query)
                   .sort("enriched_at", -1).skip(skip).limit(limit))
    for record in records:
        record["_id"] = str(record["_id"])
    return records


def get_unenriched_companies(known_companies: List[str]) -> List[str]:
    """Subset of known_companies with no fresh enrichment record."""
    cursor = get_db_connection().find(
        {"enriched_at": {"$gte": datetime.utcnow()
                         - timedelta(days=ENRICHMENT_CACHE_TTL_DAYS)}},
        {"company": 1})
    enriched_names = {(doc.get("company") or "").lower() for doc in cursor}
    return [c for c in known_companies if c and c.lower() not in enriched_names]


def get_enrichment_stats() -> Dict[str, Any]:
    """Aggregate stats for the enrichment dashboard."""
    collection = get_db_connection()
    logs_collection = get_enrichment_logs_collection()
    yesterday = datetime.utcnow() - timedelta(hours=24)
    return {
        "total_enriched": collection.count_documents({}),
        "high_confidence_count": collection.count_documents(
            {"confidence_score": {"$gte": 0.7}}),
        "enrichments_last_24h": logs_collection.count_documents(
            {"timestamp": {"$gte": yesterday}, "success": True}),
        "failures_last_24h": logs_collection.count_documents(
            {"timestamp": {"$gte": yesterday}, "success": False}),
        "cache_ttl_days": ENRICHMENT_CACHE_TTL_DAYS,
    }


async def auto_enrich_new_companies(company_names: List[str]) -> Dict[str, Any]:
    """Async wrapper: enrich only companies without a fresh record."""
    unenriched = get_unenriched_companies(company_names)
    if not unenriched:
        logger.info("No new companies to enrich")
        return {"enriched": 0, "total": len(company_names)}
    logger.info(f"Auto-enriching {len(unenriched)} new companies")
    enriched = 0
    for company in unenriched:
        result = await asyncio.to_thread(enrich_company_with_websearch, company)
        if result and result.get("success") and not result.get("error"):
            enriched += 1
        await asyncio.sleep(2)
    return {"enriched": enriched, "total": len(company_names)}
