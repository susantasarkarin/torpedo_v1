"""
Cint API Integration - Data Models

Defines Pydantic models for:
- Cint Opportunities (survey feed from webhook)
- Cint Entry Links (supplier-specific respondent entry points)
- Cint Quotas & Qualifications
- Cint Settings & Configuration
"""
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from enum import Enum


# ============================================
# Enums
# ============================================

class SupplierLinkType(str, Enum):
    """Cint supplier link engagement type"""
    OWS = "OWS"  # Offerwall/Standalone
    TS = "TS"    # Targeted/Standalone
    OTC = "OTC"  # Other


class TrackingType(str, Enum):
    """How Cint communicates back to supplier"""
    NONE = "NONE"      # Physical redirect (default)
    PIXEL = "PIXEL"    # Pixel tracking
    S2S = "S2S"        # Server-to-server postback


class ComparisonOperator(str, Enum):
    """Comparison operators for opportunity filtering"""
    EQ = "eq"
    NE = "ne"
    IN = "in"
    NIN = "nin"
    GTE = "gte"
    LTE = "lte"


class MessageReason(str, Enum):
    """Status of survey in opportunities subscription"""
    NEW = "new"
    UPDATED = "updated"
    REACTIVATED = "reactivated"
    DEACTIVATED = "deactivated"


# ============================================
# Opportunity/Survey Models
# ============================================

class CintOpportunityBase(BaseModel):
    """Base model for Cint opportunity from webhook"""
    survey_id: int
    survey_name: str
    account_name: str
    buyer_id: int
    country_language: str  # e.g., "eng_us"
    industry: Optional[str] = None
    study_type: Optional[str] = None  # e.g., "adhoc", "recruit", "recontact"
    
    # Survey parameters
    bid_length_of_interview: Optional[int] = None  # Estimated LOI in minutes
    bid_incidence: Optional[float] = None  # Estimated IR as percentage (0-100)
    collects_pii: Optional[bool] = None
    
    # Revenue & performance
    revenue_per_interview: Optional[Dict[str, Any]] = None  # {"value": 1.35, "currency_code": "USD"}
    revenue_per_click: Optional[float] = None
    
    # Actual metrics
    conversion: Optional[float] = None  # 0.0-1.0
    mobile_conversion: Optional[float] = None  # 0.0-1.0
    length_of_interview: Optional[int] = None  # Actual LOI in minutes
    termination_length_of_interview: Optional[int] = None  # Median termination LOI
    
    # Quota/Status
    total_client_entrants: Optional[int] = None
    total_remaining: Optional[int] = None
    completion_percentage: Optional[float] = None
    overall_completes: Optional[int] = None
    is_live: bool = True
    relationship_type: Optional[str] = None  # "open" or "private"
    
    # Messaging
    message_reason: str = "new"  # new, updated, reactivated, deactivated
    px_buyer_message: Optional[List[str]] = None  # Tags from buyer
    respondent_pids: Optional[List[str]] = None  # For recontact surveys
    survey_group_ids: Optional[List[int]] = None


class CintOpportunity(CintOpportunityBase):
    """Full opportunity model with internal tracking"""
    id: Optional[str] = Field(None, alias="_id", description="MongoDB ObjectId")
    
    # Internal tracking
    received_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated_at: datetime = Field(default_factory=datetime.utcnow)
    webhook_timestamp: Optional[datetime] = None
    
    # Quotas & qualifications (optional, only if include_quotas=true in subscription)
    survey_quotas: Optional[List[Dict[str, Any]]] = None
    survey_qualifications: Optional[List[Dict[str, Any]]] = None
    
    # Local cache of parsed data
    is_active: bool = True  # false if message_reason is "deactivated"
    
    class Config:
        populate_by_name = True
        use_enum_values = True


class CintQuota(BaseModel):
    """Survey quota detail"""
    survey_quota_id: int
    survey_quota_type: str  # "Total", "Client"
    conversion: float
    number_of_respondents: int
    questions: Optional[List[Dict[str, Any]]] = None


class QuestionDetail(BaseModel):
    """Question detail in quota or qualification"""
    question_id: int
    logical_operator: str  # "OR", "AND"
    precodes: List[str]


# ============================================
# Entry Link Models
# ============================================

class SupplierLinkBase(BaseModel):
    """Base entry link model"""
    supplier_link_type_code: SupplierLinkType = Field(..., alias="SupplierLinkTypeCode", description="Type of engagement")
    tracking_type_code: TrackingType = Field(default=TrackingType.NONE, alias="TrackingTypeCode", description="Communication method")
    
    # Redirect URLs (max 2999 characters each) - aliases for Cint API PascalCase
    default_link: Optional[str] = Field(None, alias="DefaultLink")
    success_link: Optional[str] = Field(None, alias="SuccessLink")
    failure_link: Optional[str] = Field(None, alias="FailureLink")
    over_quota_link: Optional[str] = Field(None, alias="OverQuotaLink")
    quality_termination_link: Optional[str] = Field(None, alias="QualityTerminationLink")
    
    class Config:
        populate_by_name = True  # Allow both snake_case and PascalCase


class SupplierLinkCreate(SupplierLinkBase):
    """Model for creating entry link"""
    pass


class SupplierLinkUpdate(SupplierLinkBase):
    """Model for updating entry link (all fields required)"""
    supplier_link_type_code: SupplierLinkType
    tracking_type_code: TrackingType
    default_link: str
    success_link: str
    failure_link: str
    over_quota_link: str
    quality_termination_link: str


class SupplierLink(SupplierLinkBase):
    """Full entry link model with generated links"""
    id: Optional[str] = Field(None, alias="_id", description="MongoDB ObjectId")
    survey_id: int
    survey_number: Optional[int] = None
    
    # Generated by Cint - aliases for PascalCase API response
    live_link: Optional[str] = Field(None, alias="LiveLink")
    test_link: Optional[str] = Field(None, alias="TestLink")
    
    # Payout information - alias for CPI from API
    cpi: Optional[float] = Field(None, alias="CPI")
    rpi: Optional[Dict[str, Any]] = Field(None, alias="RPI")  # {"value": 1.35, "currency_code": "USD"}
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True  # Allow both snake_case and PascalCase
        use_enum_values = True


# ============================================
# Subscription Models
# ============================================

class OpportunitiesSubscriptionFilter(BaseModel):
    """Filter criteria for opportunities subscription"""
    country_language: Optional[Dict[str, Any]] = None  # {"in": ["eng_us", "eng_gb"]}
    industry: Optional[Dict[str, Any]] = None
    study_type: Optional[Dict[str, Any]] = None
    bid_length_of_interview: Optional[Dict[str, Any]] = None
    bid_incidence: Optional[Dict[str, Any]] = None
    collects_pii: Optional[Dict[str, Any]] = None
    revenue_per_interview: Optional[Dict[str, Any]] = None
    conversion: Optional[Dict[str, Any]] = None
    mobile_conversion: Optional[Dict[str, Any]] = None
    revenue_per_click: Optional[Dict[str, Any]] = None
    length_of_interview: Optional[Dict[str, Any]] = None
    termination_length_of_interview: Optional[Dict[str, Any]] = None
    buyer_id: Optional[Dict[str, Any]] = None
    px_buyer_message: Optional[Dict[str, Any]] = None


class OpportunitiesSubscriptionConfig(BaseModel):
    """Configuration for opportunities webhook subscription"""
    callback_url: str = Field(..., description="Webhook URL for opportunities")
    include_quotas: bool = Field(default=False, description="Include quota/qualification data")
    payload_max_size_mb: int = Field(default=8, ge=4, le=32, description="Max payload size in MB")
    payload_max_survey_count: int = Field(default=1000, ge=1000, le=10000, description="Max surveys per callback")
    send_interval_seconds: int = Field(default=15, ge=5, le=30, description="Batch time interval")
    opportunities_filters: List[OpportunitiesSubscriptionFilter] = Field(default_factory=list, description="Filter criteria")
    
    class Config:
        use_enum_values = True


class CintSubscription(BaseModel):
    """Stored subscription configuration"""
    id: Optional[str] = Field(None, alias="_id")
    supplier_code: str
    config: OpportunitiesSubscriptionConfig
    status: Literal["active", "inactive", "error"] = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_webhook_received_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    class Config:
        populate_by_name = True
        use_enum_values = True


# ============================================
# Respondent Outcomes Models (for tracking session results)
# ============================================

class RespondentOutcome(BaseModel):
    """Respondent session outcome from webhook"""
    respondent_id: str
    parent_session_id: Optional[str] = None
    panelist_id: Optional[str] = None
    session_id: str
    marketplace_status: int  # Cint Exchange status code
    client_status: int  # Client/buyer status code
    entry_date: datetime
    last_date: datetime
    survey_id: int
    rpi: Optional[Dict[str, Any]] = None  # {"value": 1.25, "currency_code": "USD"}
    study_type: Optional[str] = None
    
    # Internal tracking
    received_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True


class OutcomeSubscriptionConfig(BaseModel):
    """Configuration for respondent outcomes subscription"""
    callback_url: str = Field(..., description="Webhook URL for outcomes")
    outcome_filters: List[Dict[str, Any]] = Field(default_factory=list, description="Status filters")
    
    class Config:
        use_enum_values = True


# ============================================
# Settings & Configuration Models
# ============================================

class CintSettings(BaseModel):
    """Cint integration settings (stored per user/account)"""
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    
    # API Configuration
    api_key: str = Field(..., description="Cint API key (stored securely)")
    supplier_code: str = Field(..., description="Unique supplier code")
    environment: Literal["sandbox", "production"] = "sandbox"
    
    # Subscription Configuration
    opportunities_subscription: Optional[OpportunitiesSubscriptionConfig] = None
    outcomes_subscription: Optional[OutcomeSubscriptionConfig] = None
    
    # Webhook Configuration
    webhook_secret: Optional[str] = None  # For validating incoming webhooks
    webhook_url_opportunities: Optional[str] = None
    webhook_url_outcomes: Optional[str] = None
    
    # Filter Preferences
    preferred_countries: List[str] = Field(default_factory=list)
    preferred_industries: List[str] = Field(default_factory=list)
    min_cpi: float = Field(default=0.0)
    max_loi: int = Field(default=60)
    
    # Auto-pause settings (same as survey allocation)
    auto_pause_enabled: bool = Field(default=True)
    max_incomplete_rate: float = Field(default=40.0)
    min_incidence_rate: float = Field(default=10.0)
    
    # Status
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        populate_by_name = True
        use_enum_values = True


# ============================================
# Request/Response Models
# ============================================

class WebhookValidationRequest(BaseModel):
    """Request to validate webhook signature"""
    payload: Dict[str, Any]
    signature: str
    timestamp: str


class EntryLinkResponse(BaseModel):
    """Response with entry link details"""
    success: bool
    message: str
    link: Optional[SupplierLink] = None
    data: Optional[Dict[str, Any]] = None


class OpportunitiesListResponse(BaseModel):
    """Response listing active opportunities"""
    success: bool
    count: int
    opportunities: List[CintOpportunity]


class SettingsResponse(BaseModel):
    """Response with settings"""
    success: bool
    settings: CintSettings


# ============================================
# Error Models
# ============================================

class CintAPIError(BaseModel):
    """Error response from Cint API"""
    error: str
    error_code: Optional[str] = None
    message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
