"""
Smoke tests for the Phase 5 panel_intelligence_agent.

Covers the pure fraud heuristic and the run that mirrors panel activity into
crm_db.panel_mirror and flags anomalies via the decision engine.
"""

import pytest

pytestmark = pytest.mark.smoke

crm_service = None
ai_engine = None
agent = None
get_database = None
_import_error = None
try:
    from app.services import crm_service as _svc
    from app.services import ai_engine as _ai
    from agents import panel_intelligence_agent as _agent
    from database import get_database as _gd
    crm_service, ai_engine, agent, get_database = _svc, _ai, _agent, _gd
except Exception as e:  # pragma: no cover
    _import_error = e

SRC_DB = "panel_test"


@pytest.fixture(autouse=True)
def _guard():
    if agent is None:
        pytest.skip(f"imports unavailable: {_import_error}")


# ---- pure heuristic ----

def test_rewards_without_completions_is_high():
    a = agent.assess_panelist({"surveys_completed": 0, "rewards_total": 100})
    assert a["risk"] == "high" and "rewards_without_completions" in a["reasons"]


def test_excessive_reward_per_survey_is_high():
    a = agent.assess_panelist({"surveys_completed": 2, "rewards_total": 600})
    assert a["risk"] == "high" and "reward_per_survey_too_high" in a["reasons"]


def test_status_flag_is_high():
    assert agent.assess_panelist({"status": "flagged"})["risk"] == "high"


def test_normal_panelist_is_low():
    assert agent.assess_panelist({"surveys_completed": 10, "rewards_total": 50, "status": "active"})["risk"] == "low"


# ---- run ----

@pytest.fixture()
def env():
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    src = get_database(SRC_DB)["panelists"]
    src.delete_many({})
    src.insert_many([
        {"panelist_id": "p1", "email": "a@x.com", "surveys_completed": 10, "rewards_total": 50, "status": "active"},
        {"panelist_id": "p2", "email": "b@x.com", "surveys_completed": 0, "rewards_total": 100},
        {"panelist_id": "p3", "surveys_completed": 2, "rewards_total": 600, "status": "active"},
    ])
    yield
    crm_service._db().client.drop_database("crm_db_test")
    crm_service._db().client.drop_database(SRC_DB)


def test_run_mirrors_and_flags(env):
    stats = agent.run(source_db=SRC_DB, source_collection="panelists")
    assert stats["scanned"] == 3
    assert stats["mirrored"] == 3
    assert stats["flagged"] == 2  # p2 + p3

    mirror = crm_service._db()["panel_mirror"]
    assert mirror.count_documents({}) == 3
    assert mirror.count_documents({"risk": "high"}) == 2
    # Flagged panelists produced decisions.
    assert crm_service._col("ai_decisions").count_documents(
        {"agent_name": "panel_intelligence_agent"}
    ) == 2


def test_dry_run_writes_nothing(env):
    stats = agent.run(source_db=SRC_DB, source_collection="panelists", dry_run=True)
    assert stats["scanned"] == 3
    assert crm_service._db()["panel_mirror"].count_documents({}) == 0
