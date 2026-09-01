"""
AI-GENERATED ICP SEARCH QUERIES (Bedrock)
=========================================

Replaces the template mix-and-match query builder with model-generated Google
queries, per ICP. The template builder in `scheduler.generate_search_queries`
is kept as an automatic fallback and is used whenever the Bedrock call fails or
returns output that will not parse.

Two hard limits protect search credits:

1. Per-ICP daily budget (`daily_budget` on the ICP config, tracked in
   `scheduler_state.leads_per_icp`) caps how many queries we will even ask for.
   An ICP that has exhausted its budget generates nothing and costs nothing.
2. Generated queries are capped at `count`, deduplicated, and length-checked
   before they reach Google CSE.

Which path was used is logged at INFO on every call.
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Queries longer than this are almost always model rambling, not a search.
MAX_QUERY_CHARS = 300
# Never ask the model for more than this in one shot, whatever the caller says.
MAX_QUERIES_PER_CALL = 25


SYSTEM_PROMPT = (
    "You are a B2B lead-generation search strategist. You write Google search "
    "queries that surface LinkedIn profiles of specific decision-makers. "
    "You return only valid JSON."
)

USER_PROMPT = """Generate exactly {count} diverse Google search queries that will surface LinkedIn profiles of people matching this Ideal Customer Profile.

ICP: {name}
{description}

Job titles to target: {designations}
Industries: {industries}
Countries / regions: {countries}
Seniority levels: {seniorities}

Requirements for the queries:
- Most should use site:linkedin.com/in/ to target individual profiles.
- Vary the approach across the set: exact-title quotes, boolean OR groups of
  title synonyms, industry-qualified searches, and country-qualified searches.
- Use title synonyms and adjacent titles a real person might actually have,
  not only the literal titles listed above.
- Stay strictly inside the industries and countries listed. Do not introduce
  unrelated industries.
- Each query must be a single line, under 200 characters, ready to paste into
  Google.
- No duplicates, no numbering, no commentary.

Return JSON in exactly this shape:
{{"queries": ["query one", "query two"]}}"""


def _fmt(values: Optional[List[str]], fallback: str = "any") -> str:
    if not values:
        return fallback
    return ", ".join(str(v) for v in values if v)


def _clean_queries(raw: List[str], count: int) -> List[str]:
    """Deduplicate (case-insensitively), drop junk, and cap at `count`."""
    seen = set()
    cleaned = []
    for query in raw:
        q = " ".join(str(query).split())
        if not q or len(q) > MAX_QUERY_CHARS:
            continue
        marker = q.lower()
        if marker in seen:
            continue
        seen.add(marker)
        cleaned.append(q)
        if len(cleaned) >= count:
            break
    return cleaned


def remaining_daily_budget(icp: Dict[str, Any],
                           leads_per_icp: Optional[Dict[str, int]] = None) -> int:
    """
    How much of this ICP's daily budget is left. Returns 0 when exhausted, which
    callers treat as "generate nothing".
    """
    budget = icp.get("daily_budget")
    if budget is None:
        return MAX_QUERIES_PER_CALL
    try:
        budget = int(budget)
    except (TypeError, ValueError):
        return MAX_QUERIES_PER_CALL
    used = int((leads_per_icp or {}).get(icp.get("slug", ""), 0) or 0)
    return max(0, budget - used)


def generate_icp_queries(icp: Dict[str, Any], count: int = 10,
                         leads_per_icp: Optional[Dict[str, int]] = None,
                         allow_fallback: bool = True) -> List[str]:
    """
    Generate search queries for one ICP via Bedrock, falling back to the
    template builder on any failure.

    Args:
        icp: ICP config dict from icp_config.py
        count: how many queries to return
        leads_per_icp: scheduler's per-ICP daily counters, for budget enforcement
        allow_fallback: set False to disable the template fallback (tests)

    Returns:
        List of query strings. May be empty if the ICP is over budget.
    """
    slug = icp.get("slug", "unknown")

    # --- Hard cap 1: per-ICP daily budget -------------------------------
    remaining = remaining_daily_budget(icp, leads_per_icp)
    if remaining <= 0:
        logger.info("icp=%s query generation skipped: daily budget exhausted", slug)
        return []

    count = max(1, min(count, remaining, MAX_QUERIES_PER_CALL))

    # --- Bedrock path ----------------------------------------------------
    if os.getenv("DISABLE_AI_CALLS", "false").lower() != "true":
        from leads.bedrock_client import BedrockError, JSONParseError, converse_string_list

        prompt = USER_PROMPT.format(
            count=count,
            name=icp.get("name", slug),
            description=icp.get("description", ""),
            designations=_fmt(icp.get("designations")),
            industries=_fmt(icp.get("industries")),
            countries=_fmt(icp.get("countries"), "global"),
            seniorities=_fmt(icp.get("seniority_levels")),
        )

        try:
            raw = converse_string_list(
                role="cheap",
                system=SYSTEM_PROMPT,
                user=prompt,
                key="queries",
                max_tokens=1024,
                temperature=0.7,  # variety is the point for query planning
            )
            if raw:
                queries = _clean_queries(raw, count)
                if queries:
                    logger.info(
                        "icp=%s query generation path=bedrock generated=%d requested=%d",
                        slug, len(queries), count)
                    return queries
                logger.warning("icp=%s bedrock returned no usable queries", slug)
            else:
                logger.warning("icp=%s bedrock output did not parse", slug)
        except (BedrockError, JSONParseError) as e:
            logger.warning("icp=%s bedrock call failed: %s", slug, e)
        except Exception as e:  # never let query generation take down the loop
            logger.warning("icp=%s bedrock path errored: %s", slug, e)
    else:
        logger.info("icp=%s AI disabled by DISABLE_AI_CALLS", slug)

    # --- Template fallback ------------------------------------------------
    if not allow_fallback:
        logger.info("icp=%s fallback disabled, returning nothing", slug)
        return []

    from leads.scheduler import generate_search_queries

    config = {
        "designations": icp.get("designations", []),
        "countries": icp.get("countries", []),
        "seniorities": icp.get("seniority_levels", []),
        "custom_query": icp.get("custom_context", ""),
        "industries": icp.get("industries", []),
    }
    queries = generate_search_queries(config, count)
    logger.info("icp=%s query generation path=template generated=%d requested=%d",
                slug, len(queries), count)
    return queries
