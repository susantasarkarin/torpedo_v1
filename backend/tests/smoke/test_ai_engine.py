"""
Smoke tests for the Phase 4 AI decision engine.

Covers the four autonomy modes and the approval gate, isolated to a throwaway
crm_db. Verifies the core safety guarantee: nothing executes without either
human approval (approve mode) or an explicit low-risk autopilot action.
"""

import pytest

pytestmark = pytest.mark.smoke

crm_service = None
ai = None
_import_error = None
try:
    from backend.app.services import crm_service as _svc
    from backend.app.services import ai_engine as _ai
    crm_service = _svc
    ai = _ai
except Exception as e:  # pragma: no cover
    _import_error = e


@pytest.fixture()
def engine():
    if ai is None:
        pytest.skip(f"ai_engine unavailable: {_import_error}")
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    yield ai
    crm_service._db().client.drop_database("crm_db_test")


def test_observe_mode_logs_only(engine):
    out = engine.submit_decision(
        "old_mail_classifier", decision="classify", autonomy_mode="observe"
    )
    assert out["decision"]["status"] == "observed"
    assert out["queued"] is None and out["executed"] is None and out["task"] is None
    # No action queued.
    assert crm_service._db()[ai.QUEUE_COLLECTION].count_documents({}) == 0


def test_recommend_mode_creates_task(engine):
    out = engine.submit_decision(
        "follow_up_agent",
        decision="follow up gap detected",
        recommended_action="Call the client",
        autonomy_mode="recommend",
        linked_object_type="account",
        linked_object_id="acc123",
    )
    assert out["decision"]["status"] == "recommended"
    assert out["task"]["title"] == "Call the client"
    assert out["task"]["metadata"]["source"] == "ai"
    assert crm_service._col("tasks").count_documents({}) == 1


def test_approve_mode_parks_pending_until_approved(engine):
    out = engine.submit_decision(
        "reply_monitor",
        decision="draft reply",
        action_type="create_task",
        action_payload={"title": "Send drafted reply"},
        autonomy_mode="approve",
        risk="low",
    )
    queued = out["queued"]
    assert queued is not None and queued["status"] == "pending"
    assert out["executed"] is None
    # Nothing executed yet — no task created.
    assert crm_service._col("tasks").count_documents({}) == 0

    # Human approves -> action executes.
    result = engine.approve_action(queued["_id"], user="alice")
    assert result["status"] == "executed"
    assert result["decided_by"] == "alice"
    assert crm_service._col("tasks").count_documents({}) == 1
    # Linked decision is marked executed.
    dec = crm_service.get("ai_decisions", queued["decision_id"])
    assert dec["status"] == "executed"


def test_reject_blocks_execution(engine):
    out = engine.submit_decision(
        "reply_monitor",
        decision="draft reply",
        action_type="create_task",
        action_payload={"title": "Nope"},
        autonomy_mode="approve",
    )
    queued = out["queued"]
    result = engine.reject_action(queued["_id"], user="bob", reason="not appropriate")
    assert result["status"] == "rejected"
    assert crm_service._col("tasks").count_documents({}) == 0
    dec = crm_service.get("ai_decisions", queued["decision_id"])
    assert dec["status"] == "rejected"

    # Cannot approve an already-decided item.
    with pytest.raises(ValueError):
        engine.approve_action(queued["_id"], user="bob")


def test_autopilot_executes_low_risk_only(engine):
    # Low-risk + allowed action -> executes immediately.
    low = engine.submit_decision(
        "follow_up_agent",
        decision="auto follow-up",
        action_type="create_task",
        action_payload={"title": "Auto task"},
        autonomy_mode="autopilot",
        risk="low",
    )
    assert low["executed"] is not None and low["executed"]["status"] == "executed"
    assert crm_service._col("tasks").count_documents({"title": "Auto task"}) == 1

    # High-risk -> falls back to pending approval, does NOT execute.
    high = engine.submit_decision(
        "follow_up_agent",
        decision="risky action",
        action_type="create_task",
        action_payload={"title": "Risky task"},
        autonomy_mode="autopilot",
        risk="high",
    )
    assert high["executed"] is None
    assert high["queued"]["status"] == "pending"
    assert crm_service._col("tasks").count_documents({"title": "Risky task"}) == 0
