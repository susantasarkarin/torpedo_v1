"""
AGENT 2 — DATABASE & DATA MODELING
MongoDB Collections & Schemas
"""

from datetime import datetime
from typing import Optional, List, Literal, Dict
from pydantic import BaseModel, Field
from enum import Enum


# ============== EMAIL THREAD MODEL ==============

class EmailThreadMessage(BaseModel):
    """Individual email message in a thread"""
    message_id: str = Field(..., description="RFC Message-ID for deduplication")
    thread_id: Optional[str] = Field(None, description="Thread grouping ID")
    subject: str = ""
    body_preview: str = Field("", description="First 200 chars of body")
    body_full: str = Field("", description="Full email body")
    direction: Literal["sent", "received"] = "received"
    inbox_used: str = Field("", description="Which of the 8 inboxes this came from")
    from_email: str = ""
    to_emails: List[str] = []
    cc_emails: List[str] = []
    date: datetime = Field(default_factory=datetime.utcnow)
    attachments: List[str] = Field([], description="Attachment filenames")
    segment: str = "others"


# ============== RFQ MODELS ==============

class RFQStatus(str, Enum):
    """RFQ status workflow"""
    PENDING = "pending"
    QUOTED = "quoted"
    NEGOTIATING = "negotiating"
    WON = "won"
    LOST = "lost"


class RFQPriority(str, Enum):
    """RFQ priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RFQSourceEmail(BaseModel):
    """Email source for RFQ"""
    message_id: str
    subject: str
    inbox: str
    date: datetime
    extracted_amount: Optional[float] = None


class RFQ(BaseModel):
    """
    Request for Quotation record.
    Collection: rfqs
    Indexes:
        - contact_email
        - lead_id
        - status
        - created_at
    """
    rfq_id: str = Field(..., description="Auto-generated RFQ-YYYY-NNNN")
    
    # Links
    contact_email: str = Field(..., description="Lead's email (foreign key)")
    lead_id: Optional[str] = Field(None, description="ObjectId reference to lead")
    
    # RFQ Details
    title: str = ""
    description: str = ""
    
    # Value (with override)
    extracted_value: Optional[float] = Field(None, description="AI/regex extracted from email")
    extracted_currency: str = "USD"
    manual_value: Optional[float] = Field(None, description="User override")
    manual_currency: Optional[str] = None
    
    @property
    def final_value(self) -> Optional[float]:
        return self.manual_value if self.manual_value is not None else self.extracted_value
    
    @property
    def final_currency(self) -> str:
        return self.manual_currency if self.manual_currency else self.extracted_currency
    
    # Source Emails
    source_emails: List[RFQSourceEmail] = []
    
    # Status
    status: RFQStatus = RFQStatus.PENDING
    priority: RFQPriority = RFQPriority.MEDIUM
    
    # Dates
    received_date: datetime = Field(default_factory=datetime.utcnow)
    due_date: Optional[datetime] = None
    quoted_date: Optional[datetime] = None
    closed_date: Optional[datetime] = None
    
    # AI Summary
    summary: str = ""
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = "auto"


class RFQCreate(BaseModel):
    """Request model for creating RFQ manually"""
    contact_email: str
    lead_id: Optional[str] = None
    title: str
    description: str = ""
    manual_value: Optional[float] = None
    manual_currency: str = "USD"
    priority: RFQPriority = RFQPriority.MEDIUM
    due_date: Optional[datetime] = None


class RFQUpdate(BaseModel):
    """Request model for updating RFQ"""
    title: Optional[str] = None
    description: Optional[str] = None
    manual_value: Optional[float] = None
    manual_currency: Optional[str] = None
    status: Optional[RFQStatus] = None
    priority: Optional[RFQPriority] = None
    due_date: Optional[datetime] = None


# ============== ENUMS ==============

class SeniorityLevel(str, Enum):
    C_LEVEL = "C-Level"
    VP = "VP"
    DIRECTOR = "Director"
    MANAGER = "Manager"
    IC = "IC"
    UNKNOWN = "Unknown"


class Department(str, Enum):
    SALES = "Sales"
    MARKETING = "Marketing"
    ENGINEERING = "Engineering"
    OPERATIONS = "Operations"
    FINANCE = "Finance"
    HR = "HR"
    PRODUCT = "Product"
    OTHER = "Other"


class Persona(str, Enum):
    DECISION_MAKER = "Decision Maker"
    INFLUENCER = "Influencer"
    GATEKEEPER = "Gatekeeper"
    PRACTITIONER = "Practitioner"


class BuyingRole(str, Enum):
    """Buying role in B2B decision making"""
    ECONOMIC_BUYER = "Economic Buyer"
    TECHNICAL_BUYER = "Technical Buyer"
    USER_BUYER = "User Buyer"
    CHAMPION = "Champion"
    INFLUENCER = "Influencer"
    UNKNOWN = "Unknown"


class Gender(str, Enum):
    """Gender inference from name/profile"""
    MALE = "Male"
    FEMALE = "Female"
    UNKNOWN = "Unknown"


class EmailStatus(str, Enum):
    """Email verification status"""
    VALID = "Valid"
    INVALID = "Invalid"
    CATCH_ALL = "Catch-All"
    UNKNOWN = "Unknown"
    NOT_FOUND = "Not Found"
    PREDICTED = "Predicted"  # AI-predicted email based on name pattern


class CompanySize(str, Enum):
    STARTUP = "Startup"
    SMB = "SMB"
    MID_MARKET = "Mid-Market"
    ENTERPRISE = "Enterprise"


class Region(str, Enum):
    US = "US"
    EU = "EU"
    APAC = "APAC"
    LATAM = "LATAM"
    OTHER = "Other"


class ClassificationStatus(str, Enum):
    PENDING = "Pending"
    PROCESSING = "Processing"
    CLASSIFIED = "Classified"
    FAILED = "Failed"


# ============== INPUT CONTRACT ==============

class LeadSource(str, Enum):
    """Supported lead data sources"""
    WEB_SEARCH = "web_search"
    LINKEDIN = "linkedin"
    GOOGLE_SEARCH = "google_search"
    CSV = "csv"
    GOOGLE_SHEETS = "google_sheets"
    APOLLO = "apollo"
    ZOOMINFO = "zoominfo"
    MANUAL = "manual"


class LeadInput(BaseModel):
    """Shared Lead Input Contract - All agents must respect this schema"""
    name: str
    title: str
    linkedin_url: str
    snippet: str = ""
    source: str = "linkedin"  # Flexible source field
    # Personal fields
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    email_status: Optional[str] = None
    location: Optional[str] = None
    added_on: Optional[str] = None
    profile_picture: Optional[str] = None
    seniority_level: Optional[str] = None
    buying_role: Optional[str] = None
    gender: Optional[str] = None
    # Company fields
    company_name: Optional[str] = None
    company_domain: Optional[str] = None
    company_website: Optional[str] = None
    company_employee_count: Optional[str] = None
    company_employee_count_range: Optional[str] = None
    company_founded: Optional[str] = None
    company_industry: Optional[str] = None
    company_type: Optional[str] = None
    company_headquarters: Optional[str] = None
    company_revenue_range: Optional[str] = None
    company_linkedin_url: Optional[str] = None
    # New fields per Issue 6
    company_crunchbase_url: Optional[str] = None
    company_funding_rounds: Optional[str] = None
    company_last_funding_round_amount: Optional[str] = None
    company_logo_url_primary: Optional[str] = None
    company_logo_url_secondary: Optional[str] = None


# ============== RAW LEAD (leads_raw collection) ==============

class LeadRaw(BaseModel):
    """
    Raw lead data - preserved forever, never modified after creation.
    Collection: leads_raw
    Indexes: 
        - linkedin_url (unique)
        - created_at
        - classification_status
    """
    name: str
    title: str
    linkedin_url: str = Field(..., description="Unique identifier")
    snippet: str = ""
    source: str = "linkedin"
    # Personal fields
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    email_status: Optional[str] = None
    location: Optional[str] = None
    added_on: Optional[str] = None
    profile_picture: Optional[str] = None
    seniority_level: Optional[str] = None
    buying_role: Optional[str] = None
    gender: Optional[str] = None
    # Company fields from import
    company_name: Optional[str] = None
    company_domain: Optional[str] = None
    company_website: Optional[str] = None
    company_employee_count: Optional[str] = None
    company_employee_count_range: Optional[str] = None
    company_founded: Optional[str] = None
    company_industry: Optional[str] = None
    company_type: Optional[str] = None
    company_headquarters: Optional[str] = None
    company_revenue_range: Optional[str] = None
    company_linkedin_url: Optional[str] = None
    # New fields per Issue 6
    company_crunchbase_url: Optional[str] = None
    company_funding_rounds: Optional[str] = None
    company_last_funding_round_amount: Optional[str] = None
    company_logo_url_primary: Optional[str] = None
    company_logo_url_secondary: Optional[str] = None
    # System fields
    created_at: datetime = Field(default_factory=datetime.utcnow)
    classification_status: ClassificationStatus = ClassificationStatus.PENDING
    classification_attempts: int = 0
    last_classification_attempt: Optional[datetime] = None
    enriched_lead_id: Optional[str] = None  # Reference to leads_enriched


# ============== AI CLASSIFICATION OUTPUT ==============

class AIClassificationOutput(BaseModel):
    """Strict JSON schema for ChatGPT output - expanded fields"""
    # Name parsing
    first_name: str
    last_name: str
    # Email prediction
    predicted_email: Optional[str] = None
    # Classification
    seniority_level: SeniorityLevel
    department: Department
    persona: Persona
    buying_role: BuyingRole
    gender: Gender
    company_size: CompanySize
    region: Region
    # Company data (AI inferred)
    company_name: Optional[str] = None
    company_domain: Optional[str] = None
    company_website: Optional[str] = None
    company_employee_count: Optional[str] = None
    company_employee_count_range: Optional[str] = None
    company_founded: Optional[str] = None
    company_industry: Optional[str] = None
    company_type: Optional[str] = None
    company_headquarters: Optional[str] = None
    company_revenue_range: Optional[str] = None
    company_linkedin_url: Optional[str] = None
    # Inferred data
    inferred_location: Optional[str] = None
    # Confidence
    confidence_score: float = Field(..., ge=0.0, le=1.0)


# ============== ENRICHED LEAD (leads_enriched collection) ==============

class LeadEnriched(BaseModel):
    """
    Enriched lead with AI classification, engagement tracking, and outreach history.
    
    Collection: leads_enriched
    
    Indexes:
        - raw_lead_id
        - seniority_level
        - department
        - persona
        - confidence_score
        - campaign_ids
        - email (unique for deduplication)
        - engagement_status (for filtering by engagement state)
        - sequence_stage (for tracking outreach sequences)
        - linkedin_connection_status (for LinkedIn tracking)
    
    New Fields (Agent 1 - Engagement & Outreach):
        - engagement_score: Numeric score 0-100 tracking email engagement
        - engagement_status: Categorical status of email engagement
        - sequence_stage: Current position in outreach sequence
        - last_outreach_date: Timestamp of most recent contact
        - outreach_history: Complete history of all outreach attempts
        - reengagement_eligible: Flag for re-engagement campaigns
        - reengagement_pool_date: When added to re-engagement pool
        - timezone: Detected timezone for send-time optimization
        - linkedin_connection_status: LinkedIn connection state
        - linkedin_connection_date: When connection was made
        - linkedin_last_message_date: Last LinkedIn message timestamp
        - reply_sentiment: AI sentiment analysis of replies
    """
    raw_lead_id: str
    
    # Personal Information
    name: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    email_status: EmailStatus = EmailStatus.UNKNOWN
    title: str
    linkedin_url: str
    location: Optional[str] = None
    phone: Optional[str] = None
    
    # Metadata
    added_on: datetime = Field(default_factory=datetime.utcnow)
    source: str = "linkedin"
    snippet: str = ""
    
    # AI Classification fields
    seniority_level: SeniorityLevel
    buying_role: BuyingRole
    department: Department
    persona: Persona
    gender: Gender
    company_size: CompanySize
    region: Region
    confidence_score: float
    
    # Company Information
    company_name: Optional[str] = None
    company_domain: Optional[str] = None
    company_website: Optional[str] = None
    company_employee_count: Optional[str] = None
    company_employee_count_range: Optional[str] = None
    company_founded: Optional[str] = None
    company_industry: Optional[str] = None
    company_type: Optional[str] = None
    company_headquarters: Optional[str] = None
    company_revenue_range: Optional[str] = None
    company_linkedin_url: Optional[str] = None
    company_crunchbase_url: Optional[str] = None
    company_funding_rounds: Optional[str] = None
    company_last_funding_round_amount: Optional[str] = None
    company_logo_url: Optional[str] = None
    
    # Email Correspondence (NEW)
    email_threads: List[EmailThreadMessage] = Field([], description="All emails to/from this lead")
    seen_in_inboxes: List[str] = Field([], description="List of org inboxes that have correspondence")
    email_message_ids: List[str] = Field([], description="All message IDs for deduplication")
    last_email_date: Optional[datetime] = None
    conversation_summary: str = Field("", description="AI-generated conversation summary")
    
    # RFQ Links (NEW)
    rfq_ids: List[str] = Field([], description="Links to rfqs collection")
    
    # ============== ENGAGEMENT TRACKING & OUTREACH HISTORY ==============
    
    # Engagement Metrics
    engagement_score: float = Field(0.0, description="Engagement score 0-100 based on email opens, clicks, replies")
    engagement_status: Optional[str] = Field(
        None, 
        description="Current engagement state: never_opened | opened_no_reply | engaged | replied_positive | replied_neutral | replied_negative | unsubscribed"
    )
    
    # Sequence Tracking
    sequence_stage: Optional[str] = Field(None, description="Current step in outreach sequence: email_1, email_2, email_3, etc.")
    last_outreach_date: Optional[datetime] = Field(None, description="Timestamp of last outreach attempt")
    outreach_history: List[Dict] = Field(
        [], 
        description="List of outreach attempts with structure: {timestamp, channel, status, subject, response_type}"
    )
    
    # Re-engagement Pool
    reengagement_eligible: bool = Field(False, description="Whether lead is eligible for re-engagement after dormancy")
    reengagement_pool_date: Optional[datetime] = Field(None, description="When lead was added to re-engagement pool")
    
    # Timezone & Timing
    timezone: Optional[str] = Field(None, description="Detected timezone for optimal send times (e.g., 'America/New_York')")
    
    # LinkedIn Integration
    linkedin_connection_status: Optional[str] = Field(
        None, 
        description="LinkedIn connection state: none | pending | connected | rejected"
    )
    linkedin_connection_date: Optional[datetime] = Field(None, description="When LinkedIn connection was established")
    linkedin_last_message_date: Optional[datetime] = Field(None, description="Last LinkedIn message timestamp")
    
    # Reply Sentiment Analysis
    reply_sentiment: Optional[str] = Field(
        None, 
        description="AI-analyzed sentiment of last reply: positive | neutral | negative | unsubscribe"
    )
    
    # ============== TEAM COLLABORATION (Agent 18 - Phase 3) ==============
    
    # Assignment & Ownership
    assigned_to: Optional[str] = Field(None, description="User ID of assigned team member")
    last_touched_by: Optional[str] = Field(None, description="User ID of last person to interact with this lead")
    team_id: Optional[str] = Field(None, description="Team that owns this lead")
    
    # Versioning
    classification_version: int = 1
    classified_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Campaign association
    campaign_ids: List[str] = []
    
    # Enrichment tracking
    enriched_at: Optional[datetime] = None
    enrichment_source: Optional[str] = None  # "openai_websearch", "clearbit", "manual"
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============== AI CLASSIFICATION LOG (lead_ai_classification_logs) ==============

class AIClassificationLog(BaseModel):
    """
    Audit log for all AI classification attempts.
    Collection: lead_ai_classification_logs
    Indexes:
        - raw_lead_id
        - created_at
        - success
    """
    raw_lead_id: str
    linkedin_url: str
    
    # Request details
    prompt_used: str
    model_used: str = "gpt-4o-mini"
    temperature: float = 0.1
    
    # Response details
    raw_response: Optional[str] = None
    parsed_output: Optional[dict] = None
    
    # Status
    success: bool
    error_message: Optional[str] = None
    confidence_score: Optional[float] = None
    
    # Performance
    tokens_used: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============== API REQUEST/RESPONSE MODELS ==============

class LeadImportRequest(BaseModel):
    leads: List[LeadInput]


class LeadImportResponse(BaseModel):
    imported: int
    duplicates: int
    errors: int
    lead_ids: List[str]


class LeadClassifyRequest(BaseModel):
    lead_ids: Optional[List[str]] = None  # If None, classify all pending
    batch_size: Optional[int] = None  # If None, classify ALL pending leads


class LeadClassifyResponse(BaseModel):
    queued: int
    message: str


class LeadFilterParams(BaseModel):
    seniority_level: Optional[SeniorityLevel] = None
    department: Optional[Department] = None
    persona: Optional[Persona] = None
    company_size: Optional[CompanySize] = None
    industry: Optional[str] = None
    region: Optional[Region] = None
    min_confidence: Optional[float] = None
    status: Optional[ClassificationStatus] = None
    lead_stage: Optional[str] = None  # Filter by lead stage: ai_database, leads, contacts
    lead_bracket: Optional[str] = None  # Filter by bracket: lead, contact, account
    source: Optional[str] = None  # Filter by source: google_search, csv_import, gmail, etc.
    search: Optional[str] = None
    fit_tier: Optional[int] = None
    basket: Optional[str] = None
    qualified_only: bool = False  # If True, show only Gmail contacts + outreach-replied leads
    page: int = 1
    limit: int = 50


class AttachLeadsRequest(BaseModel):
    lead_ids: List[str]
