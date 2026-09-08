"""
TaskService — the write path for `Task`. Same shape as every other domain
service in this codebase: one error type, `org_id` required and checked on
every id-scoped read/write (Phase 15's tenant-isolation discipline, built in
from the start here rather than retrofitted), one `Activity` per real state
change.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.tasks.models import CANCELLED, DONE, OPEN, TASK_PRIORITIES, Task


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskError(Exception):
    """Invalid priority, a subject_type/subject_id pair supplied only
    half-set, a task not found (or belonging to another org — treated
    identically, never distinguished), or a transition attempted from a
    non-OPEN status. Same discipline as every other domain's single error
    type."""


class TaskService:
    def __init__(self, tasks: CanonicalRepository[Task], activities: CanonicalRepository[Activity]):
        self._tasks = tasks
        self._activities = activities

    async def create_task(
        self, *, org_id: str, actor: str, title: str, description: str | None = None,
        due_at: datetime | None = None, assignee: str | None = None, priority: str | None = None,
        subject_type: str | None = None, subject_id: str | None = None,
    ) -> Task:
        if not title or not title.strip():
            raise TaskError("title must not be empty")
        if priority is not None and priority not in TASK_PRIORITIES:
            raise TaskError(f"unrecognized priority {priority!r} — must be one of {sorted(TASK_PRIORITIES)}")
        if bool(subject_type) != bool(subject_id):
            raise TaskError("subject_type and subject_id must both be set or both be omitted")

        task = await self._tasks.insert(
            Task(
                org_id=org_id, created_by=actor, updated_by=actor, title=title.strip(), description=description,
                due_at=due_at, assignee=assignee, priority=priority, subject_type=subject_type, subject_id=subject_id,
            )
        )
        await self._activity(org_id=org_id, actor=actor, type="task_created", subject_id=task.id, payload={"title": task.title, "assignee": assignee})
        return task

    async def complete_task(self, *, org_id: str, actor: str, task_id: str) -> Task:
        task = await self._get_or_raise(task_id, org_id=org_id)
        if task.status != OPEN:
            raise TaskError(f"task {task_id} is not open (status={task.status})")
        updated = await self._tasks.update(task.id, task.version, {"status": DONE, "completed_at": _utcnow()}, updated_by=actor)
        await self._activity(org_id=org_id, actor=actor, type="task_completed", subject_id=task.id, payload={})
        return updated

    async def cancel_task(self, *, org_id: str, actor: str, task_id: str, reason: str | None = None) -> Task:
        task = await self._get_or_raise(task_id, org_id=org_id)
        if task.status != OPEN:
            raise TaskError(f"task {task_id} is not open (status={task.status})")
        updated = await self._tasks.update(task.id, task.version, {"status": CANCELLED, "cancelled_at": _utcnow(), "cancel_reason": reason}, updated_by=actor)
        await self._activity(org_id=org_id, actor=actor, type="task_cancelled", subject_id=task.id, payload={"reason": reason})
        return updated

    async def list_open_tasks(
        self, *, org_id: str, assignee: str | None = None, overdue_only: bool = False, as_of: datetime | None = None,
    ) -> list[Task]:
        """The deterministic candidate set — real listing, no separate
        dashboard-only query built. `overdue_only` uses `Task.due_at`
        directly; a task with no `due_at` set is never "overdue", it's just
        undated."""
        query: dict = {"org_id": org_id, "status": OPEN}
        if assignee:
            query["assignee"] = assignee
        if overdue_only:
            query["due_at"] = {"$lt": as_of or _utcnow()}
        return await self._tasks.find_all(query)

    async def _get_or_raise(self, task_id: str, *, org_id: str) -> Task:
        task = await self._tasks.get(task_id)
        if task is None or task.org_id != org_id:
            raise TaskError(f"task {task_id} does not exist")
        return task

    async def _activity(self, *, org_id: str, actor: str, type: str, subject_id: str, payload: dict) -> None:
        await self._activities.insert(
            Activity(org_id=org_id, created_by=actor, updated_by=actor, type=type, subject_type="task", subject_id=subject_id, actor_type="user", actor_id=actor, payload=payload)
        )
