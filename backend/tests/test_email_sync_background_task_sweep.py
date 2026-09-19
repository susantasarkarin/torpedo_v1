"""
Covers a 2026-09-19 fix to email_sync/router.py: _background_tasks was
populated on every mailbox backfill/re-categorization trigger and never
cleaned up -- grepping the whole file found zero deletions. Identified
(alongside leads/ai_classifier.py's _classification_cache) as a concrete
cause of the API's observed memory growth.

Fixed with an opportunistic sweep (called when a new task is created) that
removes completed/failed tasks past a TTL. Pending/running tasks, and
recently-finished ones, are never touched.
"""
import importlib
from datetime import datetime, timedelta

# email_sync/__init__.py does `from .router import router`, which rebinds
# the `router` attribute on the email_sync package object to the APIRouter
# instance -- `import email_sync.router as m` would then resolve `m` to
# that instance, not the module. importlib.import_module always returns
# the real module from sys.modules, sidestepping that rebind.
m = importlib.import_module("email_sync.router")


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def setup_function():
    m._background_tasks.clear()


def test_sweep_removes_old_completed_task():
    old = datetime.utcnow() - timedelta(seconds=m._BACKGROUND_TASK_TTL_SECONDS + 60)
    m._background_tasks["t1"] = {"status": "completed", "completed_at": _iso(old)}

    m._sweep_finished_background_tasks()

    assert "t1" not in m._background_tasks


def test_sweep_keeps_recent_completed_task():
    recent = datetime.utcnow() - timedelta(seconds=60)
    m._background_tasks["t2"] = {"status": "completed", "completed_at": _iso(recent)}

    m._sweep_finished_background_tasks()

    assert "t2" in m._background_tasks


def test_sweep_never_removes_running_or_pending_tasks_regardless_of_age():
    ancient = datetime.utcnow() - timedelta(days=30)
    m._background_tasks["running"] = {"status": "running", "started_at": _iso(ancient)}
    m._background_tasks["pending"] = {"status": "pending", "created_at": _iso(ancient)}

    m._sweep_finished_background_tasks()

    assert "running" in m._background_tasks
    assert "pending" in m._background_tasks


def test_sweep_removes_old_failed_task():
    old = datetime.utcnow() - timedelta(seconds=m._BACKGROUND_TASK_TTL_SECONDS + 60)
    m._background_tasks["t3"] = {"status": "failed", "completed_at": _iso(old)}

    m._sweep_finished_background_tasks()

    assert "t3" not in m._background_tasks


def test_sweep_tolerates_missing_or_malformed_timestamps():
    m._background_tasks["no_timestamp"] = {"status": "completed"}
    m._background_tasks["bad_timestamp"] = {"status": "completed", "completed_at": "not-a-date"}

    # Must not raise.
    m._sweep_finished_background_tasks()

    # Neither is removed -- we can't judge their age, so err on keeping them
    # rather than risk dropping something a client is still polling.
    assert "no_timestamp" in m._background_tasks
    assert "bad_timestamp" in m._background_tasks
