"""
Survey Transaction Model

Tracks CPX survey transactions using trans_id as the primary identifier.
This model supports the CPX API integration (server-to-server postback flow).

Key Changes from Legacy:
- trans_id is the PRIMARY KEY (no more message_id dependency)
- Postback is the single source of truth for status updates
- Idempotent handling of duplicate/fraud postbacks
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from enum import Enum


class TransactionStatus(str, Enum):
    """Transaction lifecycle states"""
    PENDING = "pending"           # Transaction created, waiting for postback
    STARTED = "started"           # User started survey
    COMPLETED = "completed"       # Survey completed successfully (status=1)
    CANCELED = "canceled"         # User canceled or left survey (status=2)
    FRAUD = "fraud"               # Flagged as fraudulent (status=2 with fraud flag)
    EXPIRED = "expired"           # Transaction expired without completion


class SurveyTransactionBase(BaseModel):
    """Base survey transaction model"""
    trans_id: str = Field(..., description="Transaction ID - PRIMARY KEY (from CPX or generated)")
    user_id: Optional[str] = Field(None, description="User/Respondent ID")
    subid: Optional[str] = Field(None, description="Sub ID for tracking (subid_1 from CPX)")
    subid_2: Optional[str] = Field(None, description="Secondary sub ID (subid_2 from CPX)")
    
    # Survey details
    survey_id: Optional[str] = Field(None, description="CPX Survey ID")
    survey_name: Optional[str] = Field(None, description="Survey name/title")
    
    # Payout info
    amount_usd: Optional[float] = Field(None, description="Payout amount in USD")
    amount_local: Optional[float] = Field(None, description="Payout in local currency")
    currency: str = Field(default="USD", description="Currency code")
    
    # Vendor tracking
    vendor_id: Optional[str] = Field(None, description="Vendor ID (vid)")
    country_code: Optional[str] = Field(None, description="Country code (cc)")


class SurveyTransactionCreate(SurveyTransactionBase):
    """Model for creating a new survey transaction"""
    pass


class SurveyTransaction(SurveyTransactionBase):
    """Full survey transaction model with all tracking fields"""
    id: Optional[str] = Field(None, alias="_id", description="MongoDB ObjectId")
    status: TransactionStatus = Field(default=TransactionStatus.PENDING)
    
    # CPX postback data
    cpx_status: Optional[int] = Field(None, description="Raw CPX status code (1=complete, 2=canceled)")
    ip_address: Optional[str] = Field(None, description="User IP address")
    user_agent: Optional[str] = Field(None, description="User agent string")
    
    # Tracking URLs
    entry_url: Optional[str] = Field(None, description="Survey entry URL used")
    callback_url: Optional[str] = Field(None, description="Last callback URL received")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = Field(None, description="When user started survey")
    completed_at: Optional[datetime] = Field(None, description="When survey was completed")
    
    # Idempotency tracking
    postback_count: int = Field(default=0, description="Number of postbacks received")
    last_postback_at: Optional[datetime] = Field(None, description="Last postback timestamp")
    postback_hash: Optional[str] = Field(None, description="Hash of last postback for dedup")
    
    class Config:
        populate_by_name = True
        use_enum_values = True


class SurveyTransactionUpdate(BaseModel):
    """Model for updating transaction status"""
    status: Optional[TransactionStatus] = None
    cpx_status: Optional[int] = None
    amount_usd: Optional[float] = None
    amount_local: Optional[float] = None
    callback_url: Optional[str] = None


# ============================================
# API Request/Response Models
# ============================================

class CPXPostbackRequest(BaseModel):
    """
    CPX Postback Request Model
    
    CPX sends server-to-server postbacks with these parameters:
    - trans_id: Transaction ID (PRIMARY identifier)
    - status: 1=complete, 2=canceled/fraud
    - amount_usd: Payout amount (optional)
    - amount_local: Local currency payout (optional)
    - subid_1: Our tracking ID (usually SFWID)
    - subid_2: Secondary tracking ID (optional)
    - ip: User IP address (optional)
    - offer_id: CPX offer/survey ID (optional)
    """
    trans_id: str = Field(..., description="Transaction ID from CPX")
    status: int = Field(..., description="Status: 1=complete, 2=canceled")
    amount_usd: Optional[float] = Field(None, description="Payout in USD")
    amount_local: Optional[float] = Field(None, description="Payout in local currency")
    subid_1: Optional[str] = Field(None, alias="subid", description="Primary sub ID (SFWID)")
    subid_2: Optional[str] = Field(None, description="Secondary sub ID")
    ip: Optional[str] = Field(None, description="User IP address")
    offer_id: Optional[str] = Field(None, description="CPX offer/survey ID")
    hash: Optional[str] = Field(None, description="Security hash for validation")


class TransactionStatusResponse(BaseModel):
    """Response model for /response page status lookup"""
    trans_id: str
    status: str
    status_display: str = Field(description="Human-readable status")
    amount_usd: Optional[float] = None
    completed: bool = False
    message: str = ""
    
    
class SurveyStatusPollResponse(BaseModel):
    """Response model for /survey-status polling endpoint"""
    trans_id: str
    status: str
    completed: bool = False
    redirect_url: Optional[str] = None
    poll_again: bool = True
    poll_interval_ms: int = 2000  # Recommended polling interval
