"""
Shared Pydantic schemas for the adaptive lead-generation pipeline.
These are the canonical types passed between all MCP tools.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# ICP
# ---------------------------------------------------------------------------

class ICPDefinition(BaseModel):
    icp_id: str                            # slug, e.g. "survey_fieldwork"
    name: str
    target_titles: List[str] = []
    target_industries: List[str] = []
    target_geos: List[str] = []
    company_size_band: Optional[str] = None   # e.g. "50-500"
    exclusion_rules: Dict[str, Any] = {}
    min_hunter_confidence: int = 70
    daily_query_budget: int = 100


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class QueryProposal(BaseModel):
    query: str
    dimension_cell: str    # e.g. "vp_sales|fintech|india"
    rationale: str


class SERPResult(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    profile_url: str
    snippet: Optional[str] = None
    source_query: str


class SearchBatchResult(BaseModel):
    query: str
    results: List[SERPResult] = []
    quota_consumed: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Scoring / dedup
# ---------------------------------------------------------------------------

class ScoredLead(BaseModel):
    profile_url: str
    name: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    snippet: Optional[str] = None
    source_query: str
    icp_id: str
    icp_score: float = 0.0          # 0.0 – 1.0


class ScoreDedupeOutput(BaseModel):
    accepted: List[ScoredLead] = []
    rejected_dupes: List[SERPResult] = []
    rejected_low_score: List[SERPResult] = []


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

class EnrichedLead(BaseModel):
    # carries all ScoredLead fields
    profile_url: str
    name: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    snippet: Optional[str] = None
    source_query: str
    icp_id: str
    icp_score: float = 0.0
    # enrichment
    email: Optional[str] = None
    hunter_confidence: Optional[int] = None
    verification_status: Optional[str] = None   # "valid" | "risky" | "invalid"
    domain: Optional[str] = None

    @classmethod
    def from_scored(cls, lead: ScoredLead, **enrichment) -> "EnrichedLead":
        return cls(**lead.model_dump(), **enrichment)


class EnrichOutput(BaseModel):
    enriched: List[EnrichedLead] = []
    skipped: List[ScoredLead] = []


# ---------------------------------------------------------------------------
# CRM push
# ---------------------------------------------------------------------------

class CRMPushOutput(BaseModel):
    created: List[str] = []            # external_ids of new contacts
    skipped_duplicates: List[str] = [] # external_ids already in CRM
    failed: List[Dict[str, Any]] = []  # {"external_id": ..., "error": ...}


# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------

class QueryOutcome(BaseModel):
    query: str
    icp_id: str
    dimension_cell: str
    results_count: int
    novel_count: int        # not previously seen
    icp_passing: int        # passed ICP score threshold
    enriched_count: int
    pushed_count: int


class AgentStateUpdate(BaseModel):
    icp_id: str
    outcomes: List[QueryOutcome]


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------

class TriggerEvent(BaseModel):
    company_name: str
    event_type: str         # "funding" | "hiring" | "leadership_change" | "other"
    description: Optional[str] = None
    icp_id: Optional[str] = None   # restrict to a specific ICP, or None = all
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Pipeline stats
# ---------------------------------------------------------------------------

class PipelineStats(BaseModel):
    icp_id: str
    queries_run: int
    profiles_seen: int
    leads_enriched: int
    leads_pushed: int
    yield_curve: List[Dict[str, Any]] = []   # [{run_ts, novel_count, pushed_count}]
