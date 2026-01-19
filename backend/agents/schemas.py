"""
Agent Schemas - Pydantic models for agent configurations and outputs
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from enum import Enum


# ============== ENUMS ==============

class AgentType(str, Enum):
    """Types of lead generation agents"""
    COMPANY_DISCOVERY = "company_discovery"
    CONTACT_FINDER = "contact_finder"
    LEAD_ENRICHER = "lead_enricher"
    LEAD_SCORER = "lead_scorer"
    OUTREACH_COMPOSER = "outreach_composer"


class AgentStatus(str, Enum):
    """Agent execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CompanySizeFilter(str, Enum):
    """Company size filters for discovery"""
    STARTUP = "1-10"
    SMALL = "11-50"
    MEDIUM = "51-200"
    LARGE = "201-1000"
    ENTERPRISE = "1000+"


class DecisionLevelFilter(str, Enum):
    """Decision level filters for contact finding"""
    C_LEVEL = "C-Level"
    VP = "VP"
    DIRECTOR = "Director"
    MANAGER = "Manager"
    SENIOR = "Senior"
    ANY = "Any"


class OutreachTone(str, Enum):
    """Tone for outreach emails"""
    FORMAL = "formal"
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"
    CASUAL = "casual"


# ============== AGENT CONFIGURATIONS ==============

class CompanyDiscoveryConfig(BaseModel):
    """Configuration for Company Discovery Agent"""
    icp_description: str = Field(
        default="B2B SaaS companies looking for sales automation solutions",
        description="Ideal Customer Profile description"
    )
    industries: List[str] = Field(
        default=["Technology", "Software", "SaaS"],
        description="Target industries"
    )
    company_sizes: List[CompanySizeFilter] = Field(
        default=[CompanySizeFilter.MEDIUM, CompanySizeFilter.LARGE],
        description="Target company sizes"
    )
    locations: List[str] = Field(
        default=["United States", "United Kingdom", "Canada"],
        description="Target locations/countries"
    )
    keywords: List[str] = Field(
        default=[],
        description="Additional search keywords"
    )
    exclude_keywords: List[str] = Field(
        default=[],
        description="Keywords to exclude from search"
    )


class ContactFinderConfig(BaseModel):
    """Configuration for Contact Finder Agent"""
    target_titles: List[str] = Field(
        default=["CEO", "CTO", "VP Sales", "Head of Sales", "Sales Director", "VP Marketing"],
        description="Target job titles to find"
    )
    decision_levels: List[DecisionLevelFilter] = Field(
        default=[DecisionLevelFilter.C_LEVEL, DecisionLevelFilter.VP, DecisionLevelFilter.DIRECTOR],
        description="Target decision levels"
    )
    departments: List[str] = Field(
        default=["Sales", "Marketing", "Executive"],
        description="Target departments"
    )
    include_linkedin: bool = Field(
        default=True,
        description="Include LinkedIn profile URLs"
    )
    include_email_guess: bool = Field(
        default=True,
        description="Generate email guesses based on patterns"
    )


class LeadEnricherConfig(BaseModel):
    """Configuration for Lead Enricher Agent"""
    fields_to_enrich: List[str] = Field(
        default=["company_size", "industry", "email", "phone", "location", "company_revenue"],
        description="Fields to enrich"
    )
    email_patterns: List[str] = Field(
        default=[
            "{first}.{last}@{domain}",
            "{first}{last}@{domain}",
            "{f}{last}@{domain}",
            "{first}@{domain}"
        ],
        description="Email pattern templates to try"
    )
    verify_existing_data: bool = Field(
        default=True,
        description="Verify and correct existing data"
    )


class LeadScorerConfig(BaseModel):
    """Configuration for Lead Scorer Agent"""
    scoring_weights: Dict[str, float] = Field(
        default={
            "title_match": 25.0,
            "company_size": 20.0,
            "industry_fit": 20.0,
            "decision_level": 15.0,
            "email_available": 10.0,
            "linkedin_complete": 10.0
        },
        description="Weights for each scoring criterion (should sum to 100)"
    )
    minimum_score_threshold: float = Field(
        default=50.0,
        description="Minimum score to consider a lead qualified"
    )
    ideal_titles: List[str] = Field(
        default=["CEO", "CTO", "VP Sales", "Head of Growth"],
        description="Ideal job titles for scoring"
    )
    ideal_industries: List[str] = Field(
        default=["Technology", "Software", "SaaS", "B2B Services"],
        description="Ideal industries for scoring"
    )
    ideal_company_sizes: List[str] = Field(
        default=["51-200", "201-1000"],
        description="Ideal company sizes for scoring"
    )


class OutreachComposerConfig(BaseModel):
    """Configuration for Outreach Composer Agent"""
    tone: OutreachTone = Field(
        default=OutreachTone.PROFESSIONAL,
        description="Email tone"
    )
    value_proposition: str = Field(
        default="We help companies automate their sales outreach and increase conversion rates by 3x.",
        description="Main value proposition to highlight"
    )
    call_to_action: str = Field(
        default="Would you be open to a quick 15-minute call this week?",
        description="Call to action for the email"
    )
    sender_name: str = Field(
        default="",
        description="Sender's name for personalization"
    )
    sender_title: str = Field(
        default="",
        description="Sender's title"
    )
    company_name: str = Field(
        default="",
        description="Sender's company name"
    )
    max_words: int = Field(
        default=150,
        description="Maximum words in email body"
    )
    include_subject_line: bool = Field(
        default=True,
        description="Generate subject line"
    )
    personalization_level: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Level of personalization"
    )


class AgentConfig(BaseModel):
    """
    Master agent configuration - stored in MongoDB agent_configurations collection
    """
    config_id: Optional[str] = None
    name: str = Field(default="Default Configuration", description="Configuration preset name")
    description: str = Field(default="", description="Configuration description")
    user_id: Optional[str] = None
    is_default: bool = False
    
    # Per-agent configurations
    company_discovery: CompanyDiscoveryConfig = Field(default_factory=CompanyDiscoveryConfig)
    contact_finder: ContactFinderConfig = Field(default_factory=ContactFinderConfig)
    lead_enricher: LeadEnricherConfig = Field(default_factory=LeadEnricherConfig)
    lead_scorer: LeadScorerConfig = Field(default_factory=LeadScorerConfig)
    outreach_composer: OutreachComposerConfig = Field(default_factory=OutreachComposerConfig)
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============== AGENT OUTPUT RESULTS ==============

class CompanyResult(BaseModel):
    """Single company result from Company Discovery Agent"""
    name: str = Field(..., description="Company name")
    domain: str = Field(..., description="Company website domain")
    industry: str = Field(default="", description="Industry")
    size_estimate: str = Field(default="", description="Employee count estimate")
    headquarters: str = Field(default="", description="HQ location")
    description: str = Field(default="", description="Company description")
    linkedin_url: Optional[str] = Field(default=None, description="Company LinkedIn URL")
    founded_year: Optional[str] = Field(default=None, description="Year founded")
    source_url: Optional[str] = Field(default=None, description="Source URL where found")


class CompanyDiscoveryResult(BaseModel):
    """Batch result from Company Discovery Agent (10 companies)"""
    companies: List[CompanyResult] = Field(default_factory=list)
    query_used: str = ""
    total_found: int = 0
    search_timestamp: datetime = Field(default_factory=datetime.utcnow)


class ContactResult(BaseModel):
    """Single contact result from Contact Finder Agent"""
    full_name: str = Field(..., description="Full name")
    first_name: str = Field(default="", description="First name")
    last_name: str = Field(default="", description="Last name")
    title: str = Field(..., description="Job title")
    company_name: str = Field(..., description="Company name")
    company_domain: str = Field(default="", description="Company domain")
    linkedin_url: Optional[str] = Field(default=None, description="LinkedIn profile URL")
    email_guess: Optional[str] = Field(default=None, description="Guessed email address")
    decision_level: str = Field(default="Unknown", description="Decision level")
    department: str = Field(default="", description="Department")
    location: Optional[str] = Field(default=None, description="Location")
    source_url: Optional[str] = Field(default=None, description="Source URL")


class ContactFinderResult(BaseModel):
    """Batch result from Contact Finder Agent (10 contacts per company)"""
    contacts: List[ContactResult] = Field(default_factory=list)
    company_name: str = ""
    company_domain: str = ""
    total_found: int = 0
    search_timestamp: datetime = Field(default_factory=datetime.utcnow)


class EnrichedLeadResult(BaseModel):
    """Single enriched lead from Lead Enricher Agent"""
    lead_id: str = Field(..., description="Original lead ID")
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    email: Optional[str] = None
    email_confidence: float = 0.0
    phone: Optional[str] = None
    title: str = ""
    linkedin_url: str = ""
    location: str = ""
    
    # Enriched company data
    company_name: str = ""
    company_domain: str = ""
    company_size: str = ""
    company_industry: str = ""
    company_revenue: Optional[str] = None
    company_founded: Optional[str] = None
    company_headquarters: Optional[str] = None
    
    # Enrichment metadata
    fields_enriched: List[str] = Field(default_factory=list)
    enrichment_sources: List[str] = Field(default_factory=list)


class LeadEnricherResult(BaseModel):
    """Batch result from Lead Enricher Agent (10 leads)"""
    enriched_leads: List[EnrichedLeadResult] = Field(default_factory=list)
    total_enriched: int = 0
    fields_updated: Dict[str, int] = Field(default_factory=dict)
    enrichment_timestamp: datetime = Field(default_factory=datetime.utcnow)


class ScoredLeadResult(BaseModel):
    """Single scored lead from Lead Scorer Agent"""
    lead_id: str = Field(..., description="Lead ID")
    full_name: str = ""
    email: Optional[str] = None
    title: str = ""
    company_name: str = ""
    
    # Scoring
    total_score: float = Field(default=0.0, ge=0.0, le=100.0)
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    is_qualified: bool = False
    
    # Classification
    seniority_level: str = "Unknown"
    decision_level: str = "Unknown"
    buying_role: str = "Unknown"
    department: str = "Other"
    persona: str = "Unknown"
    
    # Recommendations
    priority_rank: int = 0
    recommended_approach: str = ""
    reasoning: str = ""


class LeadScorerResult(BaseModel):
    """Batch result from Lead Scorer Agent (10 leads)"""
    scored_leads: List[ScoredLeadResult] = Field(default_factory=list)
    total_scored: int = 0
    qualified_count: int = 0
    average_score: float = 0.0
    scoring_timestamp: datetime = Field(default_factory=datetime.utcnow)


class OutreachDraftResult(BaseModel):
    """Single outreach draft from Outreach Composer Agent"""
    lead_id: str = Field(..., description="Lead ID")
    recipient_name: str = ""
    recipient_email: Optional[str] = None
    recipient_company: str = ""
    
    # Email content
    subject_line: str = ""
    email_body: str = ""
    
    # Personalization details
    personalization_hooks: List[str] = Field(default_factory=list)
    tone_used: str = "professional"
    word_count: int = 0
    
    # Metadata
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    variant_number: int = 1  # For A/B testing


class OutreachComposerResult(BaseModel):
    """Batch result from Outreach Composer Agent (10 emails)"""
    drafts: List[OutreachDraftResult] = Field(default_factory=list)
    total_generated: int = 0
    average_word_count: float = 0.0
    composition_timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============== JOB TRACKING ==============

class AgentJobStatus(BaseModel):
    """Status of an agent job execution"""
    job_id: str
    status: AgentStatus = AgentStatus.PENDING
    agents_to_run: List[str] = Field(default_factory=list)
    current_agent: Optional[str] = None
    
    # Progress
    total_steps: int = 0
    completed_steps: int = 0
    progress_percent: float = 0.0
    
    # Results
    companies_found: int = 0
    contacts_found: int = 0
    leads_enriched: int = 0
    leads_scored: int = 0
    emails_composed: int = 0
    duplicates_skipped: int = 0
    
    # Errors
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    
    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    estimated_completion: Optional[datetime] = None
    
    # Config used
    config_id: Optional[str] = None
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AgentQuotaStatus(BaseModel):
    """Daily quota status"""
    leads_today: int = 0
    limit: int = 1000
    remaining: int = 1000
    reset_at: datetime = Field(default_factory=datetime.utcnow)
    is_limit_reached: bool = False
