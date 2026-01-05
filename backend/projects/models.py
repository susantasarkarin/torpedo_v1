# backend/projects/models.py
# Pydantic models for Project Management Module

from datetime import datetime, date
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    """Project status values"""
    PLANNING = "planning"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ProjectPriority(str, Enum):
    """Project priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskStatus(str, Enum):
    """Task status values"""
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """Task priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class MilestoneStatus(str, Enum):
    """Milestone status values"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    MISSED = "missed"


class TeamMember(BaseModel):
    """Team member assignment"""
    user_id: str
    user_name: Optional[str] = None
    role: str = "member"  # lead, member, reviewer
    assigned_at: datetime = Field(default_factory=datetime.utcnow)
    assigned_by: Optional[str] = None
    hours_allocated: float = 0


class Milestone(BaseModel):
    """Project milestone"""
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    status: MilestoneStatus = MilestoneStatus.PENDING
    completed_at: Optional[datetime] = None
    deliverables: List[str] = Field(default_factory=list)


class Project(BaseModel):
    """Project entity"""
    id: Optional[str] = None
    
    # Basic info
    name: str
    description: Optional[str] = None
    code: Optional[str] = None  # Project code like PRJ-001
    
    # Status and priority
    status: ProjectStatus = ProjectStatus.PLANNING
    priority: ProjectPriority = ProjectPriority.MEDIUM
    
    # Client/Customer association
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    
    # Related entities
    deal_id: Optional[str] = None  # Associated deal/opportunity
    rfq_id: Optional[str] = None  # Associated RFQ
    
    # Team
    project_lead_id: Optional[str] = None
    project_lead_name: Optional[str] = None
    team_members: List[TeamMember] = Field(default_factory=list)
    
    # Timeline
    start_date: Optional[datetime] = None
    target_end_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    
    # Milestones
    milestones: List[Milestone] = Field(default_factory=list)
    
    # Budget
    budget: float = 0
    budget_spent: float = 0
    budget_currency: str = "USD"
    
    # Progress
    progress_percent: int = 0
    total_tasks: int = 0
    completed_tasks: int = 0
    
    # Tags and categorization
    tags: List[str] = Field(default_factory=list)
    category: Optional[str] = None
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None
    
    # Soft delete
    is_archived: bool = False
    archived_at: Optional[datetime] = None


class ProjectCreate(BaseModel):
    """Request model for creating a project"""
    name: str
    description: Optional[str] = None
    code: Optional[str] = None
    priority: ProjectPriority = ProjectPriority.MEDIUM
    client_id: Optional[str] = None
    deal_id: Optional[str] = None
    rfq_id: Optional[str] = None
    project_lead_id: Optional[str] = None
    start_date: Optional[datetime] = None
    target_end_date: Optional[datetime] = None
    budget: float = 0
    budget_currency: str = "USD"
    tags: List[str] = Field(default_factory=list)
    category: Optional[str] = None


class ProjectUpdate(BaseModel):
    """Request model for updating a project"""
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None
    priority: Optional[ProjectPriority] = None
    client_id: Optional[str] = None
    project_lead_id: Optional[str] = None
    start_date: Optional[datetime] = None
    target_end_date: Optional[datetime] = None
    budget: Optional[float] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None


class Task(BaseModel):
    """Task entity"""
    id: Optional[str] = None
    
    # Basic info
    title: str
    description: Optional[str] = None
    
    # Association
    project_id: str
    milestone_id: Optional[str] = None
    parent_task_id: Optional[str] = None  # For subtasks
    
    # Status and priority
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    
    # Assignment
    assigned_to: Optional[str] = None
    assigned_to_name: Optional[str] = None
    assigned_at: Optional[datetime] = None
    assigned_by: Optional[str] = None
    
    # Timeline
    due_date: Optional[datetime] = None
    start_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Time tracking
    estimated_hours: float = 0
    actual_hours: float = 0
    
    # Dependencies
    depends_on: List[str] = Field(default_factory=list)  # Task IDs
    blocks: List[str] = Field(default_factory=list)  # Task IDs
    
    # Tags
    tags: List[str] = Field(default_factory=list)
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None


class TaskCreate(BaseModel):
    """Request model for creating a task"""
    title: str
    description: Optional[str] = None
    project_id: str
    milestone_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    priority: TaskPriority = TaskPriority.MEDIUM
    assigned_to: Optional[str] = None
    due_date: Optional[datetime] = None
    start_date: Optional[datetime] = None
    estimated_hours: float = 0
    depends_on: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    """Request model for updating a task"""
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    assigned_to: Optional[str] = None
    due_date: Optional[datetime] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    tags: Optional[List[str]] = None


class TimeEntry(BaseModel):
    """Time tracking entry"""
    id: Optional[str] = None
    task_id: str
    project_id: str
    user_id: str
    user_name: Optional[str] = None
    
    # Time
    date: datetime
    hours: float
    description: Optional[str] = None
    
    # Billing
    is_billable: bool = True
    hourly_rate: float = 0
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectStats(BaseModel):
    """Project statistics"""
    total_projects: int = 0
    active_projects: int = 0
    completed_projects: int = 0
    on_hold_projects: int = 0
    
    total_tasks: int = 0
    completed_tasks: int = 0
    overdue_tasks: int = 0
    
    total_budget: float = 0
    total_spent: float = 0
    
    by_status: Dict[str, int] = Field(default_factory=dict)
    by_priority: Dict[str, int] = Field(default_factory=dict)
