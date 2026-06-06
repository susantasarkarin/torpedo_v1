from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime


class Account(BaseModel):
    name: str
    account_type: str = Field(default="client")
    status: str = Field(default="active")
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
    phone: Optional[str] = None
    company: Optional[str] = None
    tags: List[str] = []
    customFields: Dict[str, Any] = {}
    account_id: Optional[str] = None
    created_at: Optional[datetime] = None


class Lead(BaseModel):
    email: Optional[EmailStr] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    company: Optional[str] = None
    source: Optional[str] = None
    status: str = Field(default="new")
    score: Optional[float] = None
    created_at: Optional[datetime] = None


class Opportunity(BaseModel):
    title: str
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    amount: Optional[float] = 0
    stage: str = Field(default="new")
    status: str = Field(default="open")
    created_at: Optional[datetime] = None


class Activity(BaseModel):
    type: str
    subject: Optional[str] = None
    description: Optional[str] = None
    contact_id: Optional[str] = None
    account_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    project_id: Optional[str] = None
    created_at: Optional[datetime] = None


class Task(BaseModel):
    title: str
    owner_id: Optional[str] = None
    status: str = Field(default="pending")
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
