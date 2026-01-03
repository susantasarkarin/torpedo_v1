"""
PYDANTIC SCHEMAS MODULE
Request/Response validation models for API endpoints.

Provides type-safe request validation and automatic API documentation.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr, validator
from enum import Enum


# ============== COMMON SCHEMAS ==============

class PaginationParams(BaseModel):
    """Standard pagination parameters for list endpoints."""
    skip: int = Field(default=0, ge=0, description="Number of records to skip")
    limit: int = Field(default=50, ge=1, le=1000, description="Maximum records to return")


class PaginatedResponse(BaseModel):
    """Standard paginated response structure."""
    items: List[Any]
    total: int
    skip: int
    limit: int
    has_more: bool


class SuccessResponse(BaseModel):
    """Standard success response."""
    success: bool = True
    message: str


class ErrorResponse(BaseModel):
    """Standard error response."""
    success: bool = False
    error: str
    details: Optional[Dict[str, Any]] = None


# ============== AUTH SCHEMAS ==============

class LoginRequest(BaseModel):
    """Login credentials."""
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """Login success response."""
    message: str
    username: str
    session_id: str
    role: str


class ChangePasswordRequest(BaseModel):
    """Password change request."""
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, description="Must be at least 8 characters")


class ProfileUpdateRequest(BaseModel):
    """Profile update request - only safe fields."""
    email: Optional[EmailStr] = None
    displayName: Optional[str] = Field(None, max_length=100)


class UserProfile(BaseModel):
    """User profile response."""
    username: str
    email: Optional[str] = None
    displayName: Optional[str] = None
    role: str = "admin"
    createdAt: Optional[str] = None


# ============== CONTACT SCHEMAS ==============

class ContactBase(BaseModel):
    """Base contact fields."""
    email: EmailStr
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    tags: List[str] = []
    customFields: Dict[str, Any] = {}


class ContactCreate(ContactBase):
    """Contact creation request."""
    listId: Optional[str] = None


class ContactUpdate(BaseModel):
    """Contact update request - partial update allowed."""
    email: Optional[EmailStr] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    tags: Optional[List[str]] = None
    customFields: Optional[Dict[str, Any]] = None


class ContactResponse(ContactBase):
    """Contact response with ID."""
    id: str = Field(..., alias="_id")
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    class Config:
        populate_by_name = True


# ============== INVOICE SCHEMAS ==============

class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class InvoiceLineItem(BaseModel):
    """Invoice line item."""
    description: str
    quantity: float = Field(default=1, gt=0)
    rate: float = Field(ge=0)
    amount: float = Field(ge=0)


class InvoiceCreate(BaseModel):
    """Invoice creation request."""
    invoice_number: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: str
    customer_email: Optional[EmailStr] = None
    line_items: List[InvoiceLineItem] = []
    subtotal: float = Field(ge=0)
    tax: float = Field(default=0, ge=0)
    total: float = Field(ge=0)
    status: InvoiceStatus = InvoiceStatus.DRAFT
    due_date: Optional[datetime] = None
    notes: Optional[str] = None


class InvoiceUpdate(BaseModel):
    """Invoice update request."""
    customer_name: Optional[str] = None
    customer_email: Optional[EmailStr] = None
    line_items: Optional[List[InvoiceLineItem]] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    status: Optional[InvoiceStatus] = None
    due_date: Optional[datetime] = None
    notes: Optional[str] = None


# ============== VENDOR SCHEMAS ==============

class VendorType(str, Enum):
    PANEL = "panel"
    BILLING = "billing"
    BOTH = "both"


class VendorBase(BaseModel):
    """Base vendor fields."""
    name: str = Field(..., min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    address: Optional[str] = None
    vendor_type: VendorType = VendorType.PANEL
    status: str = "active"
    notes: Optional[str] = None


class VendorCreate(VendorBase):
    """Vendor creation request."""
    pass


class VendorUpdate(BaseModel):
    """Vendor update request - partial update."""
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    address: Optional[str] = None
    vendor_type: Optional[VendorType] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class VendorResponse(VendorBase):
    """Vendor response with ID and metadata."""
    id: str = Field(..., alias="_id")
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    linked_accounts: List[str] = []

    class Config:
        populate_by_name = True


# ============== CLIENT SCHEMAS ==============

class ClientStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    BLOCKED = "blocked"


class ClientBase(BaseModel):
    """Base client fields."""
    name: str = Field(..., min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    contact_person: Optional[str] = None
    status: ClientStatus = ClientStatus.ACTIVE
    notes: Optional[str] = None


class ClientCreate(ClientBase):
    """Client creation request."""
    sales_account_id: Optional[str] = None


class ClientUpdate(BaseModel):
    """Client update request."""
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    contact_person: Optional[str] = None
    status: Optional[ClientStatus] = None
    notes: Optional[str] = None
    sales_account_id: Optional[str] = None


# ============== LEAD SCHEMAS ==============

class SeniorityLevel(str, Enum):
    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    MANAGER = "manager"
    DIRECTOR = "director"
    VP = "vp"
    C_LEVEL = "c_level"
    OWNER = "owner"


class ClassificationStatus(str, Enum):
    PENDING = "pending"
    CLASSIFIED = "classified"
    FAILED = "failed"
    SKIPPED = "skipped"


class LeadBase(BaseModel):
    """Base lead fields."""
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    company: Optional[str] = None
    title: Optional[str] = None
    linkedin_url: Optional[str] = None
    source: Optional[str] = None
    seniority: Optional[SeniorityLevel] = None
    country: Optional[str] = None
    industry: Optional[str] = None


class LeadCreate(LeadBase):
    """Lead creation request."""
    raw_data: Optional[Dict[str, Any]] = None


class LeadUpdate(BaseModel):
    """Lead update request."""
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    company: Optional[str] = None
    title: Optional[str] = None
    linkedin_url: Optional[str] = None
    seniority: Optional[SeniorityLevel] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    classification_status: Optional[ClassificationStatus] = None


# ============== CAMPAIGN SCHEMAS ==============

class CampaignStatus(str, Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CampaignBase(BaseModel):
    """Base campaign fields."""
    name: str = Field(..., min_length=1, max_length=200)
    subject: str = Field(..., min_length=1, max_length=500)
    template_id: Optional[str] = None
    list_ids: List[str] = []
    status: CampaignStatus = CampaignStatus.DRAFT
    scheduled_at: Optional[datetime] = None


class CampaignCreate(CampaignBase):
    """Campaign creation request."""
    pass


class CampaignUpdate(BaseModel):
    """Campaign update request."""
    name: Optional[str] = None
    subject: Optional[str] = None
    template_id: Optional[str] = None
    list_ids: Optional[List[str]] = None
    status: Optional[CampaignStatus] = None
    scheduled_at: Optional[datetime] = None


# ============== SETTINGS SCHEMAS ==============

class AppSettingsUpdate(BaseModel):
    """Application settings update request."""
    mongo_uri: Optional[str] = None
    cpx_app_id: Optional[str] = None
    cpx_ext_user_id: Optional[str] = None
    cpx_secure_hash_key: Optional[str] = None
    cpx_api_timeout: Optional[int] = Field(None, ge=5, le=120)
    openai_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    google_cse_id: Optional[str] = None
    google_sheets_service_account: Optional[str] = None
    google_cse_daily_limit: Optional[int] = Field(None, ge=0, le=10000)
    google_cse_hourly_limit: Optional[int] = Field(None, ge=0, le=1000)
    google_cse_query_delay: Optional[int] = Field(None, ge=0, le=60)
    google_cse_monthly_budget: Optional[float] = Field(None, ge=0)
    google_cse_rate_limit_enabled: Optional[bool] = None


class SurveyFilterSettings(BaseModel):
    """Survey filter settings."""
    max_loi: int = Field(default=20, ge=1, le=120)
    min_cpi: float = Field(default=1.0, ge=0)
    deletion_period_days: int = Field(default=7, ge=1, le=365)
    auto_refresh_enabled: bool = True
    refresh_interval_seconds: int = Field(default=60, ge=10, le=3600)


# ============== WEB SEARCH SCHEMAS ==============

class WebSearchRequest(BaseModel):
    """Web search request for lead generation."""
    designation: str = Field(default="", description="Job titles (comma-separated for multiple)")
    countries: List[str] = Field(default=[], description="Target countries")
    seniorities: List[str] = Field(default=[], description="Seniority levels")
    custom_query: str = Field(default="", description="Additional search terms")
    # Legacy single-value fields
    country: str = ""
    seniority: str = ""


class WebSearchJobResponse(BaseModel):
    """Web search job status response."""
    job_id: str
    status: str
    config: Dict[str, Any]
    target_count: int
    total_found: int
    total_imported: int
    total_duplicates: int
    current_query: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    errors: List[str] = []


# ============== IMAP SCHEMAS ==============

class IMAPAccountCreate(BaseModel):
    """IMAP account creation request."""
    email: EmailStr
    password: str
    imap_server: str = Field(..., description="IMAP server hostname")
    imap_port: int = Field(default=993, ge=1, le=65535)
    use_ssl: bool = True
    folders: List[str] = Field(default=["INBOX"])


class IMAPAccountUpdate(BaseModel):
    """IMAP account update request."""
    password: Optional[str] = None
    imap_server: Optional[str] = None
    imap_port: Optional[int] = None
    use_ssl: Optional[bool] = None
    folders: Optional[List[str]] = None
    is_active: Optional[bool] = None


# ============== CPX SURVEY SCHEMAS ==============

class CPXSurveyBase(BaseModel):
    """Base CPX survey fields."""
    survey_id: str
    name: Optional[str] = None
    loi: int = Field(ge=1, description="Length of interview in minutes")
    cpi: float = Field(ge=0, description="Cost per interview")
    ir: Optional[float] = Field(None, ge=0, le=100, description="Incidence rate")
    quota: Optional[int] = Field(None, ge=0)
    status: str = "active"


class CPXSurveyFilter(BaseModel):
    """CPX survey filter criteria."""
    max_loi: Optional[int] = Field(None, ge=1, le=120)
    min_cpi: Optional[float] = Field(None, ge=0)
    min_ir: Optional[float] = Field(None, ge=0, le=100)
    status: Optional[str] = None
