"""
Fixture data for lead-gen pipeline tests.
No real API calls — all data is local.
"""

from backend.lead_gen_mcp.schemas import (
    ICPDefinition,
    SERPResult,
    ScoredLead,
    EnrichedLead,
)

SURVEY_ICP = ICPDefinition(
    icp_id="survey_test",
    name="Survey Fieldwork Test",
    target_titles=["Head of Insights", "Research Director", "VP Market Research", "Panel Manager"],
    target_industries=["Market Research", "FMCG", "Consumer Goods", "Healthcare"],
    target_geos=["India", "United Kingdom", "Germany", "Singapore"],
    company_size_band="50-500",
    exclusion_rules={"excluded_companies": ["Accenture"], "min_icp_score": 0.25},
    min_hunter_confidence=70,
    daily_query_budget=50,
)

SERP_HIT = SERPResult(
    name="Priya Sharma",
    title="Head of Insights",
    company="Nielsen India",
    location="Mumbai, India",
    profile_url="https://www.linkedin.com/in/priya-sharma-insights",
    snippet="Head of Insights at Nielsen India · Market Research · Mumbai",
    source_query='site:linkedin.com/in/ "Head of Insights" "Market Research" India',
)

SERP_LOW_SCORE = SERPResult(
    name="John Developer",
    title="Senior Software Engineer",
    company="Google",
    location="San Francisco",
    profile_url="https://www.linkedin.com/in/john-dev-google",
    snippet="Senior SWE at Google",
    source_query='site:linkedin.com/in/ "Head of Insights" India',
)

SERP_EXCLUDED = SERPResult(
    name="Alice Manager",
    title="Research Director",
    company="Accenture",
    location="London, UK",
    profile_url="https://www.linkedin.com/in/alice-manager-accenture",
    snippet="Research Director at Accenture",
    source_query='site:linkedin.com/in/ "Research Director" UK',
)

SCORED_LEAD = ScoredLead(
    profile_url="https://www.linkedin.com/in/priya-sharma-insights",
    name="Priya Sharma",
    title="Head of Insights",
    company="Nielsen India",
    location="Mumbai, India",
    snippet="Head of Insights at Nielsen India · Market Research · Mumbai",
    source_query='site:linkedin.com/in/ "Head of Insights" "Market Research" India',
    icp_id="survey_test",
    icp_score=0.90,
)

ENRICHED_LEAD = EnrichedLead(
    profile_url="https://www.linkedin.com/in/priya-sharma-insights",
    name="Priya Sharma",
    title="Head of Insights",
    company="Nielsen India",
    location="Mumbai, India",
    snippet="Head of Insights at Nielsen India · Market Research · Mumbai",
    source_query='site:linkedin.com/in/ "Head of Insights" "Market Research" India',
    icp_id="survey_test",
    icp_score=0.90,
    email="priya.sharma@nielsen.com",
    hunter_confidence=85,
    verification_status="valid",
    domain="nielsen.com",
)
