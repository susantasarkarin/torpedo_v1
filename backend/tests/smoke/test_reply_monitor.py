"""
Smoke tests for the Phase 5 reply_monitor agent.

Seeds throwaway replies and verifies: approval-gated draft tasks (nothing sent),
contact matching, the draft carried on the task, autopilot still gating (risk=
medium), idempotency, and dry-run safety.
"""

import pytest

pytestmark = pytest.mark.smoke

crm_service = None
ai_engine = None
agent = None
get_database = None
_import_error = None
try:
    from backend.app.services import crm_service as _svc
    from backend.app.services import ai_engine as _ai
    from backend.agents import reply_monitor as _agent
    from backend.database import get_database as _gd
    crm_service, ai_engine, agent, get_database = _svc, _ai, _agent, _gd
except Exception as e:  # pragma: no cover
    _import_error = e

SRC_DB = "crm_src_test"
COL = "outreach_replies"


def _seed():
    col = get_database(SRC_DB)[COL]
    col.delete_many({})
    col.insert_many(
        [
            {"reply_id": "r1", "from_email": "jane@acme.com", "from_name": "Jane Doe",
             "company": "Acme", "subject": "Re: partnership"},
            {"reply_id": "r2", "from_email": "john@globex.com", "subject": "Re: quote"},
            {"reply_id": "r3", "subject": "no sender"},  # skipped: no from_email
        ]
    )


@pytest.fixture()
def env():
    if agent is None:
        pytest.skip(f"imports unavailable: {_import_error}")
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    _seed()
    yield
    crm_service._db().client.drop_database("crm_db_test")
    crm_service._db().client.drop_database(SRC_DB)


def test_dry_run_writes_nothing(env):
    stats = agent.run(dry_run=True, source_db=SRC_DB, replies_collection=COL)
    assert stats["scanned"] == 3
    assert crm_service._col("ai_decisions").count_documents({}) == 0
    assert crm_service._col("contacts").count_documents({}) == 0


def test_approve_gates_draft_then_creates_task(env):
    stats = agent.run(autonomy_mode="approve", source_db=SRC_DB, replies_collection=COL)
    assert stats["processed"] == 2  # r1, r2; r3 skipped (no sender)
    assert stats["skipped_no_sender"] == 1
    assert stats["queued"] == 2
    # Contacts matched/created; no tasks yet (pending approval).
    assert crm_service._col("contacts").count_documents({}) == 2
    assert crm_service._col("tasks").count_documents({}) == 0

    pending = ai_engine.list_queue(status="pending")
    assert len(pending) == 2
    # Draft is carried on the queued action payload.
    assert "draft" in pending[0]["payload"]["metadata"]
    assert pending[0]["payload"]["metadata"]["draft"]

    # Approving creates the review task (still no email sent).
    ai_engine.approve_action(pending[0]["_id"], user="rep")
    assert crm_service._col("tasks").count_documents({}) == 1
    task = crm_service._col("tasks").find_one({})
    assert task["metadata"]["agent"] == "reply_monitor"
    assert task["metadata"]["draft"]


def test_autopilot_still_gates_drafts(env):
    # risk=medium => even autopilot must not auto-execute; it falls back to pending.
    stats = agent.run(autonomy_mode="autopilot", source_db=SRC_DB, replies_collection=COL)
    assert stats["executed"] == 0
    assert stats["queued"] == 2
    assert crm_service._col("tasks").count_documents({}) == 0


def test_idempotent_rerun(env):
    first = agent.run(autonomy_mode="approve", source_db=SRC_DB, replies_collection=COL)
    assert first["processed"] == 2
    second = agent.run(autonomy_mode="approve", source_db=SRC_DB, replies_collection=COL)
    assert second["processed"] == 0
    assert second["skipped_seen"] >= 2
