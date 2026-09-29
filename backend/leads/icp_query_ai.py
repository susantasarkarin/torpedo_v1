"""
AI-GENERATED ICP SEARCH QUERIES (local SLM)
===========================================

Replaces the template mix-and-match query builder with model-generated Google
queries, per ICP. The template builder in `scheduler.generate_search_queries`
is kept as an automatic fallback and is used whenever the local model is
unavailable or writes nothing on-topic (leads/query_variants_ai.py).

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

# Never ask the model for more than this in one shot, whatever the caller says.
MAX_QUERIES_PER_CALL = 25


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
                         allow_fallback: bool = True,
                         used: Optional[List[str]] = None) -> List[str]:
    """
    Generate search queries for one ICP via the local SLM, falling back to the
    template builder when it is unavailable or writes nothing usable.

    Args:
        icp: ICP config dict from icp_config.py
        count: how many queries to return
        leads_per_icp: scheduler's per-ICP daily counters, for budget enforcement
        allow_fallback: set False to disable the template fallback (tests)
        used: searches already run, which the model is told not to repeat

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

    # --- Local SLM path (Qwen; Bedrock is not used) ---------------------
    if os.getenv("DISABLE_AI_CALLS", "false").lower() != "true":
        from leads.query_variants_ai import fresh_batch
        try:
            queries = fresh_batch(icp, used or [], count=count)
        except Exception as e:  # never let query generation take down the loop
            logger.warning("icp=%s slm path errored: %s", slug, e)
            queries = None
        if queries:
            logger.info("icp=%s query generation path=slm generated=%d requested=%d",
                        slug, len(queries), count)
            return queries
        logger.warning("icp=%s slm %s", slug,
                       "unavailable" if queries is None else "returned no usable queries")
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
