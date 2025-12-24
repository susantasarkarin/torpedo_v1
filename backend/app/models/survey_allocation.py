"""
Survey Allocation & Quality Control Engine - Data Models

Defines Pydantic models for:
- Respondents
- Surveys
- SurveyPerformance/Metrics
- AllocationSettings
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime
from enum import Enum


# ============================================
# Enums for Status Types
# ============================================

class RespondentStatus(str, Enum):
    """Respondent lifecycle states"""
    NEW = "new"
    ALLOCATED = "allocated"
    STARTED = "started"
    COMPLETED = "completed"
    TERMINATED = "terminated"
    QUOTA_FULL = "quota_full"
    SCREENED_OUT = "screened_out"


class SurveyStatus(str, Enum):
    """Survey availability states"""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    EXPIRED = "expired"


# ============================================
# Respondent Models
# ============================================

class RespondentBase(BaseModel):
    """Base respondent model with incoming parameters"""
    vid: str = Field(..., description="Vendor ID")
    cc: str = Field(..., description="Country Code (ISO 2-letter)")
    rid: str = Field(..., description="Respondent ID (unique per vendor)")


class RespondentCreate(RespondentBase):
    """Model for creating a new respondent"""
    pass


class Respondent(RespondentBase):
    """Full respondent model with all tracking fields"""
    id: Optional[str] = Field(None, alias="_id", description="MongoDB ObjectId")
    status: RespondentStatus = Field(default=RespondentStatus.NEW)
    
    # Allocation details (populated when allocated)
    survey_id: Optional[str] = None
    survey_name: Optional[str] = None
    vendor_redirect_url: Optional[str] = None
    entry_link: Optional[str] = None
    allocation_timestamp: Optional[datetime] = None
    
    # Tracking timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    terminated_at: Optional[datetime] = None
    
    # Additional metadata
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    class Config:
        populate_by_name = True
        use_enum_values = True


class RespondentUpdate(BaseModel):
    """Model for updating respondent status"""
    status: Optional[RespondentStatus] = None
    survey_id: Optional[str] = None
    survey_name: Optional[str] = None
    vendor_redirect_url: Optional[str] = None
    entry_link: Optional[str] = None


# ============================================
# Survey Models
# ============================================

class SurveyBase(BaseModel):
    """Base survey model from provider"""
    external_id: str = Field(..., description="Survey ID from provider")
    provider: str = Field(..., description="Survey provider (e.g., 'cpx', 'cint', 'lucid')")
    name: str = Field(..., description="Survey name/title")
    description: Optional[str] = None
    
    # Targeting criteria
    country_codes: List[str] = Field(default_factory=list, description="Eligible country codes")
    language_code: Optional[str] = None
    
    # Survey parameters
    loi: int = Field(..., description="Length of Interview in minutes")
    cpi: float = Field(..., description="Cost Per Interview in dollars")
    ir: Optional[float] = Field(None, description="Expected Incidence Rate from provider")
    
    # Quota management
    remaining_quota: int = Field(..., description="Remaining completes needed")
    total_quota: int = Field(..., description="Total completes required")
    
    # URLs
    entry_url: str = Field(..., description="Survey entry URL")
    complete_redirect_url: Optional[str] = None
    terminate_redirect_url: Optional[str] = None
    quota_full_redirect_url: Optional[str] = None


class SurveyCreate(SurveyBase):
    """Model for creating/importing a survey"""
    pass


class Survey(SurveyBase):
    """Full survey model with tracking fields"""
    id: Optional[str] = Field(None, alias="_id", description="MongoDB ObjectId")
    status: SurveyStatus = Field(default=SurveyStatus.ACTIVE)
    
    # Allocation tracking
    current_batch_sent: int = Field(default=0, description="Allocations in current batch")
    total_allocations: int = Field(default=0, description="Total allocations ever sent")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    paused_at: Optional[datetime] = None
    paused_reason: Optional[str] = None
    
    # Provider metadata
    provider_data: Optional[dict] = Field(default=None, description="Raw provider data")
    
    class Config:
        populate_by_name = True
        use_enum_values = True


class SurveyUpdate(BaseModel):
    """Model for updating survey"""
    name: Optional[str] = None
    status: Optional[SurveyStatus] = None
    remaining_quota: Optional[int] = None
    cpi: Optional[float] = None
    ir: Optional[float] = None


# ============================================
# Survey Performance/Metrics Models
# ============================================

class SurveyMetrics(BaseModel):
    """Real-time performance metrics for a survey"""
    survey_id: str = Field(..., description="Reference to survey")
    
    # Core metrics
    sent_n: int = Field(default=0, description="Total allocations sent")
    entrants_n: int = Field(default=0, description="Respondents who started the survey")
    completes_n: int = Field(default=0, description="Respondents who completed")
    incompletes_n: int = Field(default=0, description="Respondents who dropped off after starting")
    terminates_n: int = Field(default=0, description="Respondents who were terminated/screened out")
    quota_full_n: int = Field(default=0, description="Respondents who hit quota full")
    
    # Calculated rates (stored for quick access)
    incidence_rate: float = Field(default=0.0, description="IR = (completes / entrants) * 100")
    incomplete_rate: float = Field(default=0.0, description="Incomplete Rate = (incompletes / entrants) * 100")
    conversion_rate: float = Field(default=0.0, description="Conversion = (completes / sent) * 100")
    
    # Timestamps
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    last_allocation: Optional[datetime] = None
    last_complete: Optional[datetime] = None
    
    class Config:
        use_enum_values = True

    def recalculate_rates(self):
        """Recalculate derived rates from raw counts"""
        if self.entrants_n > 0:
            self.incidence_rate = round((self.completes_n / self.entrants_n) * 100, 2)
            self.incomplete_rate = round((self.incompletes_n / self.entrants_n) * 100, 2)
        else:
            self.incidence_rate = 0.0
            self.incomplete_rate = 0.0
        
        if self.sent_n > 0:
            self.conversion_rate = round((self.completes_n / self.sent_n) * 100, 2)
        else:
            self.conversion_rate = 0.0
        
        self.last_updated = datetime.utcnow()


# ============================================
# Allocation Settings Model
# ============================================

class AllocationSettings(BaseModel):
    """Configurable allocation parameters (stored in Profile > Settings)"""
    # Batch allocation
    batch_size: int = Field(default=100, ge=1, le=1000, description="Allocations per batch before pausing")
    buffer_multiplier: float = Field(default=1.2, ge=1.0, le=2.0, description="Allocation buffer (1.2 = 20% extra)")
    
    # Quality control thresholds
    max_incomplete_rate: float = Field(default=40.0, ge=0, le=100, description="Max incomplete rate before pause (%)")
    min_incidence_rate: float = Field(default=10.0, ge=0, le=100, description="Min IR before pause (%)")
    minimum_entrants_for_evaluation: int = Field(default=50, ge=10, le=500, description="Min entrants before evaluating pause rules")
    
    # Auto-pause settings
    auto_pause_enabled: bool = Field(default=True, description="Enable automatic survey pausing")
    pause_cooldown_minutes: int = Field(default=30, ge=5, le=1440, description="Cooldown before auto-resuming paused survey")
    
    # Allocation preferences
    prefer_high_ir_surveys: bool = Field(default=True, description="Prioritize surveys with higher expected IR")
    prefer_high_cpi_surveys: bool = Field(default=False, description="Prioritize surveys with higher CPI")
    
    class Config:
        use_enum_values = True


# ============================================
# Allocation Request/Response Models
# ============================================

class AllocationRequest(BaseModel):
    """Request for survey allocation"""
    vid: str = Field(..., description="Vendor ID")
    cc: str = Field(..., description="Country Code")
    rid: str = Field(..., description="Respondent ID")
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AllocationResponse(BaseModel):
    """Response with allocated survey details"""
    success: bool
    message: str
    respondent_id: Optional[str] = None
    survey_id: Optional[str] = None
    survey_name: Optional[str] = None
    entry_link: Optional[str] = None
    allocation_id: Optional[str] = None


# ============================================
# Callback Event Models
# ============================================

class CallbackEvent(BaseModel):
    """Survey callback event from provider/client"""
    event_type: Literal["start", "complete", "incomplete", "terminate", "quota_full"]
    respondent_id: str = Field(..., description="Our internal respondent ID")
    survey_id: str = Field(..., description="Survey ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Optional[dict] = None


class CallbackResponse(BaseModel):
    """Response to callback event"""
    success: bool
    message: str
    redirect_url: Optional[str] = None
