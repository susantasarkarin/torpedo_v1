"""
Smoke tests for cint_intelligence_agent's live run() -- mirrors
tests/smoke/test_panel_intelligence_agent.py's structure exactly. Covers the
aggregation + mirror + flag path against a real (test) Mongo, not the pure
scorer (already unit-tested in tests/test_cint_intelligence_agent.py).
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
    from agents import cint_intelligence_agent as _agent
    from database import get_database as _gd
    crm_service, ai_engine, agent, get_database = _svc, _ai, _agent, _gd
except Exception as e:  # pragma: no cover
    _import_error = e

SRC_DB = "cint_test"


@pytest.fixture(autouse=True)
def _guard():
    if agent is None:
        pytest.skip(f"imports unavailable: {_import_error}")


@pytest.fixture()
def env():
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    src = get_database(SRC_DB)["cint_surveys"]
    src.delete_many({})
    # Strong buyer: high conversion, low deactivation.
    src.insert_many([
        {"account_name": "GoodBuyer", "conversion": 5.0, "is_active": True}
        for _ in range(15)
    ] + [
        {"account_name": "GoodBuyer", "conversion": 5.0, "is_active": False}
        for _ in range(2)
    ] + [
        # Underperforming buyer: near-zero conversion, high deactivation,
        # above MIN_SURVEYS_FOR_SCORING so it's eligible to be flagged.
        {"account_name": "BadBuyer", "conversion": 0.01, "is_active": False}
        for _ in range(12)
    ] + [
        {"account_name": "BadBuyer", "conversion": 0.01, "is_active": True}
        for _ in range(2)
    ] + [
        # Below MIN_SURVEYS_FOR_SCORING -- should score but not flag.
        {"account_name": "TinyBuyer", "conversion": 0.0, "is_active": False}
        for _ in range(3)
    ])
    yield
    crm_service._db().client.drop_database("crm_db_test")
    crm_service._db().client.drop_database(SRC_DB)


def test_run_mirrors_and_flags_underperformer(env):
    stats = agent.run(source_db=SRC_DB, source_collection="cint_surveys")
    assert stats["scanned"] == 3  # GoodBuyer, BadBuyer, TinyBuyer
    assert stats["mirrored"] == 3
    assert stats["flagged"] == 1  # BadBuyer only -- TinyBuyer below the survey floor
    assert stats["errors"] == 0

    mirror = crm_service._db()["cint_buyer_mirror"]
    assert mirror.count_documents({}) == 3
    good = mirror.find_one({"account_name": "GoodBuyer"})
    assert good["tier"] == "strong"
    bad = mirror.find_one({"account_name": "BadBuyer"})
    assert bad["tier"] == "underperforming"

    decisions = crm_service._col("ai_decisions").count_documents(
        {"agent_name": "cint_intelligence_agent"})
    assert decisions == 1


def test_tiny_buyer_is_not_flagged_despite_bad_tier(env):
    """TinyBuyer (3 surveys, all deactivated) scores as underperforming by
    the pure function, but MIN_SURVEYS_FOR_SCORING must keep it from being
    flagged -- a statistically meaningless sample shouldn't generate a
    review task."""
    agent.run(source_db=SRC_DB, source_collection="cint_surveys")
    mirror = crm_service._db()["cint_buyer_mirror"]
    tiny = mirror.find_one({"account_name": "TinyBuyer"})
    assert tiny["tier"] == "underperforming"  # the pure scorer has no floor
    decisions = crm_service._col("ai_decisions").count_documents(
        {"agent_name": "cint_intelligence_agent",
         "input_summary.account_name": "TinyBuyer"})
    assert decisions == 0  # but run() didn't flag it


def test_dry_run_writes_nothing(env):
    stats = agent.run(source_db=SRC_DB, source_collection="cint_surveys", dry_run=True)
    assert stats["scanned"] == 3
    assert crm_service._db()["cint_buyer_mirror"].count_documents({}) == 0
    assert crm_service._col("ai_decisions").count_documents(
        {"agent_name": "cint_intelligence_agent"}) == 0
