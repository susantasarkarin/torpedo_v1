"""
TaskService — the checklist's own generic Task/reminder entity, built
2026-09-08. Same pattern as every other domain's service tests: creation,
transitions, tenant isolation, and the deterministic candidate-list query.
"""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.tasks.models import CANCELLED, DONE, OPEN, Task
from app.tasks.service import TaskError, TaskService

ORG = "org-A"
ACTOR = "alice"


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def activities(db) -> CanonicalRepository[Activity]:
    return CanonicalRepository(db["activities"], Activity)


@pytest.fixture
def svc(db, activities) -> TaskService:
    return TaskService(CanonicalRepository(db["tasks"], Task), activities)


@pytest.mark.asyncio
async def test_create_task_with_minimal_fields(svc: TaskService):
    task = await svc.create_task(org_id=ORG, actor=ACTOR, title="Follow up with client")
    assert task.title == "Follow up with client"
    assert task.status == OPEN
    assert task.priority is None
    assert task.assignee is None


@pytest.mark.asyncio
async def test_create_task_records_an_activity(svc: TaskService, activities):
    task = await svc.create_task(org_id=ORG, actor=ACTOR, title="Chase invoice")
    logged = await activities.find_all({"type": "task_created", "subject_id": task.id})
    assert len(logged) == 1
    assert logged[0].payload["title"] == "Chase invoice"


@pytest.mark.asyncio
async def test_create_task_with_blank_title_is_rejected(svc: TaskService):
    with pytest.raises(TaskError):
        await svc.create_task(org_id=ORG, actor=ACTOR, title="   ")


@pytest.mark.asyncio
async def test_create_task_with_an_unrecognized_priority_is_rejected(svc: TaskService):
    with pytest.raises(TaskError):
        await svc.create_task(org_id=ORG, actor=ACTOR, title="x", priority="URGENT")


@pytest.mark.asyncio
async def test_create_task_with_a_real_priority_succeeds(svc: TaskService):
    task = await svc.create_task(org_id=ORG, actor=ACTOR, title="x", priority="HIGH")
    assert task.priority == "HIGH"


@pytest.mark.asyncio
async def test_subject_type_without_subject_id_is_rejected(svc: TaskService):
    with pytest.raises(TaskError):
        await svc.create_task(org_id=ORG, actor=ACTOR, title="x", subject_type="invoice")


@pytest.mark.asyncio
async def test_subject_id_without_subject_type_is_rejected(svc: TaskService):
    with pytest.raises(TaskError):
        await svc.create_task(org_id=ORG, actor=ACTOR, title="x", subject_id="inv-1")


@pytest.mark.asyncio
async def test_task_can_be_linked_to_another_entity(svc: TaskService):
    task = await svc.create_task(org_id=ORG, actor=ACTOR, title="Chase overdue invoice", subject_type="invoice", subject_id="inv-42")
    assert task.subject_type == "invoice"
    assert task.subject_id == "inv-42"


@pytest.mark.asyncio
async def test_complete_task_moves_it_to_done_and_stamps_completed_at(svc: TaskService):
    task = await svc.create_task(org_id=ORG, actor=ACTOR, title="x")
    completed = await svc.complete_task(org_id=ORG, actor=ACTOR, task_id=task.id)
    assert completed.status == DONE
    assert completed.completed_at is not None


@pytest.mark.asyncio
async def test_a_completed_task_cannot_be_completed_again(svc: TaskService):
    task = await svc.create_task(org_id=ORG, actor=ACTOR, title="x")
    await svc.complete_task(org_id=ORG, actor=ACTOR, task_id=task.id)
    with pytest.raises(TaskError):
        await svc.complete_task(org_id=ORG, actor=ACTOR, task_id=task.id)


@pytest.mark.asyncio
async def test_cancel_task_moves_it_to_cancelled_with_a_reason(svc: TaskService):
    task = await svc.create_task(org_id=ORG, actor=ACTOR, title="x")
    cancelled = await svc.cancel_task(org_id=ORG, actor=ACTOR, task_id=task.id, reason="no longer relevant")
    assert cancelled.status == CANCELLED
    assert cancelled.cancel_reason == "no longer relevant"
    assert cancelled.cancelled_at is not None


@pytest.mark.asyncio
async def test_a_done_task_cannot_be_cancelled(svc: TaskService):
    task = await svc.create_task(org_id=ORG, actor=ACTOR, title="x")
    await svc.complete_task(org_id=ORG, actor=ACTOR, task_id=task.id)
    with pytest.raises(TaskError):
        await svc.cancel_task(org_id=ORG, actor=ACTOR, task_id=task.id)


@pytest.mark.asyncio
async def test_completing_a_missing_task_raises(svc: TaskService):
    with pytest.raises(TaskError):
        await svc.complete_task(org_id=ORG, actor=ACTOR, task_id="does-not-exist")


@pytest.mark.asyncio
async def test_list_open_tasks_excludes_completed_and_cancelled(svc: TaskService):
    open_task = await svc.create_task(org_id=ORG, actor=ACTOR, title="still open")
    done_task = await svc.create_task(org_id=ORG, actor=ACTOR, title="done")
    await svc.complete_task(org_id=ORG, actor=ACTOR, task_id=done_task.id)

    open_tasks = await svc.list_open_tasks(org_id=ORG)
    assert [t.id for t in open_tasks] == [open_task.id]


@pytest.mark.asyncio
async def test_list_open_tasks_can_be_narrowed_to_one_assignee(svc: TaskService):
    await svc.create_task(org_id=ORG, actor=ACTOR, title="mine", assignee="bob")
    await svc.create_task(org_id=ORG, actor=ACTOR, title="not mine", assignee="carol")

    bobs_tasks = await svc.list_open_tasks(org_id=ORG, assignee="bob")
    assert len(bobs_tasks) == 1
    assert bobs_tasks[0].assignee == "bob"


@pytest.mark.asyncio
async def test_list_open_tasks_overdue_only_excludes_undated_and_future_tasks(svc: TaskService):
    now = datetime.now(timezone.utc)
    overdue = await svc.create_task(org_id=ORG, actor=ACTOR, title="overdue", due_at=now - timedelta(days=1))
    await svc.create_task(org_id=ORG, actor=ACTOR, title="future", due_at=now + timedelta(days=1))
    await svc.create_task(org_id=ORG, actor=ACTOR, title="undated")  # no due_at at all — never "overdue"

    results = await svc.list_open_tasks(org_id=ORG, overdue_only=True, as_of=now)
    assert [t.id for t in results] == [overdue.id]


# --------------------------------------------------------------------------- tenant isolation


@pytest.mark.asyncio
async def test_list_open_tasks_never_crosses_orgs(svc: TaskService):
    await svc.create_task(org_id=ORG, actor=ACTOR, title="mine")
    await svc.create_task(org_id="org-B", actor="mallory", title="not mine")

    tasks = await svc.list_open_tasks(org_id=ORG)
    assert len(tasks) == 1


@pytest.mark.asyncio
async def test_cannot_complete_another_orgs_task(svc: TaskService):
    other_orgs_task = await svc.create_task(org_id="org-B", actor="mallory", title="victim's task")

    with pytest.raises(TaskError):
        await svc.complete_task(org_id=ORG, actor="attacker", task_id=other_orgs_task.id)

    untouched = await svc._tasks.get(other_orgs_task.id)
    assert untouched.status == OPEN


@pytest.mark.asyncio
async def test_cannot_cancel_another_orgs_task(svc: TaskService):
    other_orgs_task = await svc.create_task(org_id="org-B", actor="mallory", title="victim's task")

    with pytest.raises(TaskError):
        await svc.cancel_task(org_id=ORG, actor="attacker", task_id=other_orgs_task.id)

    untouched = await svc._tasks.get(other_orgs_task.id)
    assert untouched.status == OPEN
