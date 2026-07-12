from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime


class Account(BaseModel):
    name: str
    account_type: str = Field(default="client")
    status: str = Field(default="active")
    owner: Optional[str] = None          # username/email of the record owner
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    tags: List[str] = []
    metadata: Dict[str, Any] = {}
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Contact(BaseModel):
    email: EmailStr
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    name: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    owner: Optional[str] = None
    tags: List[str] = []
    customFields: Dict[str, Any] = {}
    account_id: Optional[str] = None
    created_at: Optional[datetime] = None


class Lead(BaseModel):
    email: Optional[EmailStr] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    name: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    source: Optional[str] = None
    status: str = Field(default="new")   # new | working | converted | disqualified
    owner: Optional[str] = None
    score: Optional[float] = None
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    created_at: Optional[datetime] = None


class Opportunity(BaseModel):
    title: str
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    amount: Optional[float] = 0
    stage: str = Field(default="new")    # new|rfq|qualified|proposal|negotiation|won|lost
    status: str = Field(default="open")  # open|won|lost
    owner: Optional[str] = None
    expected_close_date: Optional[datetime] = None
    probability: Optional[float] = None  # 0-1 override; stage default used when absent
    loss_reason: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None


class Activity(BaseModel):
    type: str                             # note|call|meeting|email_sent|... (free)
    subject: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    contact_id: Optional[str] = None
    account_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    project_id: Optional[str] = None
    lead_id: Optional[str] = None
    created_at: Optional[datetime] = None


class Task(BaseModel):
    title: str
    description: Optional[str] = None
    owner_id: Optional[str] = None       # assignee (username/email)
    status: str = Field(default="pending")  # pending|done
    linked_object_type: Optional[str] = None
    linked_object_id: Optional[str] = None
    due_date: Optional[datetime] = None
    priority: Optional[int] = 3


class Project(BaseModel):
    name: str
    account_id: Optional[str] = None
    status: str = Field(default="draft")
    rfq_id: Optional[str] = None
    budget: Optional[float] = 0
    created_at: Optional[datetime] = None


class Invoice(BaseModel):
    account_id: Optional[str] = None
    project_id: Optional[str] = None
    amount: float = 0
    status: str = Field(default="draft")
    due_date: Optional[datetime] = None
    created_at: Optional[datetime] = None


class AIDecision(BaseModel):
    agent_name: str
    linked_object_type: Optional[str] = None
    linked_object_id: Optional[str] = None
    input_summary: Optional[Dict[str, Any]] = {}
    decision: Optional[str] = None
    confidence: Optional[float] = None
    reason: Optional[str] = None
    recommended_action: Optional[str] = None
    executed_action: Optional[str] = None
    autonomy_mode: Optional[str] = Field(default="observe")
    status: Optional[str] = Field(default="pending")
    created_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None


class Notification(BaseModel):
    type: str                             # rfq_received|task_overdue|opportunity_stale|...
    message: str
    link_object_type: Optional[str] = None
    link_object_id: Optional[str] = None
    owner: Optional[str] = None           # target user; None = everyone
    read: bool = False
    dedupe_key: Optional[str] = None
    created_at: Optional[datetime] = None
