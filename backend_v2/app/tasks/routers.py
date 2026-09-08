"""
HTTP surface for Task/reminder. Same discipline as every prior slice:
`org_id` always derives from the resolved identity, every write permission-
gated, 404-not-403 on cross-org reads.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import require_permission
from app.db import get_database
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.rbac.identity import ResolvedIdentity
from app.rbac.permissions import TASK_CREATE, TASK_MANAGE, TASK_READ
from app.tasks.models import Task
from app.tasks.service import TaskError, TaskService

router = APIRouter()


def get_task_service() -> TaskService:
    db = get_database()
    return TaskService(CanonicalRepository(db["tasks"], Task), CanonicalRepository(db["activities"], Activity))


class CreateTaskRequest(BaseModel):
    title: str
    description: str | None = None
    due_at: datetime | None = None
    assignee: str | None = None
    priority: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None


class CancelTaskRequest(BaseModel):
    reason: str | None = None


@router.post("/tasks", response_model=Task)
async def create_task(body: CreateTaskRequest, identity: ResolvedIdentity = Depends(require_permission(TASK_CREATE)), svc: TaskService = Depends(get_task_service)) -> Task:
    try:
        return await svc.create_task(
            org_id=identity.org_id, actor=identity.user_id, title=body.title, description=body.description,
            due_at=body.due_at, assignee=body.assignee, priority=body.priority,
            subject_type=body.subject_type, subject_id=body.subject_id,
        )
    except TaskError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/tasks", response_model=list[Task])
async def list_open_tasks(
    assignee: str | None = None, overdue_only: bool = False,
    identity: ResolvedIdentity = Depends(require_permission(TASK_READ)),
    svc: TaskService = Depends(get_task_service),
) -> list[Task]:
    return await svc.list_open_tasks(org_id=identity.org_id, assignee=assignee, overdue_only=overdue_only)


@router.get("/tasks/{task_id}", response_model=Task)
async def get_task(task_id: str, identity: ResolvedIdentity = Depends(require_permission(TASK_READ)), svc: TaskService = Depends(get_task_service)) -> Task:
    task = await svc._tasks.get(task_id)
    if task is None or task.org_id != identity.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return task


@router.post("/tasks/{task_id}/complete", response_model=Task)
async def complete_task(task_id: str, identity: ResolvedIdentity = Depends(require_permission(TASK_MANAGE)), svc: TaskService = Depends(get_task_service)) -> Task:
    try:
        return await svc.complete_task(org_id=identity.org_id, actor=identity.user_id, task_id=task_id)
    except TaskError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/tasks/{task_id}/cancel", response_model=Task)
async def cancel_task(task_id: str, body: CancelTaskRequest, identity: ResolvedIdentity = Depends(require_permission(TASK_MANAGE)), svc: TaskService = Depends(get_task_service)) -> Task:
    try:
        return await svc.cancel_task(org_id=identity.org_id, actor=identity.user_id, task_id=task_id, reason=body.reason)
    except TaskError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
