"""
Smoke tests for the Phase 5 survey_revenue_agent.

Covers the pure expected-revenue scorer (no DB) and the end-to-end run that
ranks seeded surveys and logs a best-survey recommendation via the decision
engine (isolated to throwaway DBs).
"""

import pytest

pytestmark = pytest.mark.smoke

crm_service = None
agent = None
get_database = None
_import_error = None
try:
    from app.services import crm_service as _svc
    from agents import survey_revenue_agent as _agent
    from database import get_database as _gd
    crm_service, agent, get_database = _svc, _agent, _gd
except Exception as e:  # pragma: no cover
    _import_error = e

SURVEY_DB = "survey_allocation_test"


@pytest.fixture(autouse=True)
def _guard():
    if agent is None:
        pytest.skip(f"imports unavailable: {_import_error}")


# ---- pure scorer (no DB) ----

def test_score_uses_conversion_rate_first():
    s = {"cpi": 4.0, "ir": 50}
    m = {"conversion_rate": 25}  # 25% actual conversion
    score = agent.expected_revenue_score(s, m)
    assert score["basis"] == "conversion_rate"
    assert score["p_complete"] == 0.25
    assert score["epc"] == 1.0  # 4.0 * 0.25


def test_score_falls_back_to_ir_then_default():
    assert agent.expected_revenue_score({"cpi": 2.0, "ir": 40})["basis"] == "expected_ir"
    assert agent.expected_revenue_score({"cpi": 2.0, "ir": 40})["epc"] == 0.8
    d = agent.expected_revenue_score({"cpi": 10.0})
    assert d["basis"] == "default"
    assert d["epc"] == round(10.0 * agent.DEFAULT_P_COMPLETE, 4)


def test_rank_orders_by_expected_revenue():
    items = [
        {"survey": {"survey_id": "low", "cpi": 1.0, "ir": 20}},   # epc 0.2
        {"survey": {"survey_id": "high", "cpi": 5.0, "ir": 40}},  # epc 2.0
        {"survey": {"survey_id": "mid", "cpi": 3.0, "ir": 30}},   # epc 0.9
    ]
    ranked = agent.rank_surveys(items)
    assert [r["survey_id"] for r in ranked] == ["high", "mid", "low"]


# ---- end-to-end run (DB) ----

@pytest.fixture()
def env():
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    db = get_database(SURVEY_DB)
    db["surveys"].delete_many({})
    db["survey_metrics"].delete_many({})
    db["surveys"].insert_many([
        {"survey_id": "s1", "name": "Cheap low IR", "status": "active", "cpi": 1.0, "ir": 20, "remaining_quota": 100},
        {"survey_id": "s2", "name": "Rich high IR", "status": "active", "cpi": 6.0, "ir": 45, "remaining_quota": 50},
        {"survey_id": "s3", "name": "Paused", "status": "paused", "cpi": 9.0, "ir": 90, "remaining_quota": 10},
    ])
    # s1 has strong actual conversion that should still not beat s2's economics.
    db["survey_metrics"].insert_one({"survey_id": "s1", "conversion_rate": 30})
    yield
    crm_service._db().client.drop_database("crm_db_test")
    crm_service._db().client.drop_database(SURVEY_DB)


def test_run_recommends_best_active_survey(env):
    stats = agent.run(autonomy_mode="recommend", source_db=SURVEY_DB)
    # Only the 2 active surveys are scored (paused excluded).
    assert stats["scanned"] == 2
    # s2 epc = 6*0.45 = 2.7 ; s1 epc = 1*0.30 = 0.30 -> s2 wins.
    assert stats["best"]["survey_id"] == "s2"
    assert stats["decision_id"]
    # A recommendation task was created, linked to the survey.
    task = crm_service._col("tasks").find_one({})
    assert task is not None
    assert task["linked_object_id"] == "s2"
    # The decision is logged and explainable.
    dec = crm_service.get("ai_decisions", stats["decision_id"])
    assert dec["agent_name"] == "survey_revenue_agent"
    assert dec["input_summary"]["top"]


def test_dry_run_logs_nothing(env):
    stats = agent.run(source_db=SURVEY_DB, dry_run=True)
    assert stats["scanned"] == 2
    assert stats["best"]["survey_id"] == "s2"
    assert stats["decision_id"] is None
    assert crm_service._col("ai_decisions").count_documents({}) == 0
