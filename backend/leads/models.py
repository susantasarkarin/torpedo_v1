"""
AGENT 2 — DATABASE & DATA MODELING
MongoDB Collections & Schemas
"""

from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from enum import Enum


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
    snippet: str
    source: str = "linkedin"  # Flexible source field


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
    snippet: str
    source: str = "linkedin"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    classification_status: ClassificationStatus = ClassificationStatus.PENDING
    classification_attempts: int = 0
    last_classification_attempt: Optional[datetime] = None
    enriched_lead_id: Optional[str] = None  # Reference to leads_enriched


# ============== AI CLASSIFICATION OUTPUT ==============

class AIClassificationOutput(BaseModel):
    """Strict JSON schema for ChatGPT output"""
    seniority_level: SeniorityLevel
    department: Department
    persona: Persona
    company_size: CompanySize
    industry: str
    region: Region
    confidence_score: float = Field(..., ge=0.0, le=1.0)


# ============== ENRICHED LEAD (leads_enriched collection) ==============

class LeadEnriched(BaseModel):
    """
    Enriched lead with AI classification.
    Collection: leads_enriched
    Indexes:
        - raw_lead_id
        - seniority_level
        - department
        - persona
        - industry
        - region
        - confidence_score
        - campaign_ids
    """
    raw_lead_id: str
    name: str
    title: str
    linkedin_url: str
    snippet: str
    source: str
    
    # AI Classification fields
    seniority_level: SeniorityLevel
    department: Department
    persona: Persona
    company_size: CompanySize
    industry: str
    region: Region
    confidence_score: float
    
    # Versioning
    classification_version: int = 1
    classified_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Campaign association
    campaign_ids: List[str] = []
    
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
    batch_size: int = 10


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
    search: Optional[str] = None
    page: int = 1
    limit: int = 50


class AttachLeadsRequest(BaseModel):
    lead_ids: List[str]
