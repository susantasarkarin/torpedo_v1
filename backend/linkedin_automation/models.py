"""
LinkedIn Automation Models
Defines Pydantic schemas for LinkedIn accounts, schedules, automation jobs,
and LinkedIn-sourced opportunities.
"""

from typing import Optional, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, EmailStr, Field


class TaskType(str, Enum):
    """Types of LinkedIn automation tasks"""
    SEND_CONNECTIONS = "send_connections"
    SEND_MESSAGES = "send_messages"
    LIKE_POSTS = "like_posts"
    REPOST_POSTS = "repost_posts"
    COMMENT_POSTS = "comment_posts"
    ALL = "all"  # Run all operations


class JobStatus(str, Enum):
    """Status of an automation job"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    PAUSED = "paused"


class FrequencyType(str, Enum):
    """Frequency of automation execution"""
    DAILY = "daily"
    HOURLY = "hourly"
    WEEKLY = "weekly"
    CUSTOM = "custom"


class OpportunityStatus(str, Enum):
    """Lifecycle state for LinkedIn-discovered opportunities"""
    DISCOVERED = "discovered"
    QUALIFIED = "qualified"
    CONTACTED = "contacted"
    REPLIED = "replied"
    CONVERTED = "converted"
    DISMISSED = "dismissed"


class OpportunityChannel(str, Enum):
    """Origin channel for the LinkedIn signal"""
    MESSAGE = "message"
    COMMENT = "comment"
    INMAIL = "inmail"
    POST_REPLY = "post_reply"
    OTHER = "other"


class LinkedInScheduleConfig(BaseModel):
    """Configuration for scheduling LinkedIn automation"""
    frequency: FrequencyType = FrequencyType.DAILY
    run_time: str = "00:00"  # HH:MM format, UTC
    days_of_week: Optional[List[int]] = None  # 0-6 (Monday-Sunday), None = every day
    enabled: bool = True
    
    class Config:
        json_schema_extra = {
            "example": {
                "frequency": "daily",
                "run_time": "02:00",
                "days_of_week": None,
                "enabled": True
            }
        }


class LinkedInAccountCreate(BaseModel):
    """Schema for creating a LinkedIn account"""
    email: EmailStr
    password: str
    account_name: str
    active: bool = True
    schedule: LinkedInScheduleConfig = Field(default_factory=LinkedInScheduleConfig)
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "account@linkedin.com",
                "password": "secure_password",
                "account_name": "Account 1",
                "active": True,
                "schedule": {
                    "frequency": "daily",
                    "run_time": "02:00",
                    "days_of_week": None,
                    "enabled": True
                }
            }
        }


class LinkedInAccountUpdate(BaseModel):
    """Schema for updating a LinkedIn account"""
    account_name: Optional[str] = None
    active: Optional[bool] = None
    schedule: Optional[LinkedInScheduleConfig] = None


class LinkedInAccountResponse(BaseModel):
    """Schema for LinkedIn account response"""
    id: str = Field(..., alias="_id")
    email: str
    account_name: str
    active: bool
    schedule: LinkedInScheduleConfig
    created_at: datetime
    updated_at: datetime
    last_run: Optional[datetime] = None
    status: str = "idle"  # idle, running, error
    
    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "_id": "507f1f77bcf86cd799439011",
                "email": "account@linkedin.com",
                "account_name": "Account 1",
                "active": True,
                "schedule": {
                    "frequency": "daily",
                    "run_time": "02:00",
                    "days_of_week": None,
                    "enabled": True
                },
                "created_at": "2026-03-03T10:00:00Z",
                "updated_at": "2026-03-03T10:00:00Z",
                "last_run": "2026-03-03T02:15:00Z",
                "status": "idle"
            }
        }


class LinkedInJobResult(BaseModel):
    """Result metrics from a LinkedIn automation job"""
    connections_sent: int = 0
    messages_sent: int = 0
    posts_liked: int = 0
    posts_reposted: int = 0
    posts_commented: int = 0
    errors: List[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
    
    class Config:
        json_schema_extra = {
            "example": {
                "connections_sent": 5,
                "messages_sent": 2,
                "posts_liked": 10,
                "posts_reposted": 3,
                "posts_commented": 2,
                "errors": [],
                "duration_seconds": 245.5
            }
        }


class LinkedInAutomationJob(BaseModel):
    """Schema for an automation job record"""
    id: str = Field(..., alias="_id")
    account_id: str
    task_type: TaskType
    status: JobStatus
    started_at: datetime
    ended_at: Optional[datetime] = None
    results: LinkedInJobResult
    error_message: Optional[str] = None
    
    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "_id": "507f1f77bcf86cd799439012",
                "account_id": "507f1f77bcf86cd799439011",
                "task_type": "all",
                "status": "completed",
                "started_at": "2026-03-03T02:00:00Z",
                "ended_at": "2026-03-03T02:04:05Z",
                "results": {
                    "connections_sent": 5,
                    "messages_sent": 2,
                    "posts_liked": 10,
                    "posts_reposted": 3,
                    "posts_commented": 2,
                    "errors": [],
                    "duration_seconds": 245.0
                },
                "error_message": None
            }
        }


class LinkedInBotConfig(BaseModel):
    """Configuration for the LinkedIn bot execution"""
    max_connections_per_run: int = 10
    max_messages_per_run: int = 5
    max_posts_to_interact: int = 100
    browser_headless: bool = True
    browser_timeout_seconds: int = 20
    scroll_pause_min: float = 3.0
    scroll_pause_max: float = 5.0
    action_pause_min: float = 1.0
    action_pause_max: float = 3.0
    chromedriver_path: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "max_connections_per_run": 10,
                "max_messages_per_run": 5,
                "max_posts_to_interact": 100,
                "browser_headless": True,
                "browser_timeout_seconds": 20,
                "scroll_pause_min": 3.0,
                "scroll_pause_max": 5.0,
                "action_pause_min": 1.0,
                "action_pause_max": 3.0,
                "chromedriver_path": None
            }
        }


class LinkedInOpportunityIngestRequest(BaseModel):
    """Payload for recording and scoring a LinkedIn opportunity candidate"""
    account_id: Optional[str] = None
    message_id: Optional[str] = None
    channel: OpportunityChannel = OpportunityChannel.MESSAGE
    sender_name: str = Field(..., min_length=1)
    sender_profile_url: Optional[str] = None
    sender_company: Optional[str] = None
    sender_title: Optional[str] = None
    message_text: str = Field(..., min_length=1)
    division_hint: Optional[str] = None
    notes: Optional[str] = None


class LinkedInOpportunityUpdate(BaseModel):
    """Fields that can be updated as the opportunity progresses"""
    status: Optional[OpportunityStatus] = None
    division_owner: Optional[str] = None
    notes: Optional[str] = None
    response_draft: Optional[str] = None
    converted_value: Optional[float] = None


class LinkedInOpportunityResponse(BaseModel):
    """Stored LinkedIn opportunity record"""
    id: str = Field(..., alias="_id")
    account_id: Optional[str] = None
    message_id: Optional[str] = None
    channel: OpportunityChannel
    sender_name: str
    sender_profile_url: Optional[str] = None
    sender_company: Optional[str] = None
    sender_title: Optional[str] = None
    message_text: str
    message_excerpt: str
    detected_need: Optional[str] = None
    detected_keywords: List[str] = Field(default_factory=list)
    intent_score: int = 0
    confidence: float = 0.0
    status: OpportunityStatus = OpportunityStatus.DISCOVERED
    division_owner: Optional[str] = None
    response_draft: Optional[str] = None
    notes: Optional[str] = None
    converted_value: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    contacted_at: Optional[datetime] = None
    replied_at: Optional[datetime] = None
    converted_at: Optional[datetime] = None

    class Config:
        populate_by_name = True

