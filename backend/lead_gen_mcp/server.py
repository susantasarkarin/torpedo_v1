"""
Adaptive Lead-Generation Pipeline — FastMCP Server.

Run:
    python -m backend.lead_gen_mcp.server
    # or from repo root:
    uvicorn backend.lead_gen_mcp.server:mcp.app --port 9000

Tools exposed:
    define_icp
    propose_queries
    run_search_batch
    score_and_dedup
    enrich_emails
    push_to_crm
    update_agent_state
    ingest_triggers
    get_pipeline_stats
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from .schemas import (
    EnrichedLead,
    ICPDefinition,
    PipelineStats,
    QueryOutcome,
    ScoredLead,
    SERPResult,
    TriggerEvent,
)
from . import state as st
from .search import run_search_batch as _run_search
from .scorer import score_and_dedup as _score_dedup, extract_title_synonyms
from .enricher import enrich_emails as _enrich
from .crm_writer import push_to_crm as _push_crm
from .query_agent import propose_queries as _propose, learn_synonyms_from_results

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP(name="lead-gen-pipeline", version="1.0.0")


# ---------------------------------------------------------------------------
# 1. define_icp
# ---------------------------------------------------------------------------

@mcp.tool()
async def define_icp(
    name: str,
    icp_id: str,
    target_titles: List[str],
    target_industries: List[str],
    target_geos: List[str],
    company_size_band: Optional[str] = None,
    exclusion_rules: Optional[Dict[str, Any]] = None,
    min_hunter_confidence: int = 70,
    daily_query_budget: int = 100,
) -> Dict[str, Any]:
    """
    Create or update an ICP definition in the pipeline state store.

    Args:
        name:                  Human-readable ICP name
        icp_id:                Unique slug, e.g. "survey_fieldwork"
        target_titles:         List of job title patterns to target
        target_industries:     List of industry keywords
        target_geos:           List of countries / regions
        company_size_band:     Optional e.g. "50-500"
        exclusion_rules:       Optional dict — keys: excluded_companies,
                               excluded_titles, min_icp_score
        min_hunter_confidence: Minimum Hunter.io confidence (0-100)
        daily_query_budget:    Max Google CSE queries per day for this ICP
    """
    st.upsert_icp(
        icp_id=icp_id,
        name=name,
        target_titles=target_titles,
        target_industries=target_industries,
        target_geos=target_geos,
        company_size_band=company_size_band,
        exclusion_rules=exclusion_rules,
        min_hunter_conf=min_hunter_confidence,
        daily_query_budget=daily_query_budget,
    )
    return {"status": "ok", "icp_id": icp_id, "name": name}


# ---------------------------------------------------------------------------
# 2. propose_queries
# ---------------------------------------------------------------------------

@mcp.tool()
async def propose_queries(
    icp_id: str,
    batch_size: int = 20,
) -> Dict[str, Any]:
    """
    Ask the Claude query agent to generate a fresh batch of Google search
    queries for the given ICP, informed by yield history and the coverage matrix.

    Returns a list of {query, dimension_cell, rationale}.
    """
    icp_data = st.get_icp(icp_id)
    if not icp_data:
        return {"error": f"ICP '{icp_id}' not found. Call define_icp first."}

    icp = ICPDefinition(
        icp_id=icp_data["icp_id"],
        name=icp_data["name"],
        target_titles=icp_data["target_titles"],
        target_industries=icp_data["target_industries"],
        target_geos=icp_data["target_geos"],
        company_size_band=icp_data.get("company_size_band"),
        exclusion_rules=icp_data.get("exclusion_rules", {}),
        min_hunter_confidence=icp_data.get("min_hunter_conf", 70),
        daily_query_budget=icp_data.get("daily_query_budget", 100),
    )

    proposals = await _propose(icp, batch_size=batch_size)
    return {
        "icp_id": icp_id,
        "count": len(proposals),
        "queries": [p.model_dump() for p in proposals],
    }


# ---------------------------------------------------------------------------
# 3. run_search_batch
# ---------------------------------------------------------------------------

@mcp.tool()
async def run_search_batch(
    queries: List[str],
    icp_id: Optional[str] = None,
    pages_per_query: int = 1,
    recency_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a batch of GCSE queries against site:linkedin.com/in/.

    Args:
        queries:          List of raw query strings
        icp_id:           Optional — used to enforce per-ICP daily budget
        pages_per_query:  Pages to fetch per query (1 page = ~10 results, max 10)
        recency_filter:   "week" | "month" | "day" | None
    """
    budget_remaining: Optional[int] = None
    if icp_id:
        icp_data = st.get_icp(icp_id)
        if icp_data:
            used = st.daily_queries_used(icp_id)
            budget_remaining = max(0, icp_data["daily_query_budget"] - used)

    results = await _run_search(
        queries=queries,
        pages_per_query=pages_per_query,
        recency_filter=recency_filter,
        per_icp_daily_remaining=budget_remaining,
    )
    return {
        "batches": [r.model_dump() for r in results],
        "total_results": sum(len(r.results) for r in results),
        "total_quota": sum(r.quota_consumed for r in results),
    }


# ---------------------------------------------------------------------------
# 4. score_and_dedup
# ---------------------------------------------------------------------------

@mcp.tool()
async def score_and_dedup(
    results: List[Dict[str, Any]],
    icp_id: str,
) -> Dict[str, Any]:
    """
    Score SERP results against an ICP and deduplicate against pipeline history.

    `results` is a flat list of SERPResult dicts (profile_url is required).
    Returns accepted (ScoredLead), rejected_dupes, rejected_low_score.
    """
    icp_data = st.get_icp(icp_id)
    if not icp_data:
        return {"error": f"ICP '{icp_id}' not found."}

    icp = ICPDefinition(**{
        "icp_id": icp_data["icp_id"],
        "name": icp_data["name"],
        "target_titles": icp_data["target_titles"],
        "target_industries": icp_data["target_industries"],
        "target_geos": icp_data["target_geos"],
        "company_size_band": icp_data.get("company_size_band"),
        "exclusion_rules": icp_data.get("exclusion_rules", {}),
        "min_hunter_confidence": icp_data.get("min_hunter_conf", 70),
        "daily_query_budget": icp_data.get("daily_query_budget", 100),
    })

    serp_results = [SERPResult(**r) for r in results]
    output = _score_dedup(serp_results, icp)

    # Persist accepted leads to SQLite
    for lead in output.accepted:
        st.upsert_lead({**lead.model_dump(), "status": "scored"})

    # Discover synonym titles from all results
    discovered = extract_title_synonyms(serp_results, icp)
    learn_synonyms_from_results(icp, discovered)

    return {
        "accepted": [l.model_dump() for l in output.accepted],
        "rejected_dupes": [r.model_dump() for r in output.rejected_dupes],
        "rejected_low_score": [r.model_dump() for r in output.rejected_low_score],
        "counts": {
            "accepted": len(output.accepted),
            "rejected_dupes": len(output.rejected_dupes),
            "rejected_low_score": len(output.rejected_low_score),
        },
    }


# ---------------------------------------------------------------------------
# 5. enrich_emails
# ---------------------------------------------------------------------------

@mcp.tool()
async def enrich_emails(
    leads: List[Dict[str, Any]],
    min_confidence: int = 70,
) -> Dict[str, Any]:
    """
    Enrich a list of ScoredLead dicts with Hunter.io emails.

    Leads below `min_confidence` or with no discoverable domain are placed in skipped.
    """
    scored = [ScoredLead(**l) for l in leads]
    output = await _enrich(scored, min_confidence=min_confidence)

    # Persist enriched status
    for lead in output.enriched:
        st.upsert_lead({**lead.model_dump(), "status": "enriched"})

    return {
        "enriched": [l.model_dump() for l in output.enriched],
        "skipped": [l.model_dump() for l in output.skipped],
        "counts": {
            "enriched": len(output.enriched),
            "skipped": len(output.skipped),
        },
    }


# ---------------------------------------------------------------------------
# 6. push_to_crm
# ---------------------------------------------------------------------------

@mcp.tool()
async def push_to_crm(
    leads: List[Dict[str, Any]],
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Push enriched leads to the in-house CRM via /api/crm/contacts.

    Idempotent: contacts are keyed by SHA-256(profile_url) stored in customFields.
    One bad write never kills the batch.
    """
    if run_id is None:
        run_id = uuid.uuid4().hex[:12]

    enriched = [EnrichedLead(**l) for l in leads]
    output = await _push_crm(enriched, run_id=run_id)
    return output.model_dump()


# ---------------------------------------------------------------------------
# 7. update_agent_state
# ---------------------------------------------------------------------------

@mcp.tool()
async def update_agent_state(
    icp_id: str,
    query_outcomes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Persist per-query yield metrics after a search cycle.

    Each outcome: {query, dimension_cell, results_count, novel_count,
                   icp_passing, enriched_count, pushed_count}

    Also updates the coverage matrix (marks exhausted cells when yield collapses).
    """
    icp_data = st.get_icp(icp_id)
    if not icp_data:
        return {"error": f"ICP '{icp_id}' not found."}

    for outcome in query_outcomes:
        q = QueryOutcome(icp_id=icp_id, **outcome)
        st.log_query(
            icp_id=icp_id,
            query_text=q.query,
            dimension_cell=q.dimension_cell,
            result_count=q.results_count,
            novel_count=q.novel_count,
            icp_passing=q.icp_passing,
            enriched_count=q.enriched_count,
            pushed_count=q.pushed_count,
        )
        st.record_coverage_attempt(
            icp_id=icp_id,
            dimension_cell=q.dimension_cell,
            novel_count=q.novel_count,
        )

    return {"status": "ok", "logged": len(query_outcomes)}


# ---------------------------------------------------------------------------
# 8. ingest_triggers
# ---------------------------------------------------------------------------

@mcp.tool()
async def ingest_triggers(
    events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Ingest company-level trigger events into the trigger queue.

    Each event: {company_name, event_type, description?, icp_id?}
    event_type: "funding" | "hiring" | "leadership_change" | "other"

    Triggers are injected as priority queries at the start of the next
    propose_queries cycle.
    """
    inserted = 0
    for e in events:
        try:
            event = TriggerEvent(**e)
            st.ingest_trigger(
                company_name=event.company_name,
                event_type=event.event_type,
                description=event.description,
                icp_id=event.icp_id,
            )
            inserted += 1
        except Exception as exc:
            logger.warning("Failed to ingest trigger %s: %s", e, exc)

    return {"status": "ok", "inserted": inserted}


# ---------------------------------------------------------------------------
# 9. get_pipeline_stats
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_pipeline_stats(
    icp_id: str,
    since: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Return pipeline health metrics for an ICP.

    Args:
        icp_id: ICP slug
        since:  ISO timestamp to filter from (optional)
    """
    icp_data = st.get_icp(icp_id)
    if not icp_data:
        return {"error": f"ICP '{icp_id}' not found."}

    lead_counts = st.get_lead_counts(icp_id)
    stats = PipelineStats(
        icp_id=icp_id,
        queries_run=st.queries_run_count(icp_id),
        profiles_seen=st.profiles_seen_count(icp_id),
        leads_enriched=lead_counts.get("enriched", 0),
        leads_pushed=lead_counts.get("pushed", 0),
        yield_curve=st.get_yield_curve(icp_id),
    )
    return stats.model_dump()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
