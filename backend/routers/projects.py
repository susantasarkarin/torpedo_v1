# backend/routers/projects.py
# REST API endpoints for Project Management

from fastapi import APIRouter, HTTPException, Query, Depends, Request
from typing import Optional, List
from datetime import datetime

from database import get_db
from projects.models import (
    ProjectCreate, ProjectUpdate, ProjectStatus, ProjectPriority,
    TaskCreate, TaskUpdate, TaskStatus, TaskPriority,
    MilestoneStatus
)
from projects.service import ProjectService
from rbac.decorators import require_permission
from rbac.permissions import Permissions
from auth import get_current_user

router = APIRouter(prefix="/api/projects", tags=["Projects"])


def get_project_service():
    """Get project service instance"""
    db = get_db()
    return ProjectService(db)


# ==================== PROJECTS ====================

@router.post("")
@require_permission(Permissions.OPS_PROJECT_CREATE)
async def create_project(request: Request, data: ProjectCreate, current_user: dict = Depends(get_current_user)):
    """Create a new project"""
    service = get_project_service()
    user_id = str(current_user.get("_id", current_user.get("id", "")))
    project = service.create_project(data, created_by=user_id)
    return {"success": True, "data": project}


@router.get("")
@require_permission(Permissions.OPS_PROJECT_READ)
async def list_projects(
    request: Request,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    client_id: Optional[str] = None,
    project_lead_id: Optional[str] = None,
    include_archived: bool = False,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200)
):
    """List projects with filters"""
    service = get_project_service()
    result = service.list_projects(
        status=status,
        priority=priority,
        client_id=client_id,
        project_lead_id=project_lead_id,
        include_archived=include_archived,
        skip=skip,
        limit=limit
    )
    return {"success": True, **result}


@router.get("/stats")
@require_permission(Permissions.OPS_PROJECT_READ)
async def get_project_stats(request: Request, client_id: Optional[str] = None):
    """Get project statistics"""
    service = get_project_service()
    stats = service.get_project_stats(client_id=client_id)
    return {"success": True, "data": stats.model_dump()}


@router.get("/my-tasks")
def get_my_tasks(
    include_completed: bool = False,
    current_user: dict = Depends(get_current_user)
):
    """Get tasks assigned to current user"""
    service = get_project_service()
    user_id = str(current_user.get("_id", current_user.get("id", "")))
    tasks = service.get_my_tasks(user_id, include_completed=include_completed)
    return {"success": True, "data": tasks}


@router.get("/{project_id}")
@require_permission(Permissions.OPS_PROJECT_READ)
async def get_project(request: Request, project_id: str):
    """Get a project by ID"""
    service = get_project_service()
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"success": True, "data": project}


@router.put("/{project_id}")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
async def update_project(request: Request, project_id: str, data: ProjectUpdate, current_user: dict = Depends(get_current_user)):
    """Update a project"""
    service = get_project_service()
    user_id = str(current_user.get("_id", current_user.get("id", "")))
    project = service.update_project(project_id, data, updated_by=user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"success": True, "data": project}


@router.patch("/{project_id}/status")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
async def update_project_status(request: Request, project_id: str, status: ProjectStatus):
    """Update project status"""
    service = get_project_service()
    project = service.update_project_status(project_id, status)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"success": True, "data": project}


@router.post("/{project_id}/archive")
@require_permission(Permissions.OPS_PROJECT_DELETE)
async def archive_project(request: Request, project_id: str):
    """Archive a project"""
    service = get_project_service()
    success = service.archive_project(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"success": True, "message": "Project archived"}


@router.delete("/{project_id}")
@require_permission(Permissions.OPS_PROJECT_DELETE)
async def delete_project(request: Request, project_id: str):
    """Permanently delete a project"""
    service = get_project_service()
    success = service.delete_project(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"success": True, "message": "Project deleted"}


# ==================== TEAM MANAGEMENT ====================

@router.post("/{project_id}/team")
@require_permission(Permissions.OPS_PROJECT_ASSIGN)
async def add_team_member(
    request: Request,
    project_id: str,
    user_id: str,
    user_name: str,
    role: str = "member",
    hours_allocated: float = 0,
    current_user: dict = Depends(get_current_user)
):
    """Add a team member to a project"""
    service = get_project_service()
    assigned_by = str(current_user.get("_id", current_user.get("id", "")))
    project = service.add_team_member(
        project_id=project_id,
        user_id=user_id,
        user_name=user_name,
        role=role,
        hours_allocated=hours_allocated,
        assigned_by=assigned_by
    )
    if not project:
        raise HTTPException(status_code=400, detail="Failed to add team member or member already exists")
    return {"success": True, "data": project}


@router.delete("/{project_id}/team/{user_id}")
@require_permission(Permissions.OPS_PROJECT_ASSIGN)
async def remove_team_member(request: Request, project_id: str, user_id: str):
    """Remove a team member from a project"""
    service = get_project_service()
    project = service.remove_team_member(project_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"success": True, "data": project}


# ==================== MILESTONES ====================

@router.post("/{project_id}/milestones")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
async def add_milestone(
    request: Request,
    project_id: str,
    name: str,
    description: Optional[str] = None,
    due_date: Optional[datetime] = None,
    deliverables: Optional[List[str]] = None
):
    """Add a milestone to a project"""
    service = get_project_service()
    project = service.add_milestone(
        project_id=project_id,
        name=name,
        description=description,
        due_date=due_date,
        deliverables=deliverables
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"success": True, "data": project}


@router.patch("/{project_id}/milestones/{milestone_id}")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
async def update_milestone(
    request: Request,
    project_id: str,
    milestone_id: str,
    status: Optional[MilestoneStatus] = None,
    name: Optional[str] = None,
    due_date: Optional[datetime] = None
):
    """Update a milestone"""
    service = get_project_service()
    project = service.update_milestone(
        project_id=project_id,
        milestone_id=milestone_id,
        status=status,
        name=name,
        due_date=due_date
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project or milestone not found")
    return {"success": True, "data": project}


# ==================== TASKS ====================

@router.post("/tasks")
@require_permission(Permissions.OPS_PROJECT_CREATE)
async def create_task(request: Request, data: TaskCreate, current_user: dict = Depends(get_current_user)):
    """Create a new task"""
    service = get_project_service()
    user_id = str(current_user.get("_id", current_user.get("id", "")))
    task = service.create_task(data, created_by=user_id)
    return {"success": True, "data": task}


@router.get("/tasks")
@require_permission(Permissions.OPS_PROJECT_READ)
async def list_tasks(
    request: Request,
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
    milestone_id: Optional[str] = None,
    parent_task_id: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500)
):
    """List tasks with filters"""
    service = get_project_service()
    result = service.list_tasks(
        project_id=project_id,
        status=status,
        priority=priority,
        assigned_to=assigned_to,
        milestone_id=milestone_id,
        parent_task_id=parent_task_id,
        skip=skip,
        limit=limit
    )
    return {"success": True, **result}


@router.get("/tasks/{task_id}")
@require_permission(Permissions.OPS_PROJECT_READ)
async def get_task(request: Request, task_id: str):
    """Get a task by ID"""
    service = get_project_service()
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": True, "data": task}


@router.get("/tasks/{task_id}/subtasks")
@require_permission(Permissions.OPS_PROJECT_READ)
async def get_subtasks(request: Request, task_id: str):
    """Get subtasks of a task"""
    service = get_project_service()
    subtasks = service.get_subtasks(task_id)
    return {"success": True, "data": subtasks}


@router.put("/tasks/{task_id}")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
async def update_task(request: Request, task_id: str, data: TaskUpdate, current_user: dict = Depends(get_current_user)):
    """Update a task"""
    service = get_project_service()
    user_id = str(current_user.get("_id", current_user.get("id", "")))
    task = service.update_task(task_id, data, updated_by=user_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": True, "data": task}


@router.patch("/tasks/{task_id}/status")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
async def update_task_status(request: Request, task_id: str, status: TaskStatus):
    """Update task status"""
    service = get_project_service()
    task = service.update_task_status(task_id, status)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": True, "data": task}


@router.delete("/tasks/{task_id}")
@require_permission(Permissions.OPS_PROJECT_DELETE)
async def delete_task(request: Request, task_id: str):
    """Delete a task"""
    service = get_project_service()
    success = service.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": True, "message": "Task deleted"}


# ==================== TIME TRACKING ====================

@router.post("/tasks/{task_id}/time")
@require_permission(Permissions.OPS_PROJECT_UPDATE)
async def log_time(
    request: Request,
    task_id: str,
    hours: float,
    date: Optional[datetime] = None,
    description: Optional[str] = None,
    is_billable: bool = True,
    hourly_rate: float = 0,
    current_user: dict = Depends(get_current_user)
):
    """Log time entry for a task"""
    service = get_project_service()
    user_id = str(current_user.get("_id", current_user.get("id", "")))
    try:
        entry = service.log_time(
            task_id=task_id,
            user_id=user_id,
            hours=hours,
            date=date,
            description=description,
            is_billable=is_billable,
            hourly_rate=hourly_rate
        )
        return {"success": True, "data": entry}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{project_id}/time-entries")
@require_permission(Permissions.OPS_PROJECT_READ)
async def get_project_time_entries(
    request: Request,
    project_id: str,
    user_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
):
    """Get time entries for a project"""
    service = get_project_service()
    entries = service.get_time_entries(
        project_id=project_id,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date
    )
    return {"success": True, "data": entries}
