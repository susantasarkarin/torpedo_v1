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
    icp_id: str
    name: str
    target_titles: List[str] = []
    target_industries: List[str] = []
    target_geos: List[str] = []
    company_size_band: Optional[str] = None
    exclusion_rules: Dict[str, Any] = {}
    min_hunter_confidence: int = 70
    daily_query_budget: int = 100


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class QueryProposal(BaseModel):
    query: str
    dimension_cell: str
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
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    snippet: Optional[str] = None
    source_query: str
    icp_id: str
    icp_score: float = 0.0


class ScoreDedupeOutput(BaseModel):
    accepted: List[ScoredLead] = []
    rejected_dupes: List[SERPResult] = []
    rejected_low_score: List[SERPResult] = []


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

class EnrichedLead(BaseModel):
    # Identity
    profile_url: str
    name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    location: Optional[str] = None
    snippet: Optional[str] = None
    source_query: str
    icp_id: str
    icp_score: float = 0.0

    # Email
    email: Optional[str] = None
    email_status: Optional[str] = None    # "valid" | "risky" | "invalid" | "unknown"
    email_pattern: Optional[str] = None   # e.g. "{first}.{last}" — stored for audit

    # Company flat fields
    company: Optional[str] = None
    company_industry: Optional[str] = None
    company_linkedin: Optional[str] = None
    company_location: Optional[str] = None
    company_city: Optional[str] = None
    company_state: Optional[str] = None
    company_country: Optional[str] = None
    company_employees: Optional[str] = None   # stored as string e.g. "200-500"
    company_revenue: Optional[str] = None
    company_type: Optional[str] = None        # "private" | "public" | etc.
    company_website: Optional[str] = None
    company_domain: Optional[str] = None
    company_twitter: Optional[str] = None
    company_founded: Optional[str] = None

    added_on: Optional[str] = None            # ISO timestamp when lead was added

    @classmethod
    def from_scored(cls, lead: ScoredLead, **enrichment) -> "EnrichedLead":
        return cls(**lead.model_dump(), **enrichment)


class EnrichOutput(BaseModel):
    enriched: List[EnrichedLead] = []
    skipped: List[ScoredLead] = []


# ---------------------------------------------------------------------------
# Domain pattern cache entry
# ---------------------------------------------------------------------------

class DomainPattern(BaseModel):
    domain: str
    pattern: str                              # e.g. "{first}.{last}"
    organization: Optional[str] = None
    company_type: Optional[str] = None
    company_industry: Optional[str] = None
    company_country: Optional[str] = None
    company_city: Optional[str] = None
    company_state: Optional[str] = None
    company_employees: Optional[str] = None
    company_revenue: Optional[str] = None
    company_website: Optional[str] = None
    company_linkedin: Optional[str] = None
    company_twitter: Optional[str] = None
    company_founded: Optional[str] = None


# ---------------------------------------------------------------------------
# CRM push
# ---------------------------------------------------------------------------

class CRMPushOutput(BaseModel):
    created: List[str] = []
    skipped_duplicates: List[str] = []
    failed: List[Dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------

class QueryOutcome(BaseModel):
    query: str
    icp_id: str
    dimension_cell: str
    results_count: int
    novel_count: int
    icp_passing: int
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
    event_type: str
    description: Optional[str] = None
    icp_id: Optional[str] = None
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
    yield_curve: List[Dict[str, Any]] = []
