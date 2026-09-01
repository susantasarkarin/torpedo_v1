"""
Smoke tests for the Phase 5 follow_up_agent.

Seeds opportunities with controlled timestamps in a throwaway crm_db and verifies
stale detection, mode behaviour (recommend creates task; approve gates it),
de-spam guards (cooldown + existing-task), and dry-run safety.
"""

from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.smoke

crm_service = None
agent = None
ai_engine = None
_import_error = None
try:
    from app.services import crm_service as _svc
    from app.services import ai_engine as _ai
    from agents import follow_up_agent as _agent
    crm_service, ai_engine, agent = _svc, _ai, _agent
except Exception as e:  # pragma: no cover
    _import_error = e


def _insert_opp(title, status, age_days):
    """Insert an opportunity directly with an aged updated_at/created_at."""
    ts = datetime.utcnow() - timedelta(days=age_days)
    res = crm_service._col("opportunities").insert_one(
        {"title": title, "status": status, "stage": "new", "created_at": ts, "updated_at": ts}
    )
    return str(res.inserted_id)


@pytest.fixture()
def env():
    if agent is None:
        pytest.skip(f"imports unavailable: {_import_error}")
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    # stale (30d old, open), warm (2d old, open), closed (30d old, won)
    ids = {
        "stale": _insert_opp("Stale Deal", "open", 30),
        "warm": _insert_opp("Warm Deal", "open", 2),
        "closed": _insert_opp("Closed Deal", "won", 30),
    }
    yield ids
    crm_service._db().client.drop_database("crm_db_test")


def test_dry_run_writes_nothing(env):
    stats = agent.run(dry_run=True, stale_days=14)
    assert stats["scanned"] == 2  # only open opps (closed excluded by query)
    assert stats["stale_found"] == 1  # only the 30d-old open one
    assert crm_service._col("tasks").count_documents({}) == 0
    assert crm_service._col("ai_decisions").count_documents({}) == 0


def test_recommend_creates_followup_task(env):
    stats = agent.run(autonomy_mode="recommend", stale_days=14)
    assert stats["stale_found"] == 1
    assert stats["recommended"] == 1
    task = crm_service._col("tasks").find_one({})
    assert task is not None
    assert task["linked_object_type"] == "opportunity"
    assert task["linked_object_id"] == env["stale"]
    assert task["metadata"]["agent"] == "follow_up_agent"
    # The warm and closed opps produced no tasks.
    assert crm_service._col("tasks").count_documents({}) == 1


def test_idempotent_does_not_double_nudge(env):
    first = agent.run(autonomy_mode="recommend", stale_days=14)
    assert first["recommended"] == 1

    second = agent.run(autonomy_mode="recommend", stale_days=14)
    assert second["recommended"] == 0
    # Skipped because already nudged recently AND/OR has an open task.
    assert second["skipped_recent"] + second["skipped_has_task"] >= 1
    assert crm_service._col("tasks").count_documents({}) == 1


def test_approve_mode_gates_task(env):
    stats = agent.run(autonomy_mode="approve", stale_days=14)
    assert stats["queued"] == 1
    # No task created yet — it's pending approval.
    assert crm_service._col("tasks").count_documents({}) == 0
    pending = ai_engine.list_queue(status="pending")
    assert len(pending) == 1
    ai_engine.approve_action(pending[0]["_id"], user="manager")
    # Now the follow-up task exists.
    assert crm_service._col("tasks").count_documents({}) == 1
