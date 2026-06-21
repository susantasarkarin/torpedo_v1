"""
GCSE (Google Custom Search Engine) search adapter.

Supports:
- site:linkedin.com/in/ query targeting
- Pagination up to 10 pages (10 results/page)
- Recency filters: "week" → tbs=qdr:w, "month" → tbs=qdr:m
- Per-ICP daily quota cap (reads from state.py daily count)
- Defers to the existing google_rate_limit module for global hourly/daily tracking
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import List, Optional

import httpx

from .schemas import SearchBatchResult, SERPResult

# Reuse existing rate-limit tracker from the main backend.
# We import the module file directly to avoid triggering backend/leads/__init__.py,
# which loads scheduler_optimized and requires a live MongoDB connection.
import importlib.util as _ilu
import pathlib as _pl

def _load_rate_limiter():
    _mod_path = _pl.Path(__file__).parent.parent / "leads" / "google_rate_limit.py"
    _spec = _ilu.spec_from_file_location("_google_rate_limit", _mod_path)
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    return _mod

try:
    _rl = _load_rate_limiter()
    can_make_query = _rl.can_make_query
    record_query = _rl.record_query
except Exception:
    # Fallback stubs for isolated testing / CI without MongoDB
    def can_make_query():  # type: ignore
        return True, "ok"

    def record_query(queries: int = 1):  # type: ignore
        return {}

GCSE_API_URL = "https://www.googleapis.com/customsearch/v1"
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID", "")
QUERY_DELAY_SECONDS = float(os.getenv("GOOGLE_CSE_QUERY_DELAY", "2"))

_RECENCY_MAP = {
    "week": "qdr:w",
    "month": "qdr:m",
    "day": "qdr:d",
}


def _build_linkedin_query(raw_query: str) -> str:
    """Prepend site:linkedin.com/in/ if not already present."""
    if "site:linkedin.com/in/" not in raw_query:
        return f'site:linkedin.com/in/ {raw_query}'
    return raw_query


def _parse_serp_snippet(item: dict, source_query: str) -> Optional[SERPResult]:
    """
    Extract structured fields from a GCSE search result item.
    Returns None if the result doesn't look like a LinkedIn profile.
    """
    link = item.get("link", "")
    if "linkedin.com/in/" not in link:
        return None

    title_raw = item.get("title", "")
    snippet = item.get("snippet", "")

    # LinkedIn title format: "Name - Title at Company | LinkedIn"
    name = None
    job_title = None
    company = None

    if " - " in title_raw:
        parts = title_raw.split(" - ", 1)
        name = parts[0].strip()
        rest = parts[1].replace(" | LinkedIn", "").strip()
        if " at " in rest:
            title_company = rest.rsplit(" at ", 1)
            job_title = title_company[0].strip()
            company = title_company[1].strip()
        else:
            job_title = rest

    # Location: sometimes in snippet after "·"
    location = None
    loc_match = re.search(r"·\s*([^·\n]{3,40})\s*·", snippet)
    if loc_match:
        location = loc_match.group(1).strip()

    return SERPResult(
        name=name,
        title=job_title,
        company=company,
        location=location,
        profile_url=link,
        snippet=snippet[:400],
        source_query=source_query,
    )


async def _fetch_page(
    client: httpx.AsyncClient,
    query: str,
    start: int,
    recency_filter: Optional[str],
) -> list:
    params: dict = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CSE_ID,
        "q": query,
        "start": start,
        "num": 10,
    }
    if recency_filter and recency_filter in _RECENCY_MAP:
        params["tbs"] = _RECENCY_MAP[recency_filter]

    resp = await client.get(GCSE_API_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("items", [])


async def run_search_batch(
    queries: List[str],
    pages_per_query: int = 1,
    recency_filter: Optional[str] = None,
    per_icp_daily_remaining: Optional[int] = None,
) -> List[SearchBatchResult]:
    """
    Execute a batch of queries against GCSE.

    Args:
        queries:                   Raw query strings (site:linkedin.com/in/ prepended if missing)
        pages_per_query:           Pages to fetch per query (1 page = 10 results, max 10)
        recency_filter:            "week" | "month" | "day" | None
        per_icp_daily_remaining:   Optional hard cap for this ICP's daily budget
    """
    pages_per_query = min(pages_per_query, 10)
    results: List[SearchBatchResult] = []
    budget_remaining = per_icp_daily_remaining  # may be None (no cap)

    async with httpx.AsyncClient() as client:
        for raw_query in queries:
            # Check global rate limit
            allowed, msg = can_make_query()
            if not allowed:
                results.append(SearchBatchResult(
                    query=raw_query, error=f"Rate limited: {msg}"
                ))
                continue

            if budget_remaining is not None and budget_remaining <= 0:
                results.append(SearchBatchResult(
                    query=raw_query, error="ICP daily query budget exhausted"
                ))
                continue

            linkedin_query = _build_linkedin_query(raw_query)
            batch_results: List[SERPResult] = []
            pages_fetched = 0
            error_msg = None

            for page in range(pages_per_query):
                start = page * 10 + 1
                try:
                    items = await _fetch_page(client, linkedin_query, start, recency_filter)
                    record_query(1)
                    pages_fetched += 1

                    if budget_remaining is not None:
                        budget_remaining -= 1

                    for item in items:
                        parsed = _parse_serp_snippet(item, raw_query)
                        if parsed:
                            batch_results.append(parsed)

                    if len(items) < 10:
                        break  # no more results

                    if page < pages_per_query - 1:
                        await asyncio.sleep(QUERY_DELAY_SECONDS)

                except httpx.HTTPStatusError as e:
                    error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                    break
                except Exception as e:
                    error_msg = str(e)
                    break

            results.append(SearchBatchResult(
                query=raw_query,
                results=batch_results,
                quota_consumed=pages_fetched,
                error=error_msg,
            ))

            if len(queries) > 1:
                await asyncio.sleep(QUERY_DELAY_SECONDS)

    return results
