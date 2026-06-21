"""
ICP match scorer + pipeline deduplicator.

Scoring (0.0 – 1.0):
  title match   → 0.40
  industry match→ 0.25
  geo match     → 0.25
  seniority     → 0.10

A lead must score >= icp.min_icp_score (default 0.30) to be accepted.
Dedup is checked against state.profiles_seen (SQLite, pipeline-level).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .schemas import (
    ICPDefinition,
    SERPResult,
    ScoredLead,
    ScoreDedupeOutput,
)
from . import state as st

_SENIORITY_KEYWORDS = [
    "vp", "vice president", "director", "head of", "chief", "cxo", "ceo",
    "coo", "cfo", "cmo", "cto", "cpo", "svp", "evp", "partner", "president",
    "founder", "co-founder", "managing director", "md", "principal",
]

# Default minimum score — overridable per ICP via exclusion_rules["min_icp_score"]
_DEFAULT_MIN_SCORE = 0.30


def _tok(text: Optional[str]) -> str:
    return (text or "").lower()


def _phrase_match(text: str, candidates: List[str]) -> bool:
    """True if any candidate phrase appears in text."""
    tl = text.lower()
    for c in candidates:
        cl = c.lower().strip()
        if not cl:
            continue
        if len(cl) <= 3:
            if re.search(rf"\b{re.escape(cl)}\b", tl):
                return True
        else:
            if cl in tl:
                return True
    return False


def _has_seniority(title: Optional[str]) -> bool:
    tl = _tok(title)
    return any(kw in tl for kw in _SENIORITY_KEYWORDS)


def score_result(result: SERPResult, icp: ICPDefinition) -> float:
    """Return a 0.0–1.0 ICP match score for a single SERP result."""
    combined = f"{result.title or ''} {result.snippet or ''}"

    title_hit = _phrase_match(combined, icp.target_titles)
    industry_hit = _phrase_match(combined, icp.target_industries)
    geo_hit = _phrase_match(
        f"{result.location or ''} {result.snippet or ''}",
        icp.target_geos,
    )
    seniority_hit = _has_seniority(result.title)

    score = 0.0
    if title_hit:
        score += 0.40
    if industry_hit:
        score += 0.25
    if geo_hit:
        score += 0.25
    if seniority_hit:
        score += 0.10

    return round(min(score, 1.0), 3)


def _min_score(icp: ICPDefinition) -> float:
    return float(icp.exclusion_rules.get("min_icp_score", _DEFAULT_MIN_SCORE))


def _is_excluded(result: SERPResult, icp: ICPDefinition) -> bool:
    """Check exclusion rules: excluded_companies, excluded_titles."""
    excl_companies = icp.exclusion_rules.get("excluded_companies", [])
    excl_titles = icp.exclusion_rules.get("excluded_titles", [])
    if excl_companies and result.company:
        if _phrase_match(result.company, excl_companies):
            return True
    if excl_titles and result.title:
        if _phrase_match(result.title, excl_titles):
            return True
    return False


def score_and_dedup(
    results: List[SERPResult],
    icp: ICPDefinition,
) -> ScoreDedupeOutput:
    """
    Score a flat list of SERP results and deduplicate them against the
    pipeline's profiles_seen store.

    Returns accepted (ScoredLead), rejected_dupes, rejected_low_score.
    """
    accepted: List[ScoredLead] = []
    rejected_dupes: List[SERPResult] = []
    rejected_low_score: List[SERPResult] = []

    min_score = _min_score(icp)
    seen_in_batch: set[str] = set()

    for result in results:
        url = result.profile_url.strip().lower()

        # 1. Within-batch dedup
        if url in seen_in_batch:
            rejected_dupes.append(result)
            continue
        seen_in_batch.add(url)

        # 2. Exclusion rules
        if _is_excluded(result, icp):
            rejected_low_score.append(result)
            continue

        # 3. Persist-level dedup
        if st.is_profile_seen(url):
            rejected_dupes.append(result)
            continue

        # 4. Score
        score = score_result(result, icp)
        if score < min_score:
            rejected_low_score.append(result)
            continue

        # Mark seen and accept
        st.mark_profile_seen(url, icp.icp_id, result.source_query)
        accepted.append(
            ScoredLead(
                profile_url=url,
                name=result.name,
                title=result.title,
                company=result.company,
                location=result.location,
                snippet=result.snippet,
                source_query=result.source_query,
                icp_id=icp.icp_id,
                icp_score=score,
            )
        )

    return ScoreDedupeOutput(
        accepted=accepted,
        rejected_dupes=rejected_dupes,
        rejected_low_score=rejected_low_score,
    )


def extract_title_synonyms(results: List[SERPResult], icp: ICPDefinition) -> List[str]:
    """
    Parse titles from SERP results that passed the query but weren't in the
    ICP's target_titles list. Return novel titles found (raw, lowercase).
    Caller is responsible for saving to synonyms table.
    """
    known = {t.lower() for t in icp.target_titles}
    novel = set()
    for r in results:
        if not r.title:
            continue
        tl = r.title.lower().strip()
        if tl and tl not in known and len(tl) > 3:
            novel.add(tl)
    return sorted(novel)
