"""
Claude Sonnet query agent.

On each cycle, the agent reads:
  - ICP definition (titles, industries, geos, size band)
  - Recent query history (last 200 queries) with yield metrics
  - Coverage matrix (dimension cells + exhaustion flags)
  - Active synonym pool
  - Pending trigger events

It outputs a batch of ~20 queries, each with a dimension_cell and rationale.

Behaviors enforced via prompt:
  - High-yield cells → generate adjacent variants
  - Low-yield / high-dupe cells → prune, pivot dimension
  - Exhausted dimensions → force-rotate to unexplored cell
  - Triggered company events get priority slots in each batch
  - Synonym expansion: if "VP Sales" surfaces "Head of GTM", add to pool

All LLM calls are logged to state.queries (rationale field) so yield collapse
is diagnosable from the query log.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import anthropic

from .schemas import ICPDefinition, QueryProposal
from . import state as st

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 4096

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


_SYSTEM = """You are an expert B2B lead-generation strategist.
Your job is to generate Google search queries that find LinkedIn profiles
matching a defined Ideal Customer Profile (ICP).

Rules:
- Every query MUST start with: site:linkedin.com/in/
- Use quoted phrases for exact matching where helpful
- Mix title, industry, and geo dimensions for coverage
- Prioritise dimension cells with no prior queries (unexplored)
- Do NOT repeat queries from the history
- Exhausted cells (low novel yield across ≥3 attempts) must be skipped
- If trigger events are present, prepend 1-3 company-specific queries per event
- When a SERP title seen in history contains a job title NOT in the ICP's
  target_titles, infer it as a synonym and use it in at least one query

Output: a JSON object with a "queries" array.
Each element has: { "query": "...", "dimension_cell": "title|industry|geo", "rationale": "..." }
"""


def _build_user_prompt(
    icp: ICPDefinition,
    history: List[Dict[str, Any]],
    coverage: List[Dict[str, Any]],
    synonyms: List[Dict[str, Any]],
    triggers: List[Dict[str, Any]],
    batch_size: int,
) -> str:
    exhausted = [c["dimension_cell"] for c in coverage if c.get("exhausted")]
    high_yield = [
        c["dimension_cell"]
        for c in coverage
        if not c.get("exhausted") and c.get("novel_total", 0) > 0
        and c.get("attempts", 1) > 0
        and (c["novel_total"] / c["attempts"]) >= 2
    ]
    recent_queries = [h["query_text"] for h in history[:50]]
    synonym_titles = [s["synonym"] for s in synonyms if s["dimension"] == "title"]

    return f"""
ICP: {icp.name}
Target titles: {icp.target_titles + synonym_titles}
Target industries: {icp.target_industries}
Target geos: {icp.target_geos}
Company size: {icp.company_size_band or 'any'}

Recent queries (do NOT repeat):
{json.dumps(recent_queries, indent=2)}

Coverage matrix:
{json.dumps(coverage, indent=2)}

Exhausted cells (skip these): {exhausted}
High-yield cells (generate variants): {high_yield}

Synonym pool (use these titles too): {synonym_titles}

Pending trigger events (prioritise with company-specific queries):
{json.dumps([{k: t[k] for k in ("company_name", "event_type", "description") if k in t} for t in triggers], indent=2)}

Generate {batch_size} diverse queries.
Return JSON: {{ "queries": [ {{ "query": "...", "dimension_cell": "...", "rationale": "..." }}, ... ] }}
""".strip()


async def propose_queries(
    icp: ICPDefinition,
    batch_size: int = 20,
) -> List[QueryProposal]:
    """
    Ask Claude to propose a fresh batch of search queries for the given ICP.
    Returns a list of QueryProposal objects.
    """
    history = st.get_query_history(icp.icp_id, limit=200)
    coverage = st.get_coverage_matrix(icp.icp_id)
    synonyms = st.get_synonyms(icp.icp_id)
    triggers = st.pop_pending_triggers(icp_id=icp.icp_id, limit=5)

    user_prompt = _build_user_prompt(
        icp, history, coverage, synonyms, triggers, batch_size
    )

    logger.info(
        "QueryAgent.propose_queries icp=%s batch=%d triggers=%d",
        icp.icp_id, batch_size, len(triggers),
    )

    try:
        response = _get_client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
        logger.debug("QueryAgent raw response: %s", raw[:500])
    except Exception as exc:
        logger.error("QueryAgent LLM call failed: %s", exc)
        return _fallback_queries(icp, batch_size)

    proposals = _parse_proposals(raw)
    if not proposals:
        logger.warning("QueryAgent returned no parseable proposals; using fallback")
        proposals = _fallback_queries(icp, batch_size)

    return proposals


def _parse_proposals(raw: str) -> List[QueryProposal]:
    """Extract and validate the JSON array from the LLM response."""
    # Tolerate markdown code fences
    text = raw.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            if "{" in part:
                text = part.lstrip("json").strip()
                break

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract first JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
            except Exception:
                return []
        else:
            return []

    queries_raw = data.get("queries", [])
    proposals = []
    for item in queries_raw:
        q = item.get("query", "").strip()
        if not q:
            continue
        proposals.append(
            QueryProposal(
                query=q,
                dimension_cell=item.get("dimension_cell", "general"),
                rationale=item.get("rationale", ""),
            )
        )
    return proposals


def _fallback_queries(icp: ICPDefinition, batch_size: int) -> List[QueryProposal]:
    """
    Deterministic fallback when the LLM call fails.
    Generates simple cross-product of title × geo queries.
    """
    proposals = []
    titles = icp.target_titles[:4] or ["manager"]
    geos = icp.target_geos[:3] or [""]
    industries = icp.target_industries[:2] or [""]

    for title in titles:
        for geo in geos:
            for industry in industries:
                q_parts = [f'site:linkedin.com/in/ "{title}"']
                if industry:
                    q_parts.append(f'"{industry}"')
                if geo:
                    q_parts.append(f'"{geo}"')
                proposals.append(
                    QueryProposal(
                        query=" ".join(q_parts),
                        dimension_cell=f"{title.lower().replace(' ', '_')}|{industry.lower()}|{geo.lower()}",
                        rationale="fallback: LLM unavailable",
                    )
                )
                if len(proposals) >= batch_size:
                    return proposals

    return proposals[:batch_size]


def learn_synonyms_from_results(
    icp: ICPDefinition,
    discovered_titles: List[str],
) -> None:
    """
    Persist newly discovered title synonyms to the state store.
    `discovered_titles` comes from scorer.extract_title_synonyms().
    """
    known = {t.lower() for t in icp.target_titles}
    for title in discovered_titles:
        if title.lower() not in known:
            # We don't know which canonical it maps to without LLM analysis;
            # store as self-canonical for now (agent will incorporate it next cycle)
            st.add_synonym(icp.icp_id, "title", title, title)
