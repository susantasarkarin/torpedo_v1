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


class ReengagementAgentConfig(BaseModel):
    """Configuration for Reengagement Agent"""
    inactivity_threshold_days: int = Field(
        default=30,
        description="Days of inactivity to trigger reengagement"
    )
    max_reengagement_attempts: int = Field(
        default=3,
        description="Maximum number of reengagement attempts per lead"
    )
    focus_value_proposition: str = Field(
        default="We've improved our solution based on customer feedback",
        description="Value proposition specifically for reengagement"
    )
    sender_name: str = Field(
        default="",
        description="Sender's name for reengagement emails"
    )
    sender_title: str = Field(
        default="",
        description="Sender's title"
    )
    company_name: str = Field(
        default="",
        description="Sender's company name"
    )


class ABTestAnalyzerConfig(BaseModel):
    """Configuration for A/B Test Analyzer Agent"""
    significance_threshold: float = Field(
        default=0.95,
        description="Confidence level for statistical significance (0-1)"
    )
    minimum_sample_size: int = Field(
        default=100,
        description="Minimum samples per variant for analysis"
    )
    focus_metrics: List[str] = Field(
        default=["open_rate", "click_rate", "reply_rate"],
        description="Which metrics to prioritize in analysis"
    )


# ============== REENGAGEMENT AGENT SCHEMAS ==============

class DormancyAnalysis(BaseModel):
    """Analysis of why a lead went dormant"""
    reason: str = Field(..., description="Primary reason for dormancy")
    opened_last_email: bool = Field(default=False, description="Did they open last email")
    clicked_any_link: bool = Field(default=False, description="Did they click any link")
    replied_any: bool = Field(default=False, description="Did they reply to any email")
    days_since_last_engagement: int = Field(default=0, description="Days of inactivity")
    engagement_pattern: str = Field(default="", description="Pattern of engagement")
    industry_context: str = Field(default="", description="Industry-specific dormancy factors")


class ReengagementStrategy(BaseModel):
    """Reengagement strategy recommendation"""
    strategy_type: str = Field(..., description="Type: reset, soft_drip, trigger_based")
    description: str = Field(..., description="Description of the strategy")
    expected_response_lift: float = Field(default=0.0, ge=0.0, le=1.0, description="Expected lift in response rate")
    next_action: str = Field(..., description="Specific next action to take")


class FreshAngle(BaseModel):
    """Fresh angle/value prop for reengagement"""
    angle: str = Field(..., description="New value proposition angle")
    reasoning: str = Field(..., description="Why this angle for this lead")
    suggested_copy: str = Field(..., description="Suggested email copy using this angle")


class ReengagementPlan(BaseModel):
    """Complete reengagement plan for a lead"""
    lead_id: str = Field(..., description="Lead ID")
    full_name: str = ""
    email: Optional[str] = None
    company_name: str = ""
    
    # Analysis
    dormancy_analysis: DormancyAnalysis = Field(default_factory=DormancyAnalysis)
    
    # Strategy
    recommended_strategy: ReengagementStrategy = Field(default_factory=ReengagementStrategy)
    
    # Fresh angle
    fresh_angle: FreshAngle = Field(default_factory=FreshAngle)
    
    # Recommendations
    sender_to_use: str = Field(default="", description="Recommended sender (rotation)")
    optimal_send_day: str = Field(default="", description="Best day to send")
    optimal_send_time: str = Field(default="", description="Best time to send")
    subject_line_suggestion: str = Field(default="", description="Suggested subject line")
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReengagementResult(BaseModel):
    """Batch result from Reengagement Agent"""
    reengagement_plans: List[ReengagementPlan] = Field(default_factory=list)
    total_analyzed: int = 0
    total_dormant: int = 0
    strategy_distribution: Dict[str, int] = Field(default_factory=dict)
    analysis_timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============== A/B TEST ANALYZER SCHEMAS ==============

class VariantPerformance(BaseModel):
    """Performance metrics for a test variant"""
    variant_id: str = Field(..., description="Variant ID (A, B, C, etc.)")
    variant_name: str = Field(default="", description="Human-readable variant name")
    emails_sent: int = Field(default=0, description="Number of emails sent")
    opens: int = Field(default=0, description="Number of opens")
    clicks: int = Field(default=0, description="Number of clicks")
    replies: int = Field(default=0, description="Number of replies")
    conversions: int = Field(default=0, description="Number of conversions")
    
    # Calculated metrics
    open_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    click_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    reply_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    conversion_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    
    # Metadata
    subject_line: str = Field(default="", description="Subject line for this variant")
    cta_text: str = Field(default="", description="CTA text for this variant")
    email_length: str = Field(default="", description="Email length category")


class TestWinner(BaseModel):
    """Analysis of test winner"""
    winner_id: str = Field(..., description="ID of winning variant")
    winner_name: str = Field(..., description="Name of winning variant")
    metrics_won: List[str] = Field(default_factory=list, description="Which metrics it won on")
    primary_win_reason: str = Field(..., description="Main reason it won")
    detailed_reasoning: str = Field(..., description="Detailed explanation")
    improvement_over_control: Dict[str, float] = Field(default_factory=dict, description="% improvement vs control")
    statistical_confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence level (0-1)")


class NextVariantSuggestion(BaseModel):
    """Suggested variant to test next"""
    experiment_name: str = Field(..., description="Name of next experiment")
    variant_a_description: str = Field(..., description="Variant A setup")
    variant_b_description: str = Field(..., description="Variant B setup")
    expected_improvement: str = Field(..., description="Expected improvement")
    hypothesis: str = Field(..., description="Testing hypothesis")
    why_this_variant: str = Field(..., description="Why test this variant next")


class ABTestAnalysis(BaseModel):
    """Complete A/B test analysis"""
    test_name: str = Field(default="", description="Name of the test")
    control_variant: VariantPerformance = Field(default_factory=VariantPerformance)
    test_variants: List[VariantPerformance] = Field(default_factory=list)
    
    # Results
    test_winner: TestWinner = Field(default_factory=TestWinner)
    is_statistically_significant: bool = False
    
    # Copy improvements
    recommended_copy_changes: List[str] = Field(default_factory=list)
    
    # Next steps
    next_variant_suggestions: List[NextVariantSuggestion] = Field(default_factory=list)
    
    # Metadata
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)


class ABTestAnalyzerResult(BaseModel):
    """Batch result from A/B Test Analyzer Agent"""
    tests_analyzed: List[ABTestAnalysis] = Field(default_factory=list)
    total_tests: int = 0
    winners_identified: int = 0
    statistically_significant_count: int = 0
    analysis_timestamp: datetime = Field(default_factory=datetime.utcnow)


class BehaviorFollowupDraft(BaseModel):
    """Behavior-based follow-up email draft"""
    lead_id: str = Field(..., description="Lead ID")
    behavior_type: str = Field(..., description="Type: opened_no_reply, not_opened, clicked, replied")
    original_subject: str = Field(default="", description="Original email subject")
    followup_subject: str = Field(..., description="Follow-up subject line")
    followup_body: str = Field(..., description="Follow-up email body")
    cta_modification: str = Field(default="", description="How CTA was modified")
    reasoning: str = Field(..., description="Reasoning for this followup")
    word_count: int = 0
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class BehaviorFollowupResult(BaseModel):
    """Result from behavior-based follow-up generation"""
    followup_drafts: List[BehaviorFollowupDraft] = Field(default_factory=list)
    total_generated: int = 0
    by_behavior_type: Dict[str, int] = Field(default_factory=dict)
    generation_timestamp: datetime = Field(default_factory=datetime.utcnow)


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
    reengagement_agent: ReengagementAgentConfig = Field(default_factory=ReengagementAgentConfig)
    ab_test_analyzer: ABTestAnalyzerConfig = Field(default_factory=ABTestAnalyzerConfig)
    
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
